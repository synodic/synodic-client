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
"""

import json
import logging
import os
import sys
from pathlib import Path

from synodic_client.schema import BuildConfig, UserConfig

logger = logging.getLogger(__name__)

_APP_NAME = 'Synodic'
_APP_NAME_DEV = 'Synodic-Dev'
_CONFIG_FILENAME = 'config.json'


class _DevMode:
    """Module-level mutable state (avoids ``global`` statements)."""

    enabled: bool = False


def set_dev_mode(enabled: bool) -> None:
    """Enable or disable dev-mode path namespacing.

    When enabled, :func:`config_dir` returns a separate directory so that
    the development build does not share state with the user-installed
    application.

    Must be called **before** any configuration is loaded.

    Args:
        enabled: ``True`` to activate dev-mode namespacing.
    """
    _DevMode.enabled = enabled


def is_dev_mode() -> bool:
    """Return whether dev-mode namespacing is active."""
    return _DevMode.enabled


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_build_config() -> BuildConfig | None:
    """Load the portable build configuration next to the executable.

    Only applicable when running as a frozen (PyInstaller) build and a
    ``config.json`` file exists next to the executable.

    Returns:
        The loaded build config, or ``None`` when not in a frozen build
        or no portable config exists.
    """
    if not getattr(sys, 'frozen', False):
        return None

    path = Path(sys.executable).resolve().parent / _CONFIG_FILENAME
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        config = BuildConfig.model_validate(data)
        logger.debug('Loaded build config from %s', path)
        return config
    except Exception:
        logger.exception('Failed to load build config from %s', path)
        return None


def config_dir() -> Path:
    """Return the platform-appropriate global configuration directory.

    When dev-mode is active (see :func:`set_dev_mode`) the returned path
    is namespaced (e.g. ``Synodic-Dev``) so that development and
    user-installed builds maintain independent configuration.

    Returns:
        Path to the configuration directory.
    """
    app_name = _APP_NAME_DEV if _DevMode.enabled else _APP_NAME

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
