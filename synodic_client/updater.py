"""Self-update functionality using TUF and porringer.

This module handles self-updates for synodic-client with two strategies:

1. **Frozen executables** : Uses TUF
   for cryptographically verified binary downloads from GitHub releases.
   The binary is replaced in-place with automatic backup and rollback support.

2. **Python package installs** : Delegates to porringer for version
   checking. Users are instructed to run their package manager's upgrade command
   manually, as pip/pipx handle their own security and dependency resolution.
"""

import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from packaging.version import Version
from porringer.api import API
from porringer.schema import CheckUpdateParameters, UpdateSource
from tuf.api.exceptions import DownloadError, RepositoryError
from tuf.ngclient import Updater as TUFUpdater

logger = logging.getLogger(__name__)


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
    ROLLBACK_REQUIRED = auto()


@dataclass
class UpdateInfo:
    """Information about an available update."""

    available: bool
    current_version: Version
    latest_version: Version | None = None
    download_url: str | None = None
    target_name: str | None = None
    file_size: int | None = None
    error: str | None = None


@dataclass
class UpdateConfig:
    """Configuration for the updater."""

    # PyPI package name for version checks
    package_name: str = 'synodic_client'

    # TUF repository URL for secure artifact download (GitHub Pages from tuf-on-ci)
    tuf_repository_url: str = 'https://synodic.github.io/synodic-updates'

    # Channel determines whether to include prereleases
    channel: UpdateChannel = UpdateChannel.STABLE

    # Local paths
    metadata_dir: Path = field(default_factory=lambda: Path.home() / '.synodic' / 'tuf_metadata')
    download_dir: Path = field(default_factory=lambda: Path.home() / '.synodic' / 'downloads')
    backup_dir: Path = field(default_factory=lambda: Path.home() / '.synodic' / 'backup')

    @property
    def include_prereleases(self) -> bool:
        """Whether to include prerelease versions."""
        return self.channel == UpdateChannel.DEVELOPMENT


