"""Tests for the self-update functionality using Velopack."""

import json
import urllib.error
from pathlib import Path
from typing import Any
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
    on_before_uninstall,
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
    @pytest.mark.parametrize(
        'guarded_state',
        [UpdateState.DOWNLOADING, UpdateState.DOWNLOADED, UpdateState.APPLYING, UpdateState.APPLIED],
        ids=lambda s: s.name.lower(),
    )
    def test_check_preserves_advanced_state(updater: Updater, guarded_state: UpdateState) -> None:
        """Re-checking must not regress any advanced state back to UPDATE_AVAILABLE.

        Regression test: when the periodic auto-check timer fires during or
        after a download, the state must remain at the higher-priority state.
        """
        mock_target = MagicMock(spec=velopack.VelopackAsset)
        mock_target.Version = '2.0.0'
        mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
        mock_velopack_info.TargetFullRelease = mock_target

        updater._state = guarded_state
        updater._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )

        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = mock_velopack_info

        with patch.object(updater, '_get_velopack_manager', return_value=mock_manager):
            info = updater.check_for_update()

        assert info.available is True
        assert updater.state == guarded_state


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
        ('restart', 'silent', 'restart_args'),
        [
            (True, False, []),
            (False, False, []),
            (True, True, []),
            (False, True, []),
            (True, False, ['--minimized']),
            (True, True, ['--minimized']),
        ],
        ids=[
            'restart',
            'no-restart',
            'silent-restart',
            'silent-no-restart',
            'restart-with-args',
            'silent-restart-with-args',
        ],
    )
    def test_apply_on_exit_matrix(
        updater: Updater,
        *,
        restart: bool,
        silent: bool,
        restart_args: list[str],
    ) -> None:
        """Verify apply_update_on_exit stages the update with the correct flags."""
        mock_velopack_info = _setup_downloaded_state(updater)
        mock_manager = MagicMock(spec=velopack.UpdateManager)

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(updater, '_get_velopack_manager', return_value=mock_manager),
        ):
            updater.apply_update_on_exit(restart=restart, silent=silent, restart_args=restart_args)

        assert updater.state == UpdateState.APPLYING
        mock_manager.wait_exit_then_apply_updates.assert_called_once_with(
            mock_velopack_info,
            silent=silent,
            restart=restart,
            restart_args=restart_args,
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


# ---------------------------------------------------------------------------
# Realistic dev-channel manifest payload (mirrors the real GitHub Release).
# The ``dev`` tag on GitHub is marked ``"prerelease": true``, which
# Velopack's GithubSource filters out (it hard-codes prerelease=false).
# ---------------------------------------------------------------------------

_DEV_MANIFEST: dict[str, object] = {
    'Assets': [
        {
            'PackageId': 'synodic',
            'Version': '0.1.0-dev.83',
            'Type': 'Full',
            'FileName': 'synodic-0.1.0-dev.83-dev-win-full.nupkg',
            'SHA1': 'aabbccdd',
            'SHA256': '07badc6414dc5d87b009a7ecaa4ee446febe0d15275aa86465a9720762ceab80',
            'Size': 66358200,
        },
        {
            'PackageId': 'synodic',
            'Version': '0.1.0-dev.83',
            'Type': 'Delta',
            'FileName': 'synodic-0.1.0-dev.83-dev-win-delta.nupkg',
            'SHA1': '11223344',
            'SHA256': '5305031a791e0de45f517eda0d2cf827951ec603380ba740fe58fbac4b6246cd',
            'Size': 15560939,
        },
        {
            'PackageId': 'synodic',
            'Version': '0.1.0-dev.80',
            'Type': 'Full',
            'FileName': 'synodic-0.1.0-dev.80-dev-win-full.nupkg',
            'SHA1': 'deadbeef',
            'SHA256': '09bc2032a6a374e1d722cb3c42d1e586a9113c7fd6877721ad5e1ecb611dbbc3',
            'Size': 65808335,
        },
    ],
}


def _make_urlopen_response(data: dict[str, Any]) -> MagicMock:
    """Build a mock ``urlopen`` return value that reads as JSON."""
    body = json.dumps(data).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.headers = {'Content-Length': str(len(body))}
    return resp


@pytest.fixture
def dev_updater() -> Updater:
    """Create an Updater on the dev channel at version 0.1.0-dev.80."""
    config = UpdateConfig(
        repo_url=GITHUB_REPO_URL,
        channel=UpdateChannel.DEVELOPMENT,
    )
    u = Updater(current_version=Version('0.1.0.dev80'), config=config)
    u._velopack_manager = None
    u._velopack_not_installed = False
    return u


class TestDevChannelGithubPrerelease:
    """Regression: dev channel prerelease ignored by Velopack GithubSource.

    The dev channel uses a GitHub prerelease that Velopack's GithubSource
    silently ignores (``prerelease=false``).

    The check path already has ``_check_manifest_fallback``.  These tests
    verify that the *download* path also works when the update was discovered
    via the fallback.
    """

    @staticmethod
    def test_check_finds_update_via_manifest_fallback(dev_updater: Updater) -> None:
        """check_for_update discovers dev.83 via manifest fallback when SDK returns None."""
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        # SDK's GithubSource filters prereleases → returns None
        mock_manager.check_for_updates.return_value = None

        manifest_resp = _make_urlopen_response(_DEV_MANIFEST)

        with (
            patch.object(dev_updater, '_get_velopack_manager', return_value=mock_manager),
            patch('synodic_client.updater.urllib.request.urlopen', return_value=manifest_resp),
        ):
            info = dev_updater.check_for_update()

        assert info.available is True
        assert info.latest_version == Version('0.1.0.dev83')
        assert dev_updater.state == UpdateState.UPDATE_AVAILABLE

    @staticmethod
    def test_check_sets_manifest_fallback_flag(dev_updater: Updater) -> None:
        """check_for_update sets _used_manifest_fallback when fallback discovered the update."""
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = None

        manifest_resp = _make_urlopen_response(_DEV_MANIFEST)

        with (
            patch.object(dev_updater, '_get_velopack_manager', return_value=mock_manager),
            patch('synodic_client.updater.urllib.request.urlopen', return_value=manifest_resp),
        ):
            info = dev_updater.check_for_update()

        assert info._used_manifest_fallback is True

    @staticmethod
    def test_check_sdk_success_does_not_set_fallback_flag(dev_updater: Updater) -> None:
        """_used_manifest_fallback stays False when the SDK itself found the update."""
        mock_target = MagicMock(spec=velopack.VelopackAsset)
        mock_target.Version = '0.1.0-dev.83'
        mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
        mock_velopack_info.TargetFullRelease = mock_target

        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = mock_velopack_info

        with patch.object(dev_updater, '_get_velopack_manager', return_value=mock_manager):
            info = dev_updater.check_for_update()

        assert info.available is True
        assert info._used_manifest_fallback is False

    @staticmethod
    def test_download_succeeds_after_manifest_fallback(dev_updater: Updater) -> None:
        """download_update routes to _download_direct when the manifest fallback was used."""
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = None

        manifest_resp = _make_urlopen_response(_DEV_MANIFEST)

        with (
            patch.object(dev_updater, '_get_velopack_manager', return_value=mock_manager),
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch('synodic_client.updater.urllib.request.urlopen', return_value=manifest_resp),
        ):
            info = dev_updater.check_for_update()
            assert info.available is True
            assert info._used_manifest_fallback is True

        # Now mock the direct download — _download_direct is called instead of
        # manager.download_updates, so the SDK never touches GithubSource.
        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(dev_updater, '_download_direct') as mock_direct,
        ):
            result = dev_updater.download_update()

        assert result is True
        assert dev_updater.state == UpdateState.DOWNLOADED
        mock_direct.assert_called_once_with(info._velopack_info, None)
        # The SDK's download_updates should NOT have been called
        mock_manager.download_updates.assert_not_called()

    @staticmethod
    def test_sdk_download_used_when_sdk_found_update(dev_updater: Updater) -> None:
        """download_update uses the SDK when the update was found without the fallback."""
        mock_target = MagicMock(spec=velopack.VelopackAsset)
        mock_target.Version = '0.1.0-dev.83'
        mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
        mock_velopack_info.TargetFullRelease = mock_target

        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = mock_velopack_info

        with (
            patch.object(dev_updater, '_get_velopack_manager', return_value=mock_manager),
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
        ):
            info = dev_updater.check_for_update()
            assert info._used_manifest_fallback is False

            result = dev_updater.download_update()

        assert result is True
        assert dev_updater.state == UpdateState.DOWNLOADED
        mock_manager.download_updates.assert_called_once_with(mock_velopack_info, None)

    @staticmethod
    def test_download_direct_constructs_correct_url(dev_updater: Updater, tmp_path: Path) -> None:
        """_download_direct fetches from the correct GitHub release asset URL."""
        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'synodic-0.1.0-dev.83-dev-win-full.nupkg'
        mock_velopack_info.TargetFullRelease.SHA256 = ''
        mock_velopack_info.TargetFullRelease.SHA1 = ''
        mock_velopack_info.TargetFullRelease.Size = 0

        nupkg_content = b'fake-nupkg-content'
        resp = MagicMock()
        resp.read.side_effect = [nupkg_content, b'']
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.headers = {'Content-Length': str(len(nupkg_content))}

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp) as mock_urlopen,
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()

            dev_updater._download_direct(mock_velopack_info)

        # Verify the URL
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        expected_url = f'{GITHUB_REPO_URL}/releases/download/dev/synodic-0.1.0-dev.83-dev-win-full.nupkg'
        assert req.full_url == expected_url

        # Verify the file was written
        target_file = tmp_path / 'packages' / 'synodic-0.1.0-dev.83-dev-win-full.nupkg'
        assert target_file.exists()
        assert target_file.read_bytes() == nupkg_content

    @staticmethod
    def test_download_direct_sha256_mismatch(dev_updater: Updater, tmp_path: Path) -> None:
        """_download_direct raises on SHA256 mismatch and cleans up the partial."""
        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'test.nupkg'
        mock_velopack_info.TargetFullRelease.SHA256 = 'wrong_hash'
        mock_velopack_info.TargetFullRelease.SHA1 = ''
        mock_velopack_info.TargetFullRelease.Size = 0

        resp = MagicMock()
        resp.read.side_effect = [b'some content', b'']
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.headers = {'Content-Length': '12'}

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp),
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()

            with pytest.raises(RuntimeError, match='SHA256 mismatch'):
                dev_updater._download_direct(mock_velopack_info)

        # Partial file should be cleaned up
        assert not (tmp_path / 'packages' / 'test.nupkg.partial').exists()
        assert not (tmp_path / 'packages' / 'test.nupkg').exists()

    @staticmethod
    def test_download_direct_skips_existing(dev_updater: Updater, tmp_path: Path) -> None:
        """_download_direct skips download if the package already exists on disk."""
        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'already-there.nupkg'

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen') as mock_urlopen,
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()
            packages = tmp_path / 'packages'
            packages.mkdir()
            (packages / 'already-there.nupkg').write_bytes(b'existing')

            dev_updater._download_direct(mock_velopack_info)

        # Must not have opened any network connection
        mock_urlopen.assert_not_called()

    @staticmethod
    def test_download_direct_uses_replace_not_rename(dev_updater: Updater, tmp_path: Path) -> None:
        """_download_direct must use Path.replace() — not rename() — for atomicity.

        Regression: ``Path.rename()`` raises ``FileExistsError`` on Windows
        (WinError 183) when a concurrent download has already placed the
        target file.  ``Path.replace()`` overwrites atomically.
        """
        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'race.nupkg'
        mock_velopack_info.TargetFullRelease.SHA256 = ''
        mock_velopack_info.TargetFullRelease.SHA1 = ''
        mock_velopack_info.TargetFullRelease.Size = 0

        nupkg_content = b'new-package-data'
        resp = MagicMock()
        resp.read.side_effect = [nupkg_content, b'']
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.headers = {'Content-Length': str(len(nupkg_content))}

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp),
            patch.object(Path, 'replace') as mock_replace,
            patch.object(Path, 'rename') as mock_rename,
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()
            dev_updater._download_direct(mock_velopack_info)

        # replace() must be used for atomic overwrite
        mock_replace.assert_called_once()
        # rename() must NOT be used (it fails on Windows when target exists)
        mock_rename.assert_not_called()

    @staticmethod
    def test_check_does_not_regress_downloading_state(dev_updater: Updater) -> None:
        """check_for_update must not regress DOWNLOADING → UPDATE_AVAILABLE.

        Regression: a periodic re-check during an active download was
        resetting state to UPDATE_AVAILABLE, which allowed a second
        concurrent download_update() call.
        """
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.check_for_updates.return_value = None
        manifest_resp = _make_urlopen_response(_DEV_MANIFEST)

        # First: put the updater into DOWNLOADING state
        dev_updater._state = UpdateState.DOWNLOADING

        with (
            patch.object(dev_updater, '_get_velopack_manager', return_value=mock_manager),
            patch('synodic_client.updater.urllib.request.urlopen', return_value=manifest_resp),
        ):
            info = dev_updater.check_for_update()

        # The check should still report the update, but must NOT
        # regress the state from DOWNLOADING to UPDATE_AVAILABLE.
        assert info.available is True
        assert dev_updater.state == UpdateState.DOWNLOADING


