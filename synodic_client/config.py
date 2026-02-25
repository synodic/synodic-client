"""Persistent configuration for the Synodic Client.

Two configuration layers are supported:

- **BuildConfig** — a read-only ``config.json`` next to the executable
  (frozen builds only).  Written by the packaging script for dev builds.
  Contains only ``update_source`` and ``update_channel``.

- **UserConfig** — a user-scoped ``config.json`` in the OS application
  data directory.  On Windows this is ``%LOCALAPPDATA%/Synodic/config.json``.
  Persisted by the Settings UI.  Always contains every field.

Resolution of these layers into an immutable ``ResolvedConfig`` is handled
by :mod:`synodic_client.resolution`.

Back-compat aliases (``GlobalConfiguration``, ``LocalConfiguration``,
``save_config``) are provided at the bottom of the module so that
existing call-sites continue to work during migration.
"""

import json
import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_APP_NAME = 'Synodic'
_APP_NAME_DEV = 'Synodic-Dev'
_CONFIG_FILENAME = 'config.json'

_dev_mode: bool = False


def set_dev_mode(enabled: bool) -> None:
    """Enable or disable dev-mode path namespacing.

    When enabled, :func:`config_dir` returns a separate directory so that
    the development build does not share state with the user-installed
    application.

    Must be called **before** any configuration is loaded.

    Args:
        enabled: ``True`` to activate dev-mode namespacing.
    """
    global _dev_mode  # noqa: PLW0603
    _dev_mode = enabled


def is_dev_mode() -> bool:
    """Return whether dev-mode namespacing is active."""
    return _dev_mode


# ---------------------------------------------------------------------------
# BuildConfig — read-only, lives next to the executable
# ---------------------------------------------------------------------------


class BuildConfig(BaseModel):
    """Read-only configuration embedded next to the executable.

    Written by the packaging script (e.g. ``pdm run package -- --local-source``).
    Only contains the two fields the build system needs to seed.
    """

    # URL or local file path for Velopack releases.
    update_source: str | None = None

    # Update channel: "stable" or "dev".
    update_channel: str | None = None


# ---------------------------------------------------------------------------
# UserConfig — read-write, lives in the OS data directory
# ---------------------------------------------------------------------------


class UserConfig(BaseModel):
    """User-scoped configuration persisted in the OS application data directory.

    On Windows: ``%LOCALAPPDATA%/Synodic/config.json``.

    Every field is always saved.  There are no sparse/unset semantics —
    the on-disk file is a complete snapshot of the user's preferences.
    """

    # URL or local file path for Velopack releases.
    # None means use the default GitHub release source.
    update_source: str | None = None

    # Update channel: "stable" or "dev".
    # None means auto-detect from sys.frozen.
    update_channel: str | None = None

    # Interval in minutes between automatic update checks.
    # 0 disables automatic checking.  None uses the default (30 minutes).
    auto_update_interval_minutes: int | None = None

    # Interval in minutes between tool update checks.
    # 0 disables automatic checking.  None uses the default (20 minutes).
    tool_update_interval_minutes: int | None = None

    # Per-plugin auto-update toggle.  Maps plugin name to enabled state.
    # None or absent means all plugins auto-update.  Explicitly False
    # entries disable auto-update for that plugin.
    plugin_auto_update: dict[str, bool] | None = None

    # Check for updates during dry-run previews.  When True the preview
    # will query package indices for newer versions.
    detect_updates: bool = True

    # Per-manifest pre-release overrides.  Outer key is a normalised
    # manifest path (or URL for remote manifests) produced by
    # ``normalize_manifest_key()``.  Inner value is a sorted list of
    # package names (case-insensitive) that should be checked for
    # pre-release updates even when the manifest does not set
    # ``include_prereleases: true`` on the package.  ``None`` means
    # no overrides anywhere.
    prerelease_packages: dict[str, list[str]] | None = None

    # Whether the application should start automatically with the OS.
    # None means use the default (enabled).  Explicitly False disables
    # auto-startup.
    auto_start: bool | None = None


# ---------------------------------------------------------------------------
# Back-compat aliases (to be removed once all consumers migrate)
# ---------------------------------------------------------------------------

LocalConfiguration = BuildConfig
"""Deprecated alias for :class:`BuildConfig`."""

GlobalConfiguration = UserConfig
"""Deprecated alias for :class:`UserConfig`."""


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def _portable_config_path() -> Path | None:
    """Return the path to a portable config file next to the executable, if it exists.

    Only checked when running as a frozen (PyInstaller) build.

    Returns:
        Path to the portable config file, or None if not applicable.
    """
    if not getattr(sys, 'frozen', False):
        return None

    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / _CONFIG_FILENAME
    if candidate.exists():
        return candidate
    return None


def load_build_config() -> BuildConfig | None:
    """Load the portable build configuration next to the executable.

    Returns:
        The loaded build config, or ``None`` when not in a frozen build
        or no portable config exists.
    """
    portable = _portable_config_path()
    if portable is None:
        return None

    try:
        data = json.loads(portable.read_text(encoding='utf-8'))
        config = BuildConfig.model_validate(data)
        logger.debug('Loaded build config from %s', portable)
        return config
    except Exception:
        logger.exception('Failed to load build config from %s', portable)
        return None


# Keep internal name for backward compat with resolution.py during migration
_load_local_config = load_build_config


def config_dir() -> Path:
    """Return the platform-appropriate global configuration directory.

    When dev-mode is active (see :func:`set_dev_mode`) the returned path
    is namespaced (e.g. ``Synodic-Dev``) so that development and
    user-installed builds maintain independent configuration.

    Returns:
        Path to the configuration directory.
    """
    app_name = _APP_NAME_DEV if _dev_mode else _APP_NAME

    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA', '')
        if not base:
            base = str(Path.home() / 'AppData' / 'Local')
        return Path(base) / app_name
    # Stub for non-Windows platforms
    logger.warning('Config directory is not fully supported on %s', sys.platform)
    return Path.home() / f'.{app_name.lower()}'


def load_user_config() -> UserConfig:
    """Load the user configuration from the OS data directory.

    Returns:
        The loaded or default user configuration.
    """
    path = config_dir() / _CONFIG_FILENAME
    if not path.exists():
        logger.debug('No user config at %s, using defaults', path)
        return UserConfig()

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        config = UserConfig.model_validate(data)
        logger.debug('Loaded user config from %s', path)
        return config
    except Exception:
        logger.exception('Failed to load user config from %s, using defaults', path)
        return UserConfig()


# Keep internal name for backward compat with resolution.py during migration
_load_global_config = load_user_config


def save_user_config(config: UserConfig) -> None:
    """Save configuration to the global (system) config directory.

    All fields are always written.  The on-disk file is a complete
    snapshot of the user's preferences so that no implicit state is
    lost when builds change or new defaults are introduced.

    Args:
        config: The configuration to persist.
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _CONFIG_FILENAME

    try:
        path.write_text(
            config.model_dump_json(indent=2),
            encoding='utf-8',
        )
        logger.info('Saved config to %s', path)
    except Exception:
        logger.exception('Failed to save config to %s', path)


# Back-compat alias
save_config = save_user_config
"""Deprecated alias for :func:`save_user_config`."""
