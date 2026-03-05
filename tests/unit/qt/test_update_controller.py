"""Tests for the UpdateController self-update orchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from packaging.version import Version

from synodic_client.application.screen.update_banner import UpdateBanner
from synodic_client.application.update_controller import UpdateController
from synodic_client.resolution import ResolvedConfig
from synodic_client.schema import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    UpdateInfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> ResolvedConfig:
    """Create a ``ResolvedConfig`` with sensible defaults and optional overrides."""
    defaults: dict[str, Any] = {
        'update_source': None,
        'update_channel': 'stable',
        'auto_update_interval_minutes': DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
        'tool_update_interval_minutes': DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
        'plugin_auto_update': None,
        'detect_updates': True,
        'prerelease_packages': None,
        'auto_apply': True,
        'auto_start': True,
        'debug_logging': False,
        'last_client_update': None,
        'last_tool_updates': None,
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


def _make_controller(
    *,
    auto_apply: bool = True,
    auto_update_interval_minutes: int = 0,
    is_user_active: bool = False,
) -> tuple[UpdateController, MagicMock, MagicMock, UpdateBanner, UpdateBanner, MagicMock]:
    """Build an ``UpdateController`` with mocked collaborators.

    Returns (controller, app_mock, client_mock, banner1, banner2, settings_mock).
    """
    config = _make_config(
        auto_apply=auto_apply,
        auto_update_interval_minutes=auto_update_interval_minutes,
    )

    app = MagicMock()
    client = MagicMock()
    client.updater = MagicMock()
    banner1 = UpdateBanner()
    banner2 = UpdateBanner()
    settings = MagicMock()
    # settings mock only needs: check_updates_requested, set_checking,
    # reset_check_updates_button, set_last_updated

    with patch('synodic_client.application.update_controller.resolve_update_config') as mock_ucfg:
        mock_ucfg.return_value = MagicMock(
            auto_update_interval_minutes=auto_update_interval_minutes,
        )
        controller = UpdateController(
            app,
            client,
            [banner1, banner2],
            settings_window=settings,
            config=config,
        )
        controller.set_user_active_predicate(lambda: is_user_active)

    return controller, app, client, banner1, banner2, settings


# ---------------------------------------------------------------------------
# Check result routing
# ---------------------------------------------------------------------------


class TestCheckFinished:
    """Verify _on_check_finished routes results correctly."""

    @staticmethod
    def test_none_result_shows_error_banner_when_not_silent() -> None:
        """A None result with silent=False should show error on all banners."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()
        ctrl._on_check_finished(None, silent=False)

        settings.reset_check_updates_button.assert_called_once()
        assert b1.state.name == 'ERROR'
        assert b2.state.name == 'ERROR'

    @staticmethod
    def test_none_result_no_banner_when_silent() -> None:
        """A None result with silent=True should NOT show the error banner."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()
        ctrl._on_check_finished(None, silent=True)

        assert b1.state.name == 'HIDDEN'
        assert b2.state.name == 'HIDDEN'

    @staticmethod
    def test_error_result_shows_error_banner() -> None:
        """An error result should show error on all banners."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()
        result = UpdateInfo(available=False, current_version=Version('1.0.0'), error='No releases found')
        ctrl._on_check_finished(result, silent=False)

        assert b1.state.name == 'ERROR'
        assert b2.state.name == 'ERROR'

    @staticmethod
    def test_no_update_available_banners_remain_hidden() -> None:
        """No update available should leave banners hidden."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()
        result = UpdateInfo(available=False, current_version=Version('1.0.0'))
        ctrl._on_check_finished(result, silent=False)

        assert b1.state.name == 'HIDDEN'
        assert b2.state.name == 'HIDDEN'

    @staticmethod
    def test_update_available_shows_downloading_and_starts_download() -> None:
        """Available update should show downloading on all banners and start download."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()
        result = UpdateInfo(available=True, current_version=Version('1.0.0'), latest_version=Version('2.0.0'))

        with patch.object(ctrl, '_start_download') as mock_dl:
            ctrl._on_check_finished(result, silent=False)

        assert b1.state.name == 'DOWNLOADING'
        assert b2.state.name == 'DOWNLOADING'
        mock_dl.assert_called_once_with('2.0.0')


# ---------------------------------------------------------------------------
# Download completion — auto-apply vs manual
# ---------------------------------------------------------------------------