class TestDownloadDirectSHA1:
    """Verify _download_direct SHA1 verification paths."""

    @staticmethod
    def test_sha1_only_success(dev_updater: Updater, tmp_path: Path) -> None:
        """When SHA256 is empty but SHA1 is provided, SHA1 is verified."""
        content = b'sha1-verified-content'
        expected_sha1 = 'c1e63f162617f1685471d477b99de2532580ea97'

        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'sha1-only.nupkg'
        mock_velopack_info.TargetFullRelease.SHA256 = ''
        mock_velopack_info.TargetFullRelease.SHA1 = expected_sha1
        mock_velopack_info.TargetFullRelease.Size = len(content)

        resp = MagicMock()
        resp.read.side_effect = [content, b'']
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.headers = {'Content-Length': str(len(content))}

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp),
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()
            dev_updater._download_direct(mock_velopack_info)

        target = tmp_path / 'packages' / 'sha1-only.nupkg'
        assert target.exists()
        assert target.read_bytes() == content

    @staticmethod
    def test_sha1_mismatch(dev_updater: Updater, tmp_path: Path) -> None:
        """SHA1 mismatch raises RuntimeError and cleans up the partial file."""
        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'sha1-bad.nupkg'
        mock_velopack_info.TargetFullRelease.SHA256 = ''
        mock_velopack_info.TargetFullRelease.SHA1 = 'wrong_sha1_hash'
        mock_velopack_info.TargetFullRelease.Size = 0

        resp = MagicMock()
        resp.read.side_effect = [b'some content', b'']
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.headers = {'Content-Length': '12'}

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp),
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()

            with pytest.raises(RuntimeError, match='SHA1 mismatch'):
                dev_updater._download_direct(mock_velopack_info)

        assert not (tmp_path / 'packages' / 'sha1-bad.nupkg.partial').exists()
        assert not (tmp_path / 'packages' / 'sha1-bad.nupkg').exists()

    @staticmethod
    def test_no_checksums_skips_verification(dev_updater: Updater, tmp_path: Path) -> None:
        """When both SHA256 and SHA1 are empty, download succeeds without verification."""
        content = b'no-checksum-content'

        mock_velopack_info = MagicMock()
        mock_velopack_info.TargetFullRelease.FileName = 'no-hash.nupkg'
        mock_velopack_info.TargetFullRelease.SHA256 = ''
        mock_velopack_info.TargetFullRelease.SHA1 = ''
        mock_velopack_info.TargetFullRelease.Size = 0

        resp = MagicMock()
        resp.read.side_effect = [content, b'']
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        resp.headers = {'Content-Length': str(len(content))}

        with (
            patch('synodic_client.updater.sys') as mock_sys,
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp),
        ):
            mock_sys.executable = str(tmp_path / 'current' / 'synodic.exe')
            (tmp_path / 'current').mkdir()
            dev_updater._download_direct(mock_velopack_info)

        assert (tmp_path / 'packages' / 'no-hash.nupkg').exists()