class Updater:
    """Handles self-update operations using TUF for security and porringer for downloads."""

    def __init__(self, current_version: Version, porringer_api: API, config: UpdateConfig | None = None) -> None:
        """Initialize the updater.

        Args:
            current_version: The current version of the application
            porringer_api: The porringer API instance for download operations
            config: Update configuration, uses defaults if not provided
        """
        self._current_version = current_version
        self._porringer = porringer_api
        self._config = config or UpdateConfig()
        self._state = UpdateState.NO_UPDATE
        self._update_info: UpdateInfo | None = None
        self._downloaded_path: Path | None = None

        # Ensure directories exist
        self._config.metadata_dir.mkdir(parents=True, exist_ok=True)
        self._config.download_dir.mkdir(parents=True, exist_ok=True)
        self._config.backup_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state(self) -> UpdateState:
        """Current state of the update process."""
        return self._state

    @property
    def is_frozen(self) -> bool:
        """Check if running as a frozen executable (PyInstaller)."""
        return getattr(sys, 'frozen', False)

    @property
    def executable_path(self) -> Path:
        """Get the path to the current executable."""
        if self.is_frozen:
            return Path(sys.executable)
        # In dev mode, return the script path
        return Path(sys.argv[0]).resolve()

    def check_for_update(self) -> UpdateInfo:
        """Check PyPI for available updates.

        Returns:
            UpdateInfo with details about available updates.
        """
        try:
            params = CheckUpdateParameters(
                source=UpdateSource.PYPI,
                current_version=str(self._current_version),
                package_name=self._config.package_name,
                include_prereleases=self._config.include_prereleases,
            )

            result = self._porringer.update.check(params)

            if result.available and result.latest_version:
                latest = Version(str(result.latest_version))

                self._update_info = UpdateInfo(
                    available=True,
                    current_version=self._current_version,
                    latest_version=latest,
                    download_url=result.download_url,
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

    def download_update(self, progress_callback: Callable | None = None) -> Path | None:
        """Download the update artifact using TUF for verification.

        This method is only applicable for frozen executables. For pip/pipx installs,
        use the upgrade_command from UpdateInfo instead.

        Args:
            progress_callback: Optional callback for progress updates (received, total)

        Returns:
            Path to the downloaded file, or None on failure
        """
        if not self.is_frozen:
            raise NotImplementedError('Updates for pip/pipx installs are not yet supported')

        if self._state != UpdateState.UPDATE_AVAILABLE or not self._update_info:
            logger.error('No update available to download')
            return None

        self._state = UpdateState.DOWNLOADING

        try:
            # Determine target name based on platform and version
            target_name = self._get_target_name()
            download_path = self._config.download_dir / target_name

            # Use TUF to securely download and verify the artifact
            tuf_updater = self._create_tuf_updater()

            if tuf_updater:
                # TUF-secured download
                target_info = tuf_updater.get_targetinfo(target_name)

                if target_info is None:
                    raise RepositoryError(f'Target {target_name} not found in TUF repository')

                # Download through TUF (handles verification)
                tuf_updater.download_target(target_info, str(self._config.download_dir))
                logger.info('Downloaded and verified update via TUF: %s', download_path)

            else:
                # No TUF available - cannot proceed safely for frozen builds
                raise RepositoryError('TUF repository not available. Cannot securely download update.')

            self._downloaded_path = download_path
            self._state = UpdateState.DOWNLOADED
            return download_path

        except (DownloadError, RepositoryError) as e:
            logger.exception('TUF download/verification failed')
            self._state = UpdateState.FAILED
            self._update_info.error = str(e)
            return None
        except Exception as e:
            logger.exception('Failed to download update')
            self._state = UpdateState.FAILED
            self._update_info.error = str(e)
            return None

    def apply_update(self) -> bool:
        """Apply the downloaded update.

        This method is only applicable for frozen executables. For pip/pipx installs,
        users should run the upgrade_command from UpdateInfo manually.

        Returns:
            True if update was applied successfully
        """
        if not self.is_frozen:
            raise NotImplementedError('Updates for pip/pipx installs are not yet supported')

        if self._state != UpdateState.DOWNLOADED or not self._downloaded_path:
            logger.error('No downloaded update to apply')
            return False

        self._state = UpdateState.APPLYING

        try:
            return self._apply_frozen_update()

        except Exception as e:
            logger.exception('Failed to apply update')
            self._state = UpdateState.ROLLBACK_REQUIRED
            if self._update_info is not None:
                self._update_info.error = str(e)
            return False

    def rollback(self) -> bool:
        """Rollback to the previous version.

        Returns:
            True if rollback was successful
        """
        backup_path = self._get_backup_path()

        if not backup_path.exists():
            logger.error('No backup available for rollback')
            return False

        try:
            current_exe = self.executable_path

            if self.is_frozen:
                # Restore from backup
                shutil.copy2(backup_path, current_exe)
                logger.info('Rolled back to previous version')

            self._state = UpdateState.NO_UPDATE
            return True

        except Exception:
            logger.exception('Rollback failed')
            return False

    def cleanup_backup(self) -> None:
        """Remove the backup after successful update verification."""
        backup_path = self._get_backup_path()

        if backup_path.exists():
            try:
                backup_path.unlink()
                logger.info('Cleaned up backup: %s', backup_path)
            except Exception as e:
                logger.warning('Failed to cleanup backup: %s', e)

    def restart_application(self) -> None:
        """Restart the application with the new version.

        Spawns a new process and exits the current one.
        """
        if self.is_frozen:
            executable = self.executable_path
            args = sys.argv[1:]  # Preserve command line arguments
        else:
            # Dev mode: run via Python interpreter
            executable = Path(sys.executable)
            args = sys.argv

        logger.info('Restarting application: %s %s', executable, args)

        # Spawn new process
        subprocess.Popen(
            [str(executable), *args],
            start_new_session=True,
        )

        # Exit current process
        sys.exit(0)

    def _create_tuf_updater(self) -> TUFUpdater | None:
        """Create a TUF updater instance.

        Returns:
            TUFUpdater instance or None if TUF repository is not configured
        """
        try:
            # Check if we have trusted root metadata
            root_path = self._config.metadata_dir / 'root.json'

            if not root_path.exists():
                # Try to bootstrap from bundled root metadata
                bundled_root = self._get_bundled_root_metadata()
                if bundled_root and bundled_root.exists():
                    shutil.copy2(bundled_root, root_path)
                else:
                    logger.warning('No TUF root metadata available')
                    return None

            return TUFUpdater(
                metadata_dir=str(self._config.metadata_dir),
                metadata_base_url=f'{self._config.tuf_repository_url}/metadata',
                target_base_url=f'{self._config.tuf_repository_url}/targets',
                target_dir=str(self._config.download_dir),
            )

        except Exception as e:
            logger.warning('Failed to initialize TUF updater: %s', e)
            return None

    def _get_bundled_root_metadata(self) -> Path | None:
        """Get the path to bundled TUF root metadata.

        Returns:
            Path to root.json if bundled, None otherwise
        """
        if self.is_frozen:
            # PyInstaller bundle - _MEIPASS is set by PyInstaller at runtime
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass is not None:
                bundle_dir = Path(meipass)
                root_path = bundle_dir / 'data' / 'tuf_root.json'
            else:
                return None
        else:
            # Development mode
            root_path = Path(__file__).parent.parent / 'data' / 'tuf_root.json'

        return root_path if root_path.exists() else None

    def _get_target_name(self) -> str:
        """Get the target artifact name for the current platform.

        Returns:
            Target name string
        """
        version = self._update_info.latest_version if self._update_info else self._current_version

        if sys.platform == 'win32':
            return f'synodic-{version}-windows-x64.exe'
        elif sys.platform == 'darwin':
            return f'synodic-{version}-macos-x64'
        else:
            return f'synodic-{version}-linux-x64'

    def _get_backup_path(self) -> Path:
        """Get the path for the backup executable.

        Returns:
            Path to backup location
        """
        exe_name = self.executable_path.name
        return self._config.backup_dir / f'{exe_name}.backup'

    def _apply_frozen_update(self) -> bool:
        """Apply update to a frozen executable.

        Returns:
            True if successful
        """
        current_exe = self.executable_path
        backup_path = self._get_backup_path()
        new_exe = self._downloaded_path

        if new_exe is None:
            logger.error('No downloaded executable found')
            return False

        # Create backup of current executable
        logger.info('Creating backup: %s -> %s', current_exe, backup_path)
        shutil.copy2(current_exe, backup_path)

        # On Windows, we can't replace a running executable directly
        # We need to use a helper script or rename approach
        if sys.platform == 'win32':
            return self._apply_windows_update(current_exe, new_exe, backup_path)
        else:
            # Unix: Can replace executable while running
            shutil.copy2(new_exe, current_exe)
            self._state = UpdateState.APPLIED
            logger.info('Update applied successfully')
            return True

    def _apply_windows_update(self, current_exe: Path, new_exe: Path, backup_path: Path) -> bool:
        """Apply update on Windows using rename-then-replace.

        Windows allows renaming a running executable but not overwriting it.
        We rename the current exe, copy the new one to the original path,
        then the app can restart normally. The old exe is cleaned up on next launch.

        Args:
            current_exe: Path to current executable
            new_exe: Path to new executable
            backup_path: Path to backup (already created by caller)

        Returns:
            True if update was applied successfully
        """
        # Mark the old exe for cleanup (rename it so we can place new one)
        old_exe_path = current_exe.with_suffix('.exe.old')

        # Remove any previous .old file from earlier updates
        # May fail if still locked from a very recent restart, that's ok
        with suppress(OSError):
            if old_exe_path.exists():
                old_exe_path.unlink()

        try:
            # Rename running exe (Windows allows this)
            current_exe.rename(old_exe_path)
            logger.info('Renamed running executable: %s -> %s', current_exe, old_exe_path)

            # Copy new exe to original location
            shutil.copy2(new_exe, current_exe)
            logger.info('Installed new executable: %s', current_exe)

            self._state = UpdateState.APPLIED
            logger.info('Windows update applied successfully (restart required)')
            return True

        except OSError as e:
            logger.exception('Failed to apply Windows update via rename')
            # Try to restore if rename succeeded but copy failed
            if old_exe_path.exists() and not current_exe.exists():
                with suppress(OSError):
                    old_exe_path.rename(current_exe)
            raise RuntimeError(f'Windows update failed: {e}') from e

    def cleanup_old_executable(self) -> None:
        """Clean up old executable from previous update.

        Call this on application startup to remove the .old file left
        from the rename-then-replace update strategy on Windows.
        """
        if sys.platform != 'win32' or not self.is_frozen:
            return

        old_exe_path = self.executable_path.with_suffix('.exe.old')
        if old_exe_path.exists():
            try:
                old_exe_path.unlink()
                logger.info('Cleaned up old executable: %s', old_exe_path)
            except OSError as e:
                logger.warning('Failed to clean up old executable: %s', e)
