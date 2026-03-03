"""Self-update functionality using Velopack.

This module handles self-updates for synodic-client using Velopack,
which manages the full update lifecycle including download, verification,
and installation.

For non-installed (development) environments, updates are not supported.
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from typing import Any

import velopack
from packaging.version import Version

from synodic_client.protocol import remove_protocol
from synodic_client.startup import remove_startup

logger = logging.getLogger(__name__)

# GitHub repository base URL.  Transformed into a release-asset URL
# by :func:`github_release_asset_url` at resolution time so that
# Velopack's ``HttpSource`` can fetch ``releases.{channel}.json``
# from the correct GitHub Releases download path.
GITHUB_REPO_URL = 'https://github.com/synodic/synodic-client'

# Fixed tag used for rolling development releases on GitHub.
_DEV_RELEASE_TAG = 'dev'


def pep440_to_semver(version_string: str) -> str:
    """Convert a PEP 440 version string to a SemVer string for Velopack.

    Velopack requires strict SemVer (``MAJOR.MINOR.PATCH[-pre.N]``) while
    Python tooling produces PEP 440 (e.g. ``0.1.dev47+g799543c``).  This
    function bridges the two:

    * Normalises the base to three components (``0.1`` → ``0.1.0``).
    * Converts ``.devN`` to ``-dev.N``.
    * Strips local segments (``+g…``).
    * Stable versions pass through unchanged (``1.0.0`` → ``1.0.0``).

    Examples::

        >>> pep440_to_semver('0.1.dev47+g799543c')
        '0.1.0-dev.47'
        >>> pep440_to_semver('0.1.1.dev3')
        '0.1.1-dev.3'
        >>> pep440_to_semver('1.0.0')
        '1.0.0'

    Args:
        version_string: A PEP 440 version string.

    Returns:
        A SemVer-compatible version string.
    """
    v = Version(version_string)
    base = f'{v.major}.{v.minor}.{v.micro}'
    if v.dev is not None:
        return f'{base}-dev.{v.dev}'
    return base


def github_release_asset_url(repo_url: str, channel: UpdateChannel) -> str:
    """Convert a GitHub repository URL into a release-asset download URL.

    Velopack's runtime SDK uses a plain ``HttpSource`` that requests
    ``{base_url}/releases.{channel}.json``.  GitHub serves release assets
    at ``{repo}/releases/download/{tag}/`` (for a specific tag) or
    ``{repo}/releases/latest/download/`` (auto-resolves to the newest
    non-prerelease release).

    * **Development** channel → ``/releases/download/dev/``
    * **Stable** channel → ``/releases/latest/download/``

    Non-GitHub URLs (local paths, custom HTTP servers) are returned
    unchanged.

    Args:
        repo_url: A GitHub repository URL or custom update source.
        channel: The resolved update channel.

    Returns:
        A URL (or path) suitable for Velopack's ``UpdateManager``.
    """
    normalized = repo_url.rstrip('/')
    # Only transform URLs that look like a GitHub repository.
    if not normalized.startswith(('https://github.com/', 'http://github.com/')):
        return repo_url

    if channel == UpdateChannel.DEVELOPMENT:
        return f'{normalized}/releases/download/{_DEV_RELEASE_TAG}'
    return f'{normalized}/releases/latest/download'


# Map sys.platform values to Velopack channel suffixes
_PLATFORM_SUFFIXES: dict[str, str] = {
    'win32': 'win',
    'linux': 'linux',
    'darwin': 'osx',
}


def platform_suffix() -> str:
    """Return the Velopack channel suffix for the current platform."""
    try:
        return _PLATFORM_SUFFIXES[sys.platform]
    except KeyError:
        raise RuntimeError(f'Unsupported platform for updates: {sys.platform}') from None


class UpdateChannel(StrEnum):
    """Update channel selection."""

    STABLE = 'stable'
    DEVELOPMENT = 'development'


class UpdateState(Enum):
    """State of an update operation."""

    NO_UPDATE = auto()
    UPDATE_AVAILABLE = auto()
    DOWNLOADING = auto()
    DOWNLOADED = auto()
    APPLYING = auto()
    APPLIED = auto()
    FAILED = auto()


@dataclass
class UpdateInfo:
    """Information about an available update."""

    available: bool
    current_version: Version
    latest_version: Version | None = None
    error: str | None = None

    # Internal: Velopack update info for download/apply
    _velopack_info: Any = field(default=None, repr=False)


# Default interval for automatic update checks (minutes)
DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES = 5

# Default interval for tool update checks (minutes)
DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES = 5


@dataclass
class UpdateConfig:
    """Configuration for the updater."""

    # GitHub repository URL for Velopack to discover releases
    repo_url: str = GITHUB_REPO_URL

    # Channel determines whether to use dev or stable releases
    channel: UpdateChannel = UpdateChannel.STABLE

    # Interval in minutes between automatic update checks (0 = disabled)
    auto_update_interval_minutes: int = DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    # Interval in minutes between tool update checks (0 = disabled)
    tool_update_interval_minutes: int = DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    @property
    def channel_name(self) -> str:
        """Get the channel name for Velopack.

        Combines the update track (dev/stable) with a platform suffix
        so each OS has its own release manifest and nupkg files.
        """
        base = 'dev' if self.channel == UpdateChannel.DEVELOPMENT else 'stable'
        suffix = platform_suffix()
        return f'{base}-{suffix}'


class Updater:
    """Handles self-update operations using Velopack."""

    def __init__(self, current_version: Version, config: UpdateConfig | None = None) -> None:
        """Initialize the updater.

        Args:
            current_version: The current version of the application
            config: Update configuration, uses defaults if not provided
        """
        self._current_version = current_version
        self._config = config or UpdateConfig()
        self._state = UpdateState.NO_UPDATE
        self._update_info: UpdateInfo | None = None
        self._velopack_manager: Any = None
        self._velopack_not_installed: bool = False

        logger.info(
            'Updater created: version=%s, channel=%s, repo=%s',
            self._current_version,
            self._config.channel_name,
            self._config.repo_url,
        )

    @property
    def current_version(self) -> Version:
        """Best-known application version.

        Returns the Velopack-installed version when available, otherwise
        the version from Python package metadata passed at construction.
        """
        return self._current_version

    @property
    def state(self) -> UpdateState:
        """Current state of the update process."""
        return self._state

    @property
    def is_installed(self) -> bool:
        """Check if running as a Velopack-installed application.

        Delegates to ``_get_velopack_manager`` which creates the
        ``UpdateManager``.  The SDK constructor raises ``RuntimeError``
        with *"not properly installed"* when no Velopack manifest is
        found; that specific error is treated as "not installed" while
        all other failures propagate.
        """
        try:
            return self._get_velopack_manager() is not None
        except RuntimeError:
            return False

    def check_for_update(self) -> UpdateInfo:
        """Check for available updates.

        Returns:
            UpdateInfo with details about available updates.
        """
        try:
            manager = self._get_velopack_manager()
            if manager is None:
                logger.info('Not a Velopack install, skipping update check')
                return UpdateInfo(
                    available=False,
                    current_version=self._current_version,
                    error='Not installed via Velopack',
                )

            velopack_info = manager.check_for_updates()

            if velopack_info is not None:
                latest = Version(velopack_info.TargetFullRelease.Version)

                self._update_info = UpdateInfo(
                    available=True,
                    current_version=self._current_version,
                    latest_version=latest,
                    _velopack_info=velopack_info,
                )
                self._state = UpdateState.UPDATE_AVAILABLE
                logger.info('Update available: %s -> %s', self._current_version, latest)
            else:
                self._update_info = UpdateInfo(
                    available=False,
                    current_version=self._current_version,
                )
                self._state = UpdateState.NO_UPDATE
                logger.info('No update available, current version: %s', self._current_version)

            return self._update_info

        except Exception as e:
            if '404' in str(e):
                channel = self._config.channel_name
                msg = (
                    f"No releases found for the '{channel}' channel. "
                    "Try switching to the 'Development' channel in Settings \u2192 Channel."
                )
                logger.debug('No releases for channel %s: %s', channel, e)
                self._state = UpdateState.NO_UPDATE
                return UpdateInfo(
                    available=False,
                    current_version=self._current_version,
                    error=msg,
                )

            logger.exception('Failed to check for updates')
            self._state = UpdateState.FAILED
            return UpdateInfo(
                available=False,
                current_version=self._current_version,
                error=str(e),
            )

    def download_update(self, progress_callback: Callable[[int], None] | None = None) -> bool:
        """Download the update.

        Args:
            progress_callback: Optional callback for progress updates (0-100)

        Returns:
            True if download succeeded, False otherwise
        """
        if not self.is_installed:
            raise NotImplementedError('Updates are only supported for Velopack installs')

        if self._state != UpdateState.UPDATE_AVAILABLE or not self._update_info:
            logger.error('No update available to download')
            return False

        if self._update_info._velopack_info is None:
            logger.error('No Velopack update info available')
            return False

        self._state = UpdateState.DOWNLOADING
        logger.info('Starting update download for %s', self._update_info._velopack_info)

        try:
            manager = self._get_velopack_manager()
            if manager is None:
                raise RuntimeError('Velopack manager not available')

            manager.download_updates(self._update_info._velopack_info, progress_callback)

            self._state = UpdateState.DOWNLOADED
            logger.info('Update downloaded successfully')
            return True

        except Exception as e:
            logger.exception('Failed to download update')
            self._state = UpdateState.FAILED
            self._update_info.error = str(e)
            return False

    def apply_update_on_exit(self, restart: bool = True, restart_args: list[str] | None = None) -> None:
        """Apply the downloaded update, optionally restarting the application.

        When *restart* is ``True`` the Velopack runtime applies the update
        **and** relaunches the new version (the call does not return).
        When ``False`` the update is staged and applied after the process
        exits without relaunching.

        Args:
            restart: Whether to restart the application after applying.
            restart_args: Optional arguments to pass to the restarted application.
        """
        if not self.is_installed:
            raise NotImplementedError('Updates are only supported for Velopack installs')

        if self._state != UpdateState.DOWNLOADED or not self._update_info:
            raise RuntimeError('No downloaded update to apply')

        if self._update_info._velopack_info is None:
            raise RuntimeError('No Velopack update info available')

        try:
            manager = self._get_velopack_manager()
            if manager is None:
                raise RuntimeError('Velopack manager not available')

            logger.info('Applying update (restart=%s)', restart)

            if restart:
                self._state = UpdateState.APPLYING
                if restart_args:
                    manager.apply_updates_and_restart_with_args(
                        self._update_info._velopack_info,
                        restart_args,
                    )
                else:
                    manager.apply_updates_and_restart(self._update_info._velopack_info)
                # apply_updates_and_restart terminates the process;
                # fall through only as a safety net.
                sys.exit(0)
            else:
                manager.apply_updates_and_exit(self._update_info._velopack_info)
                self._state = UpdateState.APPLIED

        except Exception as e:
            logger.exception('Failed to apply update')
            self._state = UpdateState.FAILED
            self._update_info.error = str(e)
            raise

    _NOT_INSTALLED_SENTINEL = 'not properly installed'
    """Substring the Velopack SDK includes in its ``RuntimeError`` when
    the application was not installed via Velopack."""

    def _get_velopack_manager(self) -> Any:
        """Get or create the Velopack UpdateManager.

        Returns:
            UpdateManager instance, or ``None`` when the application is
            not running from a Velopack installation.

        Raises:
            RuntimeError: If the ``UpdateManager`` could not be created
                for a reason *other* than the app not being installed
                (e.g. a genuine SDK or configuration problem).
        """
        if self._velopack_manager is not None:
            return self._velopack_manager

        if self._velopack_not_installed:
            return None

        try:
            options = velopack.UpdateOptions(
                AllowVersionDowngrade=False,
                MaximumDeltasBeforeFallback=10,  # required by the SDK
            )
            options.ExplicitChannel = self._config.channel_name

            self._velopack_manager = velopack.UpdateManager(
                self._config.repo_url,
                options,
            )

            # The Velopack-installed version is authoritative; Python
            # package metadata may be stale after an in-place update.
            self._current_version = Version(
                self._velopack_manager.get_current_version(),
            )

            logger.debug(
                'Velopack manager created: app_id=%s, version=%s, portable=%s',
                self._velopack_manager.get_app_id(),
                self._current_version,
                self._velopack_manager.get_is_portable(),
            )
            return self._velopack_manager
        except RuntimeError as e:
            if self._NOT_INSTALLED_SENTINEL in str(e).lower():
                logger.debug('Not a Velopack install: %s', e)
                self._velopack_not_installed = True
                return None
            logger.warning('Velopack manager creation failed: %s', e)
            raise
        except Exception as e:
            logger.warning('Velopack manager creation failed: %s', e)
            raise RuntimeError(f'Failed to create Velopack UpdateManager: {e}') from e


def _on_before_uninstall(version: str) -> None:
    """Velopack hook: called before the app is uninstalled.

    Removes the ``synodic://`` URI protocol handler and auto-startup
    registrations.

    Args:
        version: The current version string (provided by Velopack).
    """
    logger.info('Velopack uninstall hook fired for version %s', version)
    try:
        remove_protocol()
        logger.info('Protocol handler removed successfully')
    except Exception:
        logger.warning('Protocol removal failed during uninstall hook', exc_info=True)
    try:
        remove_startup()
        logger.info('Auto-startup registration removed successfully')
    except Exception:
        logger.warning('Auto-startup removal failed during uninstall hook', exc_info=True)


_velopack_initialized = False


def initialize_velopack() -> None:
    """Initialize Velopack at application startup.

    This should be called as early as possible in the application lifecycle,
    before any UI is shown. Velopack may need to perform cleanup or apply
    pending updates.

    Safe to call more than once — subsequent calls are no-ops.

    .. note::

        The SDK's callback hooks only accept ``PyCFunction`` — add an
        uninstall hook here when that is fixed upstream.
    """
    global _velopack_initialized  # noqa: PLW0603
    if _velopack_initialized:
        return
    _velopack_initialized = True

    logger.info('Initializing Velopack (exe=%s)', sys.executable)
    try:
        app = velopack.App()
        app.run()
        logger.info('Velopack initialized successfully')
    except Exception as e:
        logger.info('Velopack initialization skipped (not a Velopack install): %s', e)