class TestCheckManifestFallbackEdgeCases:
    """Direct unit tests for _check_manifest_fallback edge cases."""

    @staticmethod
    def test_empty_assets_returns_none(dev_updater: Updater) -> None:
        """A manifest with no Assets returns None."""
        manifest = {'Assets': []}
        resp = _make_urlopen_response(manifest)

        with (
            patch.object(dev_updater, '_get_velopack_manager', return_value=None),
            patch('synodic_client.updater.urllib.request.urlopen', return_value=resp),
        ):
            result = dev_updater._check_manifest_fallback()

        assert result is None

    @staticmethod
    def test_no_full_assets_returns_none(dev_updater: Updater) -> None:
        """A manifest with only Delta assets returns None."""
        manifest = {
            'Assets': [
                {
                    'PackageId': 'synodic',
                    'Version': '0.1.0-dev.83',
                    'Type': 'Delta',
                    'FileName': 'delta.nupkg',
                },
            ],
        }
        resp = _make_urlopen_response(manifest)

        with patch('synodic_client.updater.urllib.request.urlopen', return_value=resp):
            result = dev_updater._check_manifest_fallback()

        assert result is None

    @staticmethod
    def test_older_version_returns_none(dev_updater: Updater) -> None:
        """A manifest with only older versions returns None."""
        manifest = {
            'Assets': [
                {
                    'PackageId': 'synodic',
                    'Version': '0.1.0-dev.79',
                    'Type': 'Full',
                    'FileName': 'old.nupkg',
                },
            ],
        }
        resp = _make_urlopen_response(manifest)

        with patch('synodic_client.updater.urllib.request.urlopen', return_value=resp):
            result = dev_updater._check_manifest_fallback()

        assert result is None

    @staticmethod
    def test_network_error_returns_none(dev_updater: Updater) -> None:
        """A network error during manifest fetch returns None."""
        with patch(
            'synodic_client.updater.urllib.request.urlopen',
            side_effect=urllib.error.URLError('connection refused'),
        ):
            result = dev_updater._check_manifest_fallback()

        assert result is None

    @staticmethod
    def test_invalid_version_skipped(dev_updater: Updater) -> None:
        """An asset with an unparseable version is skipped without crashing."""
        manifest = {
            'Assets': [
                {
                    'PackageId': 'synodic',
                    'Version': 'not-a-version',
                    'Type': 'Full',
                    'FileName': 'bad.nupkg',
                },
                {
                    'PackageId': 'synodic',
                    'Version': '0.1.0-dev.83',
                    'Type': 'Full',
                    'FileName': 'good.nupkg',
                    'SHA256': 'abc',
                },
            ],
        }
        resp = _make_urlopen_response(manifest)

        with patch('synodic_client.updater.urllib.request.urlopen', return_value=resp):
            result = dev_updater._check_manifest_fallback()

        assert result is not None
        assert result.TargetFullRelease.Version == '0.1.0-dev.83'

    @staticmethod
    def test_picks_highest_version(dev_updater: Updater) -> None:
        """When multiple Full assets are newer, the highest version wins."""
        manifest = {
            'Assets': [
                {
                    'PackageId': 'synodic',
                    'Version': '0.1.0-dev.81',
                    'Type': 'Full',
                    'FileName': 'v81.nupkg',
                },
                {
                    'PackageId': 'synodic',
                    'Version': '0.1.0-dev.85',
                    'Type': 'Full',
                    'FileName': 'v85.nupkg',
                },
                {
                    'PackageId': 'synodic',
                    'Version': '0.1.0-dev.83',
                    'Type': 'Full',
                    'FileName': 'v83.nupkg',
                },
            ],
        }
        resp = _make_urlopen_response(manifest)

        with patch('synodic_client.updater.urllib.request.urlopen', return_value=resp):
            result = dev_updater._check_manifest_fallback()

        assert result is not None
        assert result.TargetFullRelease.Version == '0.1.0-dev.85'
        assert result.TargetFullRelease.FileName == 'v85.nupkg'

    @staticmethod
    def test_collects_matching_deltas(dev_updater: Updater) -> None:
        """Delta assets matching the best version are included in DeltasToTarget."""
        resp = _make_urlopen_response(_DEV_MANIFEST)

        with patch('synodic_client.updater.urllib.request.urlopen', return_value=resp):
            result = dev_updater._check_manifest_fallback()

        assert result is not None
        assert len(result.DeltasToTarget) == 1
        assert result.DeltasToTarget[0].Type == 'Delta'
        assert result.DeltasToTarget[0].Version == '0.1.0-dev.83'


