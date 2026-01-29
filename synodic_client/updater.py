"""Self-update functionality using TUF and porringer."""

import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from packaging.version import Version
from porringer.api import API
from porringer.schema import CheckUpdateParameters, DownloadParameters, UpdateSource
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
            UpdateInfo with details about available updates
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

        Args:
            progress_callback: Optional callback for progress updates (received, total)

        Returns:
            Path to the downloaded file, or None on failure
        """
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
                # Fallback: Direct download via porringer (development mode)
                logger.warning('TUF repository not available, using direct download')
                self._download_direct(download_path, progress_callback)

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

        For frozen executables: Replaces the executable with the new version.
        For dev mode: Rebuilds with PyInstaller.

        Returns:
            True if update was applied successfully
        """
        if self._state != UpdateState.DOWNLOADED or not self._downloaded_path:
            logger.error('No downloaded update to apply')
            return False

        self._state = UpdateState.APPLYING

        try:
            if self.is_frozen:
                return self._apply_frozen_update()
            else:
                return self._apply_dev_update()

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

    def _download_direct(self, download_path: Path, progress_callback: Callable | None = None) -> None:
        """Download update directly via porringer (fallback for dev mode).

        Args:
            download_path: Destination path
            progress_callback: Progress callback
        """
        if not self._update_info or not self._update_info.download_url:
            raise ValueError('No download URL available')

        params = DownloadParameters(
            url=self._update_info.download_url,
            destination=download_path,
        )

        self._porringer.update.download(params, progress_callback)

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
        """Apply update on Windows using a batch script.

        Args:
            current_exe: Path to current executable
            new_exe: Path to new executable
            backup_path: Path to backup

        Returns:
            True if update script was created successfully
        """
        # Create a batch script that will run after we exit
        script_path = self._config.download_dir / 'update.bat'

        script_content = f'''@echo off
echo Waiting for application to close...
timeout /t 2 /nobreak > nul
echo Applying update...
copy /y "{new_exe}" "{current_exe}"
if errorlevel 1 (
    echo Update failed, restoring backup...
    copy /y "{backup_path}" "{current_exe}"
    exit /b 1
)
echo Update complete, starting application...
start "" "{current_exe}"
del "%~f0"
'''

        script_path.write_text(script_content)

        # Schedule the script to run
        # Windows-specific process creation flags
        flags = 0
        if sys.platform == 'win32':
            # CREATE_NEW_CONSOLE = 0x00000200, DETACHED_PROCESS = 0x00000008
            flags = 0x00000200 | 0x00000008
        
        subprocess.Popen(
            ['cmd', '/c', str(script_path)],
            creationflags=flags,
        )

        self._state = UpdateState.APPLIED
        logger.info('Windows update script scheduled')
        return True

    def _apply_dev_update(self) -> bool:
        """Apply update in development mode by rebuilding with PyInstaller.

        Returns:
            True if successful
        """
        logger.info('Development mode: Rebuilding with PyInstaller')

        # Find the spec file
        spec_file = Path(__file__).parent.parent.parent / 'tool' / 'pyinstaller' / 'synodic.spec'

        if not spec_file.exists():
            raise FileNotFoundError(f'PyInstaller spec file not found: {spec_file}')

        # First, update the package
        logger.info('Updating package via pip...')
        pip_cmd = [sys.executable, '-m', 'pip', 'install', '--upgrade']

        if self._config.include_prereleases:
            pip_cmd.append('--pre')

        pip_cmd.append(self._config.package_name)

        pip_result = subprocess.run(pip_cmd, capture_output=True, text=True, check=False)

        if pip_result.returncode != 0:
            raise RuntimeError(f'Pip upgrade failed: {pip_result.stderr}')

        # Rebuild with PyInstaller
        logger.info('Rebuilding with PyInstaller...')
        pyinstaller_cmd = [sys.executable, '-m', 'PyInstaller', '--clean', str(spec_file)]

        build_result = subprocess.run(
            pyinstaller_cmd, capture_output=True, text=True, cwd=spec_file.parent.parent.parent, check=False
        )

        if build_result.returncode != 0:
            raise RuntimeError(f'PyInstaller build failed: {build_result.stderr}')

        self._state = UpdateState.APPLIED
        logger.info('Development build complete')
        return True
