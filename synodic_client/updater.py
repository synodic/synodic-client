"""Self-update functionality using Velopack.

This module handles self-updates for synodic-client using Velopack,
which manages the full update lifecycle including download, verification,
and installation.

For non-installed (development) environments, updates are not supported.
"""

import contextlib
import logging
import sys
from collections.abc import Callable
from typing import Any

import velopack
from packaging.version import Version

from synodic_client.protocol import remove_protocol
from synodic_client.schema import (
    UpdateChannel,
    UpdateConfig,
    UpdateInfo,
    UpdateState,
)
from synodic_client.startup import remove_startup

logger = logging.getLogger(__name__)

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

        # Eagerly resolve the Velopack manager so that
        # _current_version reflects the installed binary version
        # rather than the (potentially stale) Python package metadata.
        with contextlib.suppress(Exception):
            self._get_velopack_manager()

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

    def apply_update_on_exit(
        self,
        restart: bool = True,
        silent: bool = False,
        restart_args: list[str] | None = None,
    ) -> None:
        """Stage the downloaded update to apply when the process exits.

        Uses ``wait_exit_then_apply_updates`` which returns immediately.
        The Velopack Update.exe runs after the current process exits,
        applies the update, and optionally relaunches the application.

        The caller is responsible for shutting down the process (e.g.
        ``QApplication.quit()``) after this method returns.

        Args:
            restart: Whether to restart the application after applying.
            silent: When ``True``, suppress the Velopack splash window.
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

            logger.info('Applying update (restart=%s, silent=%s)', restart, silent)
            self._state = UpdateState.APPLYING
            manager.wait_exit_then_apply_updates(
                self._update_info._velopack_info,
                silent=silent,
                restart=restart,
                restart_args=restart_args or [],
            )

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


class _VelopackState:
    """Module-level mutable state (avoids ``global`` statements)."""

    initialized: bool = False


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
    if _VelopackState.initialized:
        return
    _VelopackState.initialized = True

    # During post-update restarts Velopack's App.run() may exit the
    # current process (to apply the update and relaunch).  Each
    # short-lived process writes "Initializing Velopack" to the shared
    # log file before being replaced, so multiple entries followed by a
    # single "initialized successfully" is expected behaviour.
    logger.info('Initializing Velopack (exe=%s)', sys.executable)
    try:
        app = velopack.App()
        app.run()
        logger.info('Velopack initialized successfully')
    except Exception as e:
        logger.info('Velopack initialization skipped (not a Velopack install): %s', e)