class TestDownloadUpdateGuards:
    """Test edge-case guards in download_update()."""

    @staticmethod
    def test_velopack_info_none_returns_false() -> None:
        """download_update returns False when _velopack_info is None."""
        config = UpdateConfig(repo_url=GITHUB_REPO_URL, channel=UpdateChannel.STABLE)
        u = Updater(current_version=Version('1.0.0'), config=config)
        u._state = UpdateState.UPDATE_AVAILABLE
        u._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=None,
        )

        with patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True):
            result = u.download_update()

        assert result is False
        # State should NOT advance to DOWNLOADING
        assert u.state == UpdateState.UPDATE_AVAILABLE

    @staticmethod
    def test_download_transitions_through_downloading_state() -> None:
        """download_update sets DOWNLOADING state during the download."""
        config = UpdateConfig(repo_url=GITHUB_REPO_URL, channel=UpdateChannel.STABLE)
        u = Updater(current_version=Version('1.0.0'), config=config)
        mock_velopack_info = MagicMock(spec=velopack.UpdateInfo)
        u._state = UpdateState.UPDATE_AVAILABLE
        u._update_info = UpdateInfo(
            available=True,
            current_version=Version('1.0.0'),
            latest_version=Version('2.0.0'),
            _velopack_info=mock_velopack_info,
        )

        observed_states: list[UpdateState] = []
        mock_manager = MagicMock(spec=velopack.UpdateManager)
        mock_manager.download_updates.side_effect = lambda info, cb: observed_states.append(u.state)

        with (
            patch.object(Updater, 'is_installed', new_callable=PropertyMock, return_value=True),
            patch.object(u, '_get_velopack_manager', return_value=mock_manager),
        ):
            u.download_update()

        assert UpdateState.DOWNLOADING in observed_states


