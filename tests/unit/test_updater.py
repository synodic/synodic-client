"""Tests for the self-update functionality using Velopack."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import velopack
from packaging.version import Version

import synodic_client.updater as updater_mod
from synodic_client.schema import GITHUB_REPO_URL, UpdateChannel, UpdateConfig, UpdateInfo, UpdateState, platform_suffix
from synodic_client.updater import (
    Updater,
    github_release_asset_url,
    initialize_velopack,
    pep440_to_semver,
)


def _setup_downloaded_state(updater: Updater) -> MagicMock:
    """Put *updater* into DOWNLOADED state and return the mock velopack UpdateInfo."""
    mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
    updater._update_info = UpdateInfo(
        available=True,
        current_version=Version('1.0.0'),
        latest_version=Version('2.0.0'),
        _velopack_info=mock_velopack_info,
    )
    updater._state = UpdateState.DOWNLOADED
    return mock_velopack_info


def _setup_update_available_state(updater: Updater) -> MagicMock:
    """Put *updater* into UPDATE_AVAILABLE state and return the mock velopack UpdateInfo."""
    mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
    updater._update_info = UpdateInfo(
        available=True,
        current_version=Version('1.0.0'),
        latest_version=Version('2.0.0'),
        _velopack_info=mock_velopack_info,
    )
    updater._state = UpdateState.UPDATE_AVAILABLE
    return mock_velopack_info


class TestUpdateConfig:
    """Tests for UpdateConfig dataclass."""

    @staticmethod
    def test_channel_name_stable() -> None:
        """Verify STABLE channel returns platform-specific 'stable' name."""
        config = UpdateConfig(channel=UpdateChannel.STABLE)
        assert config.channel_name == f'stable-{platform_suffix()}'

    @staticmethod
    def test_channel_name_development() -> None:
        """Verify DEVELOPMENT channel returns platform-specific 'dev' name."""
        config = UpdateConfig(channel=UpdateChannel.DEVELOPMENT)
        assert config.channel_name == f'dev-{platform_suffix()}'


class TestGithubReleaseAssetUrl:
    """Tests for github_release_asset_url helper."""

    @staticmethod
    def test_dev_channel() -> None:
        """Verify dev channel produces /releases/download/dev URL."""
        url = github_release_asset_url(GITHUB_REPO_URL, UpdateChannel.DEVELOPMENT)
        assert url == f'{GITHUB_REPO_URL}/releases/download/dev'

    @staticmethod
    def test_stable_channel() -> None:
        """Verify stable channel produces /releases/latest/download URL."""
        url = github_release_asset_url(GITHUB_REPO_URL, UpdateChannel.STABLE)
        assert url == f'{GITHUB_REPO_URL}/releases/latest/download'

    @staticmethod
    def test_non_github_url_unchanged() -> None:
        """Verify non-GitHub URLs pass through unchanged."""
        custom = 'https://custom.example.com/updates'
        assert github_release_asset_url(custom, UpdateChannel.DEVELOPMENT) == custom
        assert github_release_asset_url(custom, UpdateChannel.STABLE) == custom

    @staticmethod
    def test_local_path_unchanged() -> None:
        """Verify local file paths pass through unchanged."""
        path = '/srv/releases'
        assert github_release_asset_url(path, UpdateChannel.DEVELOPMENT) == path

    @staticmethod
    def test_trailing_slash_stripped() -> None:
        """Verify trailing slashes are stripped before appending path."""
        url = github_release_asset_url('https://github.com/owner/repo/', UpdateChannel.DEVELOPMENT)
        assert url == 'https://github.com/owner/repo/releases/download/dev'


@pytest.fixture
def updater() -> Updater:
    """Create an Updater instance for testing."""
    u = Updater(current_version=Version('1.0.0'))
    # Reset state cached by the eager _get_velopack_manager() call
    # so each test can independently mock the Velopack SDK.
    u._velopack_manager = None
    u._velopack_not_installed = False
    return u


@pytest.fixture
def updater_with_config() -> Updater:
    """Create an Updater instance with custom config."""
    config = UpdateConfig(
        repo_url='https://github.com/test/repo',
        channel=UpdateChannel.DEVELOPMENT,
    )
    u = Updater(current_version=Version('1.0.0'), config=config)
    u._velopack_manager = None
    u._velopack_not_installed = False
    return u


class TestUpdater:
    """Tests for Updater class."""

    @staticmethod
    def test_initial_state(updater: Updater) -> None:
        """Verify updater starts in NO_UPDATE state."""
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_current_version_returns_init_value(updater: Updater) -> None:
        """Verify current_version starts as the value passed to __init__."""
        assert updater.current_version == Version('1.0.0')

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
        with patch.object(updater, '_get_velopack_manager', return_value=None):
            assert updater.is_installed is False

    @staticmethod
    def test_is_installed_with_velopack(updater: Updater) -> None:
        """Verify is_installed returns True when Velopack manager available."""
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            assert updater.is_installed is True

    @staticmethod
    def test_is_installed_handles_runtime_error(updater: Updater) -> None:
        """Verify is_installed returns False when RuntimeError is raised."""
        with patch.object(updater, '_get_velopack_manager', side_effect=RuntimeError('fail')):
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
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = None

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is False
        assert info.current_version == Version('1.0.0')
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_check_update_available(updater: Updater) -> None:
        """Verify check_for_update handles update available."""
        mock_target = MagicMock(spec=velopack.VelopackAsset)
        mock_target.Version = '2.0.0'
        mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
        mock_velopack_info.TargetFullRelease = mock_target

        mock_manager = MagicMock(spec=velopack.UpdateManager)
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
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.side_effect = Exception('Network error')

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is False
        assert info.error == 'Network error'
        assert updater.state == UpdateState.FAILED

    @staticmethod
    def test_check_404_returns_friendly_message(updater: Updater) -> None:
        """Verify a 404 from GitHub falls back to manifest check gracefully."""
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.side_effect = RuntimeError('Network error: Http error: http status: 404')

        with (
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
            patch.object(updater, '_check_manifest_fallback', return_value=None),
        ):
            info = updater.check_for_update()

        assert info.available is False
        # Fallback returned None, so no error — just no update.
        assert updater.state == UpdateState.NO_UPDATE

    @staticmethod
    def test_check_non_404_http_error_is_failed(updater: Updater) -> None:
        """Verify non-404 HTTP errors still produce FAILED state."""
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.side_effect = RuntimeError('Network error: Http error: http status: 500')

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is False
        assert updater.state == UpdateState.FAILED

    @staticmethod
    def test_check_preserves_downloaded_state(updater: Updater) -> None:
        """Re-checking after download must not regress DOWNLOADED → UPDATE_AVAILABLE.

        Regression test: when the periodic auto-check timer fires between
        download completion and the user clicking "Restart Now", the state
        was incorrectly reset to UPDATE_AVAILABLE, causing apply_update_on_exit
        to reject the update with "No downloaded update to apply".
        """
        mock_target = MagicMock(spec=velopack.VelopackAsset)
        mock_target.Version = '2.0.0'
        mock_velopack_info = _setup_downloaded_state(updater)
        mock_velopack_info.TargetFullRelease = mock_target

        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = mock_velopack_info

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is True
        assert updater.state == UpdateState.DOWNLOADED


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
        mock_velopack_info = _setup_update_available_state(updater)

        mock_manager = MagicMock(spec=velopack.UpdateManager)

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
        mock_velopack_info = _setup_update_available_state(updater)

        mock_manager = MagicMock(spec=velopack.UpdateManager)
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
        _setup_update_available_state(updater)

        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.download_updates.side_effect = Exception('Download failed')

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            result = updater.download_update()

        assert result is False
        assert updater.state == UpdateState.FAILED
        assert updater._update_info is not None
        assert updater._update_info.error == 'Download failed'


class TestUpdaterApplyUpdate:
    """Tests for apply_update methods."""

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
    @pytest.mark.parametrize(
        ('restart', 'silent'),
        [
            (True, False),
            (False, False),
            (True, True),
            (False, True),
        ],
        ids=['restart', 'no-restart', 'silent-restart', 'silent-no-restart'],
    )
    def test_apply_on_exit_matrix(updater: Updater, *, restart: bool, silent: bool) -> None:
        """Verify apply_update_on_exit stages the update with the correct restart/silent flags."""
        mock_velopack_info = _setup_downloaded_state(updater)
        mock_manager = MagicMock(spec=velopack.UpdateManager)

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            updater.apply_update_on_exit(restart=restart, silent=silent)

        assert updater.state == UpdateState.APPLYING
        mock_manager.wait_exit_then_apply_updates.assert_called_once_with(
            mock_velopack_info,
            silent=silent,
            restart=restart,
            restart_args=[],
        )

    @staticmethod
    def test_apply_on_exit_with_restart_args(updater: Updater) -> None:
        """Verify restart_args are forwarded to wait_exit_then_apply_updates."""
        mock_velopack_info = _setup_downloaded_state(updater)
        mock_manager = MagicMock(spec=velopack.UpdateManager)

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            updater.apply_update_on_exit(restart=True, restart_args=['--minimized'])

        assert updater.state == UpdateState.APPLYING
        mock_manager.wait_exit_then_apply_updates.assert_called_once_with(
            mock_velopack_info,
            silent=False,
            restart=True,
            restart_args=['--minimized'],
        )

    @staticmethod
    def test_apply_on_exit_silent_with_restart_args(updater: Updater) -> None:
        """Verify silent mode forwards restart_args."""
        mock_velopack_info = _setup_downloaded_state(updater)
        mock_manager = MagicMock(spec=velopack.UpdateManager)

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            updater.apply_update_on_exit(restart=True, silent=True, restart_args=['--minimized'])

        assert updater.state == UpdateState.APPLYING
        mock_manager.wait_exit_then_apply_updates.assert_called_once_with(
            mock_velopack_info,
            silent=True,
            restart=True,
            restart_args=['--minimized'],
        )


class TestInitializeVelopack:
    """Tests for initialize_velopack function."""

    @staticmethod
    @pytest.fixture(autouse=True)
    def _reset_velopack_guard() -> None:
        """Reset the idempotency guard before each test."""
        updater_mod._VelopackState.initialized = False

    @staticmethod
    def test_initialize_success() -> None:
        """Verify initialize_velopack calls App().run()."""
        mock_app = MagicMock(spec=velopack.App)
        with patch('synodic_client.updater.velopack.App', return_value=mock_app) as mock_app_class:
            initialize_velopack()
            mock_app_class.assert_called_once()
            mock_app.run.assert_called_once()

    @staticmethod
    def test_initialize_handles_exception() -> None:
        """Verify initialize_velopack handles exceptions gracefully."""
        mock_app = MagicMock(spec=velopack.App)
        mock_app.run.side_effect = Exception('Test')
        with patch('synodic_client.updater.velopack.App', return_value=mock_app):
            # Should not raise
            initialize_velopack()

    @staticmethod
    def test_idempotent_on_second_call() -> None:
        """A second call is a no-op; Velopack is initialised only once."""
        mock_app = MagicMock(spec=velopack.App)
        with patch('synodic_client.updater.velopack.App', return_value=mock_app) as mock_app_class:
            initialize_velopack()
            initialize_velopack()
            mock_app_class.assert_called_once()


class TestGetVelopackManager:
    """Tests for _get_velopack_manager install detection via the SDK."""

    _PATCH_OPTIONS = patch('synodic_client.updater.velopack.UpdateOptions')

    @staticmethod
    def test_not_installed_returns_none(updater: Updater) -> None:
        """Verify manager returns None when SDK says 'not properly installed'."""
        error = RuntimeError('This application is not properly installed: Could not auto-locate app manifest')
        with (
            TestGetVelopackManager._PATCH_OPTIONS,
            patch('synodic_client.updater.velopack.UpdateManager', side_effect=error),
        ):
            assert updater._get_velopack_manager() is None

    @staticmethod
    def test_not_installed_sentinel_cached(updater: Updater) -> None:
        """Verify that once detected as not-installed, the SDK is not called again."""
        error = RuntimeError('This application is not properly installed')
        with (
            TestGetVelopackManager._PATCH_OPTIONS,
            patch('synodic_client.updater.velopack.UpdateManager', side_effect=error) as mock_cls,
        ):
            updater._get_velopack_manager()
            updater._get_velopack_manager()
            mock_cls.assert_called_once()

    @staticmethod
    def test_real_error_propagates(updater: Updater) -> None:
        """Verify non-install RuntimeErrors propagate instead of returning None."""
        error = RuntimeError('Some other SDK failure')
        with (
            TestGetVelopackManager._PATCH_OPTIONS,
            patch('synodic_client.updater.velopack.UpdateManager', side_effect=error),
            pytest.raises(RuntimeError, match='Some other SDK failure'),
        ):
            updater._get_velopack_manager()

    @staticmethod
    def test_non_runtime_error_propagates(updater: Updater) -> None:
        """Verify non-RuntimeError exceptions are wrapped and propagated."""
        error = ValueError('bad config')
        with (
            TestGetVelopackManager._PATCH_OPTIONS,
            patch('synodic_client.updater.velopack.UpdateManager', side_effect=error),
            pytest.raises(RuntimeError, match='Failed to create Velopack UpdateManager'),
        ):
            updater._get_velopack_manager()

    @staticmethod
    def test_success_caches_manager(updater: Updater) -> None:
        """Verify successful manager creation is cached."""
        mock_manager = MagicMock()
        mock_manager.get_current_version.return_value = '9.8.7'
        with (
            TestGetVelopackManager._PATCH_OPTIONS,
            patch('synodic_client.updater.velopack.UpdateManager', return_value=mock_manager) as mock_cls,
        ):
            result1 = updater._get_velopack_manager()
            result2 = updater._get_velopack_manager()
            assert result1 is mock_manager
            assert result2 is mock_manager
            mock_cls.assert_called_once()

    @staticmethod
    def test_success_promotes_version(updater: Updater) -> None:
        """Verify _current_version is overwritten with the Velopack version."""
        mock_manager = MagicMock()
        mock_manager.get_current_version.return_value = '9.8.7'
        with (
            TestGetVelopackManager._PATCH_OPTIONS,
            patch('synodic_client.updater.velopack.UpdateManager', return_value=mock_manager),
        ):
            updater._get_velopack_manager()

        assert updater._current_version == Version('9.8.7')
        assert updater.current_version == Version('9.8.7')


class TestPep440ToSemver:
    """Tests for pep440_to_semver conversion."""

    @staticmethod
    def test_dev_version_two_part_base() -> None:
        """PDM SCM 2-part base normalises to 3-part SemVer."""
        assert pep440_to_semver('0.1.dev47+g799543c') == '0.1.0-dev.47'

    @staticmethod
    def test_dev_version_three_part_base() -> None:
        """Three-part dev version converts correctly."""
        assert pep440_to_semver('0.1.1.dev3') == '0.1.1-dev.3'

    @staticmethod
    def test_stable_version() -> None:
        """Stable version passes through unchanged."""
        assert pep440_to_semver('1.0.0') == '1.0.0'

    @staticmethod
    def test_stable_version_two_part() -> None:
        """Two-part stable normalises to three-part."""
        assert pep440_to_semver('1.0') == '1.0.0'

    @staticmethod
    def test_dev_zero() -> None:
        """Dev release number zero is preserved."""
        assert pep440_to_semver('0.1.0.dev0') == '0.1.0-dev.0'

    @staticmethod
    def test_local_segment_stripped() -> None:
        """Local segment (+gXXXXXXX) is stripped."""
        assert pep440_to_semver('1.2.3.dev10+gabcdef1') == '1.2.3-dev.10'

    @staticmethod
    def test_semver_input_passthrough() -> None:
        """SemVer-style pre-release input is normalised via PEP 440."""
        # packaging.version.Version normalises '0.1.0-dev.5' to '0.1.0.dev5'
        assert pep440_to_semver('0.1.0-dev.5') == '0.1.0-dev.5'
