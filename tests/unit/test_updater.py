"""Tests for the self-update functionality using Velopack."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from packaging.version import Version

from synodic_client.updater import (
    GITHUB_REPO_URL,
    UpdateChannel,
    UpdateConfig,
    UpdateInfo,
    Updater,
    UpdateState,
    initialize_velopack,
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
        assert info._velopack_info is None

    @staticmethod
    def test_full_creation() -> None:
        """Verify UpdateInfo can be created with all fields."""
        mock_velopack_info = MagicMock()
        info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            error=None,
            _velopack_info=mock_velopack_info,
        )
        assert info.available is True
        assert info.latest_version == Version('2.0.0')
        assert info._velopack_info is mock_velopack_info

    @staticmethod
    def test_with_error() -> None:
        """Verify UpdateInfo can be created with error."""
        info = UpdateInfo(
            available=False,
            current_version=Version('1.0.0'),
            error='Network error',
        )
        assert info.available is False
        assert info.error == 'Network error'


class TestUpdateConfig:
    """Tests for UpdateConfig dataclass."""

    @staticmethod
    def test_default_values() -> None:
        """Verify default configuration values."""
        config = UpdateConfig()
        assert config.repo_url == GITHUB_REPO_URL
        assert config.channel == UpdateChannel.STABLE

    @staticmethod
    def test_custom_values() -> None:
        """Verify custom configuration values are applied."""
        config = UpdateConfig(
            repo_url='https://github.com/custom/repo',
            channel=UpdateChannel.DEVELOPMENT,
        )
        assert config.repo_url == 'https://github.com/custom/repo'
        assert config.channel == UpdateChannel.DEVELOPMENT

    @staticmethod
    def test_channel_name_stable() -> None:
        """Verify STABLE channel returns 'stable' name."""
        config = UpdateConfig(channel=UpdateChannel.STABLE)
        assert config.channel_name == 'stable'

    @staticmethod
    def test_channel_name_development() -> None:
        """Verify DEVELOPMENT channel returns 'dev' name."""
        config = UpdateConfig(channel=UpdateChannel.DEVELOPMENT)
        assert config.channel_name == 'dev'


@pytest.fixture
def updater() -> Updater:
    """Create an Updater instance for testing."""
    return Updater(current_version=Version('1.0.0'))


@pytest.fixture
def updater_with_config() -> Updater:
    """Create an Updater instance with custom config."""
    config = UpdateConfig(
        repo_url='https://github.com/test/repo',
        channel=UpdateChannel.DEVELOPMENT,
    )
    return Updater(current_version=Version('1.0.0'), config=config)


class TestUpdater:
    """Tests for Updater class."""

    @staticmethod
    def test_initial_state(updater: Updater) -> None:
        """Verify updater starts in NO_UPDATE state."""
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_initial_update_info_is_none(updater: Updater) -> None:
        """Verify initial update info is None."""
        assert updater._update_info is None

    @staticmethod
    def test_default_config(updater: Updater) -> None:
        """Verify default config is used when not provided."""
        assert updater._config.repo_url == GITHUB_REPO_URL
        assert updater._config.channel == UpdateChannel.STABLE

    @staticmethod
    def test_custom_config(updater_with_config: Updater) -> None:
        """Verify custom config is applied."""
        assert updater_with_config._config.repo_url == 'https://github.com/test/repo'
        assert updater_with_config._config.channel == UpdateChannel.DEVELOPMENT

    @staticmethod
    def test_is_installed_not_velopack(updater: Updater) -> None:
        """Verify is_installed returns False in test environment."""
        # Tests run in non-Velopack environment
        with patch.object(updater, '_get_velopack_manager', return_value=None):
            assert updater.is_installed is False

    @staticmethod
    def test_is_installed_with_velopack(updater: Updater) -> None:
        """Verify is_installed returns True when Velopack manager available."""
        mock_manager = MagicMock()
        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            assert updater.is_installed is True

    @staticmethod
    def test_is_installed_handles_exception(updater: Updater) -> None:
        """Verify is_installed returns False when exception occurs."""
        with patch.object(updater, '_get_velopack_manager', side_effect=Exception('Test')):
            assert updater.is_installed is False


class TestUpdaterCheckForUpdate:
    """Tests for check_for_update method."""

    @staticmethod
    def test_check_not_installed(updater: Updater) -> None:
        """Verify check_for_update handles non-Velopack environment."""
        with patch.object(updater, '_get_velopack_manager', return_value=None):
            info = updater.check_for_update()

        assert info.available is False
        assert info.error == 'Not installed via Velopack'
        assert info.current_version == Version('1.0.0')

    @staticmethod
    def test_check_no_update(updater: Updater) -> None:
        """Verify check_for_update handles no update available."""
        mock_manager = MagicMock()
        mock_manager.check_for_updates.return_value = None

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is False
        assert info.current_version == Version('1.0.0')
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_check_update_available(updater: Updater) -> None:
        """Verify check_for_update handles update available."""
        mock_velopack_info = MagicMock()
        mock_velopack_info.target_full_release.version = '2.0.0'

        mock_manager = MagicMock()
        mock_manager.check_for_updates.return_value = mock_velopack_info

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is True
        assert info.latest_version == Version('2.0.0')
        assert info._velopack_info is mock_velopack_info
        assert updater.state == UpdateState.UPDATE_AVAILABLE

    @staticmethod
    def test_check_error(updater: Updater) -> None:
        """Verify check_for_update handles errors gracefully."""
        mock_manager = MagicMock()
        mock_manager.check_for_updates.side_effect = Exception('Network error')

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is False
        assert info.error == 'Network error'
        assert updater.state == UpdateState.FAILED


class TestUpdaterDownloadUpdate:
    """Tests for download_update method."""

    @staticmethod
    def test_download_not_installed(updater: Updater) -> None:
        """Verify download_update raises NotImplementedError when not installed."""
        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=False),
            pytest.raises(NotImplementedError, match='Velopack installs'),
        ):
            updater.download_update()

    @staticmethod
    def test_download_no_update_available(updater: Updater) -> None:
        """Verify download_update returns False when no update available."""
        with patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True):
            result = updater.download_update()

        assert result is False

    @staticmethod
    def test_download_success(updater: Updater) -> None:
        """Verify download_update succeeds with valid update info."""
        mock_velopack_info = MagicMock()
        updater._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )
        updater._state = UpdateState.UPDATE_AVAILABLE

        mock_manager = MagicMock()

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            result = updater.download_update()

        assert result is True
        assert updater.state == UpdateState.DOWNLOADED
        mock_manager.download_updates.assert_called_once_with(mock_velopack_info, None)

    @staticmethod
    def test_download_with_progress_callback(updater: Updater) -> None:
        """Verify download_update passes progress callback."""
        mock_velopack_info = MagicMock()
        updater._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )
        updater._state = UpdateState.UPDATE_AVAILABLE

        mock_manager = MagicMock()
        progress_cb = MagicMock()

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            result = updater.download_update(progress_callback=progress_cb)

        assert result is True
        mock_manager.download_updates.assert_called_once_with(mock_velopack_info, progress_cb)

    @staticmethod
    def test_download_error(updater: Updater) -> None:
        """Verify download_update handles errors gracefully."""
        mock_velopack_info = MagicMock()
        updater._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )
        updater._state = UpdateState.UPDATE_AVAILABLE

        mock_manager = MagicMock()
        mock_manager.download_updates.side_effect = Exception('Download failed')

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            result = updater.download_update()

        assert result is False
        assert updater.state == UpdateState.FAILED
        assert updater._update_info.error == 'Download failed'


class TestUpdaterApplyUpdate:
    """Tests for apply_update methods."""

    @staticmethod
    def test_apply_and_restart_not_installed(updater: Updater) -> None:
        """Verify apply_update_and_restart raises when not installed."""
        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=False),
            pytest.raises(NotImplementedError, match='Velopack installs'),
        ):
            updater.apply_update_and_restart()

    @staticmethod
    def test_apply_and_restart_no_downloaded_update(updater: Updater) -> None:
        """Verify apply_update_and_restart raises when no downloaded update."""
        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            pytest.raises(RuntimeError, match='No downloaded update'),
        ):
            updater.apply_update_and_restart()

    @staticmethod
    def test_apply_on_exit_not_installed(updater: Updater) -> None:
        """Verify apply_update_on_exit raises when not installed."""
        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=False),
            pytest.raises(NotImplementedError, match='Velopack installs'),
        ):
            updater.apply_update_on_exit()

    @staticmethod
    def test_apply_on_exit_no_downloaded_update(updater: Updater) -> None:
        """Verify apply_update_on_exit raises when no downloaded update."""
        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            pytest.raises(RuntimeError, match='No downloaded update'),
        ):
            updater.apply_update_on_exit()

    @staticmethod
    def test_apply_on_exit_success(updater: Updater) -> None:
        """Verify apply_update_on_exit schedules update."""
        mock_velopack_info = MagicMock()
        updater._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )
        updater._state = UpdateState.DOWNLOADED

        mock_manager = MagicMock()

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            updater.apply_update_on_exit(restart=True)

        assert updater.state == UpdateState.APPLIED
        mock_manager.apply_updates_and_exit.assert_called_once_with(mock_velopack_info)

    @staticmethod
    def test_apply_on_exit_no_restart(updater: Updater) -> None:
        """Verify apply_update_on_exit can disable restart (note: not supported by Velopack)."""
        mock_velopack_info = MagicMock()
        updater._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )
        updater._state = UpdateState.DOWNLOADED

        mock_manager = MagicMock()

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            updater.apply_update_on_exit(restart=False)

        # Note: Velopack's apply_updates_and_exit doesn't support restart parameter
        mock_manager.apply_updates_and_exit.assert_called_once_with(mock_velopack_info)


class TestInitializeVelopack:
    """Tests for initialize_velopack function."""

    @staticmethod
    def test_initialize_success() -> None:
        """Verify initialize_velopack calls velopack.App().run()."""
        mock_app = MagicMock()
        with patch('synodic_client.updater.velopack.App', return_value=mock_app) as mock_app_class:
            initialize_velopack()
            mock_app_class.assert_called_once()
            mock_app.run.assert_called_once()

    @staticmethod
    def test_initialize_handles_exception() -> None:
        """Verify initialize_velopack handles exceptions gracefully."""
        mock_app = MagicMock()
        mock_app.run.side_effect = Exception('Test')
        with patch('synodic_client.updater.velopack.App', return_value=mock_app):
            # Should not raise
            initialize_velopack()