class TestOnBeforeUninstall:
    """Tests for the Velopack uninstall hook."""

    @staticmethod
    def test_removes_protocol_and_startup() -> None:
        """Both remove_protocol and remove_startup are called."""
        with (
            patch('synodic_client.updater.remove_protocol') as mock_proto,
            patch('synodic_client.updater.remove_startup') as mock_startup,
        ):
            on_before_uninstall('0.1.0')

        mock_proto.assert_called_once()
        mock_startup.assert_called_once()

    @staticmethod
    def test_protocol_failure_does_not_block_startup_removal() -> None:
        """If remove_protocol raises, remove_startup is still called."""
        with (
            patch('synodic_client.updater.remove_protocol', side_effect=OSError('failed')),
            patch('synodic_client.updater.remove_startup') as mock_startup,
        ):
            on_before_uninstall('0.1.0')

        mock_startup.assert_called_once()

    @staticmethod
    def test_startup_failure_does_not_raise() -> None:
        """If remove_startup raises, the hook does not propagate and protocol is still removed."""
        with (
            patch('synodic_client.updater.remove_protocol') as mock_proto,
            patch('synodic_client.updater.remove_startup', side_effect=OSError('failed')),
        ):
            on_before_uninstall('0.1.0')  # should not raise

        mock_proto.assert_called_once()
