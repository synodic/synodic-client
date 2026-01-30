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
from enum import Enum, auto
from typing import Any

import velopack
from packaging.version import Version

logger = logging.getLogger(__name__)

# GitHub repository for Velopack updates
# Velopack automatically discovers releases from GitHub releases
GITHUB_REPO_URL = 'https://github.com/synodic/synodic-client'


class UpdateChannel(Enum):
    """Update channel selection."""

    STABLE = auto()
    DEVELOPMENT = auto()


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


@dataclass
class UpdateConfig:
    """Configuration for the updater."""

    # GitHub repository URL for Velopack to discover releases
    repo_url: str = GITHUB_REPO_URL

    # Channel determines whether to use dev or stable releases
    channel: UpdateChannel = UpdateChannel.STABLE

    @property
    def channel_name(self) -> str:
        """Get the channel name for Velopack."""
        return 'dev' if self.channel == UpdateChannel.DEVELOPMENT else 'stable'


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

    @property
    def state(self) -> UpdateState:
        """Current state of the update process."""
        return self._state

    @property
    def is_installed(self) -> bool:
        """Check if running as a Velopack-installed application."""
        try:
            manager = self._get_velopack_manager()
            # If we can get the manager and it has a version, we're installed
            return manager is not None
        except Exception:
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
                latest = Version(velopack_info.target_full_release.version)

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

    def apply_update_and_restart(self, restart_args: list[str] | None = None) -> None:
        """Apply the downloaded update and restart the application.

        This method will not return - it exits the current process
        and launches the updated version.

        Args:
            restart_args: Optional arguments to pass to the restarted application
        """
        if not self.is_installed:
            raise NotImplementedError('Updates are only supported for Velopack installs')

        if self._state != UpdateState.DOWNLOADED or not self._update_info:
            raise RuntimeError('No downloaded update to apply')

        if self._update_info._velopack_info is None:
            raise RuntimeError('No Velopack update info available')

        self._state = UpdateState.APPLYING

        try:
            manager = self._get_velopack_manager()
            if manager is None:
                raise RuntimeError('Velopack manager not available')

            logger.info('Applying update and restarting...')
            if restart_args:
                manager.apply_updates_and_restart_with_args(
                    self._update_info._velopack_info,
                    restart_args,
                )
            else:
                manager.apply_updates_and_restart(self._update_info._velopack_info)
            # This should not return, but just in case
            sys.exit(0)

        except Exception as e:
            logger.exception('Failed to apply update')
            self._state = UpdateState.FAILED
            self._update_info.error = str(e)
            raise

    def apply_update_on_exit(self, restart: bool = True, restart_args: list[str] | None = None) -> None:
        """Schedule the update to be applied when the application exits.

        Unlike apply_update_and_restart, this method returns immediately
        and the update is applied after the application exits gracefully.

        Args:
            restart: Whether to restart the application after applying
            restart_args: Optional arguments to pass to the restarted application
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

            logger.info('Scheduling update to apply on exit (restart=%s)', restart)
            # Velopack apply_updates_and_exit applies on exit
            # Note: The restart parameter is not supported by Velopack's exit method
            # The app will need to be manually restarted or use apply_updates_and_restart
            manager.apply_updates_and_exit(self._update_info._velopack_info)
            self._state = UpdateState.APPLIED

        except Exception as e:
            logger.exception('Failed to schedule update')
            self._state = UpdateState.FAILED
            self._update_info.error = str(e)
            raise

    def _get_velopack_manager(self) -> Any:
        """Get or create the Velopack UpdateManager.

        Returns:
            UpdateManager instance, or None if not installed via Velopack
        """
        if self._velopack_manager is not None:
            return self._velopack_manager

        try:
            options = velopack.UpdateOptions()  # type: ignore[attr-defined]
            options.allow_version_downgrade = False
            options.explicit_channel = self._config.channel_name

            self._velopack_manager = velopack.UpdateManager(  # type: ignore[attr-defined]
                self._config.repo_url,
                options,
            )
            return self._velopack_manager
        except Exception as e:
            logger.debug('Failed to create Velopack manager: %s', e)
            return None


def initialize_velopack() -> None:
    """Initialize Velopack at application startup.

    This should be called as early as possible in the application lifecycle,
    before any UI is shown. Velopack may need to perform cleanup or apply
    pending updates.
    """
    try:
        velopack.App().run()  # type: ignore[attr-defined]
        logger.debug('Velopack initialized')
    except Exception as e:
        logger.debug('Velopack initialization skipped: %s', e)