class TestDownloadFinished:
    """Verify _on_download_finished behaviour with auto-apply on/off."""

    @staticmethod
    def test_auto_apply_calls_apply_update() -> None:
        """When auto_apply=True, a successful download should call _apply_update(silent=True)."""
        ctrl, app, client, b1, b2, settings = _make_controller(auto_apply=True)

        with patch.object(ctrl, '_apply_update') as mock_apply:
            ctrl._on_download_finished(True, '2.0.0')

        mock_apply.assert_called_once_with(silent=True)

    @staticmethod
    def test_auto_apply_does_not_show_ready_banner() -> None:
        """When auto_apply=True, the ready banner should NOT be shown."""
        ctrl, app, client, b1, b2, settings = _make_controller(auto_apply=True)

        with patch.object(ctrl, '_apply_update'):
            ctrl._on_download_finished(True, '2.0.0')

        assert b1.state.name != 'READY'
        assert b2.state.name != 'READY'

    @staticmethod
    def test_no_auto_apply_shows_ready_banners() -> None:
        """When auto_apply=False, a successful download should show ready on all banners."""
        ctrl, app, client, b1, b2, settings = _make_controller(auto_apply=False)
        ctrl._on_download_finished(True, '2.0.0')

        assert b1.state.name == 'READY'
        assert b2.state.name == 'READY'

    @staticmethod
    def test_user_active_shows_ready_banners() -> None:
        """When user is active, the ready banners should be shown."""
        ctrl, app, client, b1, b2, settings = _make_controller(
            auto_apply=True,
            is_user_active=True,
        )

        with patch.object(ctrl, '_apply_update'):
            ctrl._on_download_finished(True, '2.0.0')

        assert b1.state.name == 'READY'
        assert b2.state.name == 'READY'

    @staticmethod
    def test_download_failure_shows_error() -> None:
        """A failed download should show an error on all banners."""
        ctrl, app, client, b1, b2, settings = _make_controller()
        ctrl._on_download_finished(False, '2.0.0')

        assert b1.state.name == 'ERROR'
        assert b2.state.name == 'ERROR'

    @staticmethod
    def test_download_sets_pending_version() -> None:
        """A successful download should set _pending_version."""
        ctrl, app, client, b1, b2, settings = _make_controller(auto_apply=False)
        ctrl._on_download_finished(True, '2.0.0')

        assert ctrl._pending_version == '2.0.0'


# ---------------------------------------------------------------------------
# Pending version — skip redundant downloads
# ---------------------------------------------------------------------------


