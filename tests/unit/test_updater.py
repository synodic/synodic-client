"""Tests for the self-update functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from synodic_client.updater import (
    UpdateChannel,
    UpdateConfig,
    UpdateInfo,
    Updater,
    UpdateState,
)


class TestUpdateChannel:
    """Tests for UpdateChannel enum."""

    @staticmethod
    def test_stable_channel_exists() -> None:
        """Verify STABLE channel is defined."""
        assert hasattr(UpdateChannel, 'STABLE')

    @staticmethod
    def test_development_channel_exists() -> None:
        """Verify DEVELOPMENT channel is defined."""
        assert hasattr(UpdateChannel, 'DEVELOPMENT')


class TestUpdateState:
    """Tests for UpdateState enum."""

    @staticmethod
    def test_all_states_exist() -> None:
        """Verify all expected states are defined."""
        expected_states = [
            'NO_UPDATE',
            'UPDATE_AVAILABLE',
            'DOWNLOADING',
            'DOWNLOADED',
            'APPLYING',
            'APPLIED',
            'FAILED',
            'ROLLBACK_REQUIRED',
        ]
        for state_name in expected_states:
            assert hasattr(UpdateState, state_name)


class TestUpdateInfo:
    """Tests for UpdateInfo dataclass."""

    @staticmethod
    def test_minimal_creation() -> None:
        """Verify UpdateInfo can be created with minimal required fields."""
        info = UpdateInfo(
            available=False,
            current_version=Version('1.0.0'),
        )
        assert info.available is False
        assert info.current_version == Version('1.0.0')
        assert info.latest_version is None
        assert info.error is None

    @staticmethod
    def test_full_creation() -> None:
        """Verify UpdateInfo can be created with all fields."""
        info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            download_url='https://example.com/update.exe',
            target_name='synodic-2.0.0-windows-x64.exe',
            file_size=1024000,
            error=None,
        )
        assert info.available is True
        assert info.latest_version == Version('2.0.0')
        assert info.download_url == 'https://example.com/update.exe'


class TestUpdateConfig:
    """Tests for UpdateConfig dataclass."""

    @staticmethod
    def test_default_values() -> None:
        """Verify default configuration values."""
        config = UpdateConfig()
        assert config.package_name == 'synodic_client'
        assert config.channel == UpdateChannel.STABLE
        assert config.tuf_repository_url == 'https://synodic.github.io/synodic-updates'

    @staticmethod
    def test_custom_values() -> None:
        """Verify custom configuration values are applied."""
        config = UpdateConfig(
            package_name='custom_package',
            channel=UpdateChannel.DEVELOPMENT,
            tuf_repository_url='https://custom.example.com/tuf',
        )
        assert config.package_name == 'custom_package'
        assert config.channel == UpdateChannel.DEVELOPMENT
        assert config.tuf_repository_url == 'https://custom.example.com/tuf'

    @staticmethod
    def test_include_prereleases_stable() -> None:
        """Verify STABLE channel does not include prereleases."""
        config = UpdateConfig(channel=UpdateChannel.STABLE)
        assert config.include_prereleases is False

    @staticmethod
    def test_include_prereleases_development() -> None:
        """Verify DEVELOPMENT channel includes prereleases."""
        config = UpdateConfig(channel=UpdateChannel.DEVELOPMENT)
        assert config.include_prereleases is True

    @staticmethod
    def test_default_paths(tmp_path: Path) -> None:
        """Verify default paths are under user home directory."""
        config = UpdateConfig()
        assert '.synodic' in str(config.metadata_dir)
        assert '.synodic' in str(config.download_dir)
        assert '.synodic' in str(config.backup_dir)


@pytest.fixture
def mock_porringer_api() -> MagicMock:
    """Create a mock porringer API."""
    api = MagicMock()
    api.update = MagicMock()
    return api


@pytest.fixture
def updater(mock_porringer_api: MagicMock, tmp_path: Path) -> Updater:
    """Create an Updater instance with temporary directories."""
    config = UpdateConfig(
        metadata_dir=tmp_path / 'metadata',
        download_dir=tmp_path / 'downloads',
        backup_dir=tmp_path / 'backup',
    )
    return Updater(
        current_version=Version('1.0.0'),
        porringer_api=mock_porringer_api,
        config=config,
    )


class TestUpdater:
    """Tests for Updater class."""

    @staticmethod
    def test_initial_state(updater: Updater) -> None:
        """Verify updater starts in NO_UPDATE state."""
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_directories_created(updater: Updater) -> None:
        """Verify configuration directories are created on init."""
        assert updater._config.metadata_dir.exists()
        assert updater._config.download_dir.exists()
        assert updater._config.backup_dir.exists()

    @staticmethod
    def test_is_frozen_property(updater: Updater) -> None:
        """Verify is_frozen returns False in test environment."""
        # Tests run in non-frozen environment
        assert updater.is_frozen is False

    @staticmethod
    def test_executable_path_not_frozen(updater: Updater) -> None:
        """Verify executable_path returns a Path in non-frozen mode."""
        path = updater.executable_path
        assert isinstance(path, Path)

    @staticmethod
    def test_check_for_update_no_update(updater: Updater, mock_porringer_api: MagicMock) -> None:
        """Verify check_for_update handles no update available."""
        mock_result = MagicMock()
        mock_result.available = False
        mock_result.latest_version = None
        mock_porringer_api.update.check.return_value = mock_result

        info = updater.check_for_update()

        assert info.available is False
        assert info.current_version == Version('1.0.0')
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_check_for_update_available(updater: Updater, mock_porringer_api: MagicMock) -> None:
        """Verify check_for_update handles update available."""
        mock_result = MagicMock()
        mock_result.available = True
        mock_result.latest_version = '2.0.0'
        mock_result.download_url = 'https://example.com/update.exe'
        mock_porringer_api.update.check.return_value = mock_result

        info = updater.check_for_update()

        assert info.available is True
        assert info.latest_version == Version('2.0.0')
        assert updater.state == UpdateState.UPDATE_AVAILABLE

    @staticmethod
    def test_check_for_update_error(updater: Updater, mock_porringer_api: MagicMock) -> None:
        """Verify check_for_update handles errors gracefully."""
        mock_porringer_api.update.check.side_effect = Exception('Network error')

        info = updater.check_for_update()

        assert info.available is False
        assert info.error == 'Network error'
        assert updater.state == UpdateState.FAILED

    @staticmethod
    def test_download_update_not_frozen(updater: Updater) -> None:
        """Verify download_update raises NotImplementedError when not frozen."""
        with pytest.raises(NotImplementedError, match='pip/pipx'):
            updater.download_update()

    @staticmethod
    def test_apply_update_not_frozen(updater: Updater) -> None:
        """Verify apply_update raises NotImplementedError when not frozen."""
        with pytest.raises(NotImplementedError, match='pip/pipx'):
            updater.apply_update()

    @staticmethod
    def test_rollback_no_backup(updater: Updater) -> None:
        """Verify rollback fails when no backup exists."""
        result = updater.rollback()
        assert result is False

    @staticmethod
    def test_cleanup_backup_no_backup(updater: Updater) -> None:
        """Verify cleanup_backup handles missing backup gracefully."""
        # Should not raise
        updater.cleanup_backup()

    @staticmethod
    def test_cleanup_backup_with_backup(updater: Updater) -> None:
        """Verify cleanup_backup removes existing backup."""
        backup_path = updater._get_backup_path()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text('backup content')

        updater.cleanup_backup()

        assert not backup_path.exists()

    @staticmethod
    def test_get_target_name_windows(updater: Updater, mock_porringer_api: MagicMock) -> None:
        """Verify target name generation for Windows."""
        # Set up update info
        mock_result = MagicMock()
        mock_result.available = True
        mock_result.latest_version = '2.0.0'
        mock_result.download_url = 'https://example.com/update.exe'
        mock_porringer_api.update.check.return_value = mock_result
        updater.check_for_update()

        with patch('synodic_client.updater.sys.platform', 'win32'):
            target_name = updater._get_target_name()
            assert target_name == 'synodic-2.0.0-windows-x64.exe'

    @staticmethod
    def test_get_target_name_linux(updater: Updater, mock_porringer_api: MagicMock) -> None:
        """Verify target name generation for Linux."""
        mock_result = MagicMock()
        mock_result.available = True
        mock_result.latest_version = '2.0.0'
        mock_result.download_url = 'https://example.com/update'
        mock_porringer_api.update.check.return_value = mock_result
        updater.check_for_update()

        with patch('synodic_client.updater.sys.platform', 'linux'):
            target_name = updater._get_target_name()
            assert target_name == 'synodic-2.0.0-linux-x64'

    @staticmethod
    def test_get_target_name_macos(updater: Updater, mock_porringer_api: MagicMock) -> None:
        """Verify target name generation for macOS."""
        mock_result = MagicMock()
        mock_result.available = True
        mock_result.latest_version = '2.0.0'
        mock_result.download_url = 'https://example.com/update'
        mock_porringer_api.update.check.return_value = mock_result
        updater.check_for_update()

        with patch('synodic_client.updater.sys.platform', 'darwin'):
            target_name = updater._get_target_name()
            assert target_name == 'synodic-2.0.0-macos-x64'


class TestUpdaterIntegration:
    """Integration tests for the full update workflow."""

    @staticmethod
    def test_full_update_check_workflow(mock_porringer_api: MagicMock, tmp_path: Path) -> None:
        """Test the complete update check workflow."""
        config = UpdateConfig(
            metadata_dir=tmp_path / 'metadata',
            download_dir=tmp_path / 'downloads',
            backup_dir=tmp_path / 'backup',
            channel=UpdateChannel.DEVELOPMENT,
        )

        updater = Updater(
            current_version=Version('1.0.0'),
            porringer_api=mock_porringer_api,
            config=config,
        )

        # Simulate update available
        mock_result = MagicMock()
        mock_result.available = True
        mock_result.latest_version = '1.1.0.dev1'
        mock_result.download_url = 'https://example.com/update.exe'
        mock_porringer_api.update.check.return_value = mock_result

        # Check for update
        info = updater.check_for_update()

        # Verify the workflow
        assert info.available is True
        assert info.latest_version == Version('1.1.0.dev1')
        assert updater.state == UpdateState.UPDATE_AVAILABLE

        # Verify porringer was called with correct parameters
        call_args = mock_porringer_api.update.check.call_args
        params = call_args[0][0]
        assert params.include_prereleases is True  # DEVELOPMENT channel
