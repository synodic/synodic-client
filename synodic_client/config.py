"""Persistent configuration for the Synodic Client.

Two configuration layers are supported:

- **LocalConfiguration** — a portable ``config.json`` next to the executable
  (frozen builds only).  Written by the packaging script for dev builds.
  Fields set here override the global configuration.

- **GlobalConfiguration** — a user-scoped ``config.json`` in the OS application
  data directory.  On Windows this is ``%LOCALAPPDATA%/Synodic/config.json``.
  Persisted by the Settings UI.

Merging and resolution of these layers is handled by
:mod:`synodic_client.resolution`.
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


class _ConfigBase(BaseModel):
    """Shared fields for both configuration layers."""

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


class LocalConfiguration(_ConfigBase):
    """Portable configuration embedded next to the executable.

    Written by the packaging script (e.g. ``pdm run package -- --local-source``).
    Fields set here override the corresponding ``GlobalConfiguration`` values.
    """


class GlobalConfiguration(_ConfigBase):
    """User-scoped configuration persisted in the OS application data directory.

    On Windows: ``%LOCALAPPDATA%/Synodic/config.json``.
    """


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


def _load_local_config() -> LocalConfiguration | None:
    """Load the portable local configuration, if present.

    Returns:
        The loaded local config, or None.
    """
    portable = _portable_config_path()
    if portable is None:
        return None

    try:
        data = json.loads(portable.read_text(encoding='utf-8'))
        config = LocalConfiguration.model_validate(data)
        logger.debug('Loaded local config from %s', portable)
        return config
    except Exception:
        logger.exception('Failed to load local config from %s', portable)
        return None


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


def _load_global_config() -> GlobalConfiguration:
    """Load the global configuration from the OS data directory.

    Returns:
        The loaded or default global configuration.
    """
    path = config_dir() / _CONFIG_FILENAME
    if not path.exists():
        logger.debug('No global config at %s, using defaults', path)
        return GlobalConfiguration()

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        config = GlobalConfiguration.model_validate(data)
        logger.debug('Loaded global config from %s', path)
        return config
    except Exception:
        logger.exception('Failed to load global config from %s, using defaults', path)
        return GlobalConfiguration()


def save_config(config: GlobalConfiguration) -> None:
    """Save configuration to the global (system) config directory.

    Args:
        config: The configuration to persist.
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _CONFIG_FILENAME

    try:
        path.write_text(config.model_dump_json(indent=2), encoding='utf-8')
        logger.info('Saved config to %s', path)
    except Exception:
        logger.exception('Failed to save config to %s', path)