class TestPendingVersion:
    """Verify behaviour when an update is already downloaded and pending."""

    @staticmethod
    def test_check_skips_download_when_version_already_pending() -> None:
        """Re-checking the same version should restore ready state, not re-download."""
        ctrl, _app, _client, b1, b2, settings = _make_controller(auto_apply=False)
        ctrl._pending_version = '2.0.0'

        result = UpdateInfo(available=True, current_version=Version('1.0.0'), latest_version=Version('2.0.0'))

        with patch.object(ctrl, '_start_download') as mock_dl:
            ctrl._on_check_finished(result, silent=True)

        mock_dl.assert_not_called()
        assert b1.state.name == 'READY'
        assert b2.state.name == 'READY'

    @staticmethod
    def test_check_downloads_when_newer_version() -> None:
        """A different version should trigger a fresh download."""
        ctrl, _app, _client, b1, b2, settings = _make_controller(auto_apply=False)
        ctrl._pending_version = '1.5.0'

        result = UpdateInfo(available=True, current_version=Version('1.0.0'), latest_version=Version('2.0.0'))

        with patch.object(ctrl, '_start_download') as mock_dl:
            ctrl._on_check_finished(result, silent=True)

        mock_dl.assert_called_once_with('2.0.0')

    @staticmethod
    def test_do_check_preserves_banner_when_pending() -> None:
        """set_checking should NOT be called when an update is already pending."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()
        ctrl._pending_version = '2.0.0'

        with patch('asyncio.create_task'):
            ctrl._do_check(silent=True)

        settings.set_checking.assert_not_called()

    @staticmethod
    def test_do_check_shows_checking_when_no_pending() -> None:
        """set_checking should be called when there is no pending update."""
        ctrl, _app, _client, b1, b2, settings = _make_controller()

        with patch('asyncio.create_task'):
            ctrl._do_check(silent=True)

        settings.set_checking.assert_called_once()

    @staticmethod
    def test_apply_clears_pending_version() -> None:
        """_apply_update should clear _pending_version."""
        ctrl, app, client, b1, b2, settings = _make_controller()
        ctrl._pending_version = '2.0.0'
        ctrl._apply_update()

        assert ctrl._pending_version is None


# ---------------------------------------------------------------------------
# User-active gating
# ---------------------------------------------------------------------------


class TestUserActiveGating:
    """Verify that auto-apply is deferred when the user is active.

    Automatic checks always run so the settings window stays current.
    Only the silent apply-and-restart is gated by ``_is_user_active``.
    """

    @staticmethod
    def test_auto_check_always_runs() -> None:
        """_on_auto_check should call _do_check even when user is active."""
        ctrl, _app, _client, b1, b2, settings = _make_controller(is_user_active=True)

        with patch.object(ctrl, '_do_check') as mock_check:
            ctrl._on_auto_check()

        mock_check.assert_called_once_with(silent=True)

    @staticmethod
    def test_manual_check_unaffected_by_active_user() -> None:
        """_on_manual_check should always call _do_check regardless of user activity."""
        ctrl, _app, _client, b1, b2, settings = _make_controller(is_user_active=True)

        with patch.object(ctrl, '_do_check') as mock_check:
            ctrl._on_manual_check()

        mock_check.assert_called_once_with(silent=False)

    @staticmethod
    def test_auto_apply_deferred_when_user_active() -> None:
        """When auto_apply=True but user is active, show READY banners instead of applying."""
        ctrl, app, client, b1, b2, settings = _make_controller(
            auto_apply=True,
            is_user_active=True,
        )

        with patch.object(ctrl, '_apply_update') as mock_apply:
            ctrl._on_download_finished(True, '2.0.0')

        mock_apply.assert_not_called()
        assert b1.state.name == 'READY'
        assert b2.state.name == 'READY'

    @staticmethod
    def test_auto_apply_proceeds_when_user_inactive() -> None:
        """When auto_apply=True and user is inactive, _apply_update is called."""
        ctrl, app, client, b1, b2, settings = _make_controller(
            auto_apply=True,
            is_user_active=False,
        )

        with patch.object(ctrl, '_apply_update') as mock_apply:
            ctrl._on_download_finished(True, '2.0.0')

        mock_apply.assert_called_once_with(silent=True)

    @staticmethod
    def test_can_auto_apply_false_when_user_active() -> None:
        """_can_auto_apply should return False when auto_apply=True but user is active."""
        ctrl, *_ = _make_controller(auto_apply=True, is_user_active=True)
        assert ctrl._can_auto_apply() is False

    @staticmethod
    def test_can_auto_apply_false_when_disabled() -> None:
        """_can_auto_apply should return False when auto_apply=False."""
        ctrl, *_ = _make_controller(auto_apply=False, is_user_active=False)
        assert ctrl._can_auto_apply() is False

    @staticmethod
    def test_can_auto_apply_true_when_enabled_and_inactive() -> None:
        """_can_auto_apply should return True only when auto_apply=True and user is inactive."""
        ctrl, *_ = _make_controller(auto_apply=True, is_user_active=False)
        assert ctrl._can_auto_apply() is True


# ---------------------------------------------------------------------------
# Apply update
# ---------------------------------------------------------------------------


class TestApplyUpdate:
    """Verify _apply_update delegates to client and quits."""

    @staticmethod
    def test_apply_update_calls_client_and_quits() -> None:
        """_apply_update should call client.apply_update_on_exit and app.quit."""
        ctrl, app, client, b1, b2, settings = _make_controller()
        ctrl._apply_update()

        client.apply_update_on_exit.assert_called_once_with(restart=True, silent=False)
        app.quit.assert_called_once()

    @staticmethod
    def test_apply_update_noop_without_updater() -> None:
        """_apply_update should be a no-op when client.updater is None."""
        ctrl, app, client, b1, b2, settings = _make_controller()
        client.updater = None
        ctrl._apply_update()

        client.apply_update_on_exit.assert_not_called()
        app.quit.assert_not_called()


# ---------------------------------------------------------------------------
# Settings changed → immediate check
# ---------------------------------------------------------------------------


class TestSettingsChanged:
    """Verify on_settings_changed triggers reinit and immediate check."""

    @staticmethod
    def test_settings_changed_triggers_reinit_and_check() -> None:
        """Changing settings should reinitialise the updater and check."""
        ctrl, app, client, b1, b2, settings = _make_controller()

        new_config = _make_config(update_channel='dev')

        with (
            patch.object(ctrl, '_reinitialize_updater') as mock_reinit,
            patch.object(ctrl, 'check_now') as mock_check,
        ):
            ctrl.on_settings_changed(new_config)

        mock_reinit.assert_called_once_with(new_config)
        mock_check.assert_called_once_with(silent=True)

    @staticmethod
    def test_settings_changed_updates_auto_apply() -> None:
        """Changing settings should update the auto_apply flag."""
        ctrl, app, client, b1, b2, settings = _make_controller(auto_apply=True)

        new_config = _make_config(auto_apply=False)

        with (
            patch.object(ctrl, '_reinitialize_updater'),
            patch.object(ctrl, 'check_now'),
        ):
            ctrl.on_settings_changed(new_config)

        assert ctrl._auto_apply is False


# ---------------------------------------------------------------------------
# Check error
# ---------------------------------------------------------------------------


class TestCheckError:
    """Verify _on_check_error routes errors correctly."""

    @staticmethod
    def test_check_error_shows_banner_when_not_silent() -> None:
        """An exception during check should show banner when not silent."""
        ctrl, app, client, b1, b2, settings = _make_controller()
        ctrl._on_check_error('timeout', silent=False)

        assert b1.state.name == 'ERROR'
        assert b2.state.name == 'ERROR'

    @staticmethod
    def test_check_error_no_banner_when_silent() -> None:
        """An exception during check should NOT show banner when silent."""
        ctrl, app, client, b1, b2, settings = _make_controller()
        ctrl._on_check_error('timeout', silent=True)

        assert b1.state.name == 'HIDDEN'
        assert b2.state.name == 'HIDDEN'
