"""Tests for the UpdateController self-update orchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from packaging.version import Version

from synodic_client.application.config_store import ConfigStore
from synodic_client.application.screen.update_banner import UpdateBanner
from synodic_client.application.theme import (
    UPDATE_STATUS_AVAILABLE_STYLE,
    UPDATE_STATUS_ERROR_STYLE,
    UPDATE_STATUS_UP_TO_DATE_STYLE,
)
from synodic_client.application.update_controller import UpdateController
from synodic_client.application.update_model import UpdateModel
from synodic_client.resolution import ResolvedConfig
from synodic_client.schema import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    UpdateInfo,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ModelSpy:
    """Records signal emissions from an :class:`UpdateModel`."""

    def __init__(self, model: UpdateModel) -> None:
        """Connect to *model* signals and record emissions."""
        self.status: list[tuple[str, str]] = []
        self.check_button_enabled: list[bool] = []
        self.restart_visible: list[bool] = []
        self.last_checked: list[str] = []

        model.status_text_changed.connect(lambda t, s: self.status.append((t, s)))
        model.check_button_enabled_changed.connect(self.check_button_enabled.append)
        model.restart_visible_changed.connect(self.restart_visible.append)
        model.last_checked_changed.connect(self.last_checked.append)


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
) -> tuple[UpdateController, MagicMock, MagicMock, UpdateBanner, UpdateModel]:
    """Build an ``UpdateController`` with mocked collaborators.

    Returns (controller, app_mock, client_mock, banner, model).
    """
    config = _make_config(
        auto_apply=auto_apply,
        auto_update_interval_minutes=auto_update_interval_minutes,
    )

    app = MagicMock()
    client = MagicMock()
    client.updater = MagicMock()
    model = UpdateModel()
    banner = UpdateBanner()
    banner.connect_model(model)
    store = ConfigStore(config)

    with patch('synodic_client.application.update_controller.resolve_update_config') as mock_ucfg:
        mock_ucfg.return_value = MagicMock(
            auto_update_interval_minutes=auto_update_interval_minutes,
        )
        controller = UpdateController(
            app,
            client,
            model,
            store=store,
        )
        controller.set_user_active_predicate(lambda: is_user_active)

    return controller, app, client, banner, model


# ---------------------------------------------------------------------------
# Check result routing
# ---------------------------------------------------------------------------


class TestCheckFinished:
    """Verify _on_check_finished routes results correctly."""

    @staticmethod
    def test_none_result_sets_error_status() -> None:
        """A None result should set 'Check failed' in red."""
        ctrl, _app, _client, banner, model = _make_controller()
        spy = ModelSpy(model)
        ctrl._on_check_finished(None, silent=False)

        assert True in spy.check_button_enabled
        assert ('Check failed', UPDATE_STATUS_ERROR_STYLE) in spy.status

    @staticmethod
    def test_none_result_shows_banner_when_not_silent() -> None:
        """A None result with silent=False should show the error banner."""
        ctrl, _app, _client, banner, model = _make_controller()
        ctrl._on_check_finished(None, silent=False)

        assert banner.state.name == 'ERROR'

    @staticmethod
    def test_none_result_no_banner_when_silent() -> None:
        """A None result with silent=True should NOT show the error banner."""
        ctrl, _app, _client, banner, model = _make_controller()
        ctrl._on_check_finished(None, silent=True)

        assert banner.state.name == 'HIDDEN'

    @staticmethod
    def test_error_result_sets_error_status() -> None:
        """An error result should set 'Check failed' status."""
        ctrl, _app, _client, banner, model = _make_controller()
        spy = ModelSpy(model)
        result = UpdateInfo(available=False, current_version=Version('1.0.0'), error='No releases found')
        ctrl._on_check_finished(result, silent=False)

        assert ('Check failed', UPDATE_STATUS_ERROR_STYLE) in spy.status

    @staticmethod
    def test_no_update_sets_up_to_date() -> None:
        """No update available should set 'Up to date' in green."""
        ctrl, _app, _client, banner, model = _make_controller()
        spy = ModelSpy(model)
        result = UpdateInfo(available=False, current_version=Version('1.0.0'))
        ctrl._on_check_finished(result, silent=False)

        assert ('Up to date', UPDATE_STATUS_UP_TO_DATE_STYLE) in spy.status

    @staticmethod
    def test_update_available_sets_status_and_starts_download() -> None:
        """Available update should set orange status and start download."""
        ctrl, _app, _client, banner, model = _make_controller()
        spy = ModelSpy(model)
        result = UpdateInfo(available=True, current_version=Version('1.0.0'), latest_version=Version('2.0.0'))

        with patch.object(ctrl, '_start_download') as mock_dl:
            ctrl._on_check_finished(result, silent=False)

        assert ('v2.0.0 available', UPDATE_STATUS_AVAILABLE_STYLE) in spy.status
        mock_dl.assert_called_once_with('2.0.0', silent=False)


# ---------------------------------------------------------------------------
# Download completion — auto-apply vs manual
# ---------------------------------------------------------------------------


class TestDownloadFinished:
    """Verify _on_download_finished behaviour with auto-apply on/off."""

    @staticmethod
    def test_auto_apply_calls_apply_update() -> None:
        """When auto_apply=True, a successful download should call _apply_update(silent=True)."""
        ctrl, app, client, banner, model = _make_controller(auto_apply=True)

        with patch.object(ctrl, '_apply_update') as mock_apply:
            ctrl._on_download_finished(True, '2.0.0')

        mock_apply.assert_called_once_with(silent=True)

    @staticmethod
    def test_auto_apply_does_not_show_ready_banner() -> None:
        """When auto_apply=True, the ready banner should NOT be shown."""
        ctrl, app, client, banner, model = _make_controller(auto_apply=True)

        with patch.object(ctrl, '_apply_update'):
            ctrl._on_download_finished(True, '2.0.0')

        # Banner should not be in READY state
        assert banner.state.name != 'READY'

    @staticmethod
    def test_no_auto_apply_shows_ready_banner() -> None:
        """When auto_apply=False, a successful download should show the ready banner."""
        ctrl, app, client, banner, model = _make_controller(auto_apply=False)
        with patch.object(ctrl._store, 'update'):
            ctrl._on_download_finished(True, '2.0.0')

        assert banner.state.name == 'READY'

    @staticmethod
    def test_no_auto_apply_sets_ready_status() -> None:
        """When auto_apply=False, status should show 'v2.0.0 ready' in green."""
        ctrl, app, client, banner, model = _make_controller(auto_apply=False)
        spy = ModelSpy(model)
        with patch.object(ctrl._store, 'update'):
            ctrl._on_download_finished(True, '2.0.0')

        assert ('v2.0.0 ready', UPDATE_STATUS_UP_TO_DATE_STYLE) in spy.status

    @staticmethod
    def test_no_auto_apply_shows_restart_button() -> None:
        """When auto_apply=False, the restart button should be shown in settings."""
        ctrl, app, client, banner, model = _make_controller(auto_apply=False)
        spy = ModelSpy(model)
        with patch.object(ctrl._store, 'update'):
            ctrl._on_download_finished(True, '2.0.0')

        assert True in spy.restart_visible

    @staticmethod
    def test_user_active_shows_restart_button() -> None:
        """When user is active, the restart button should be shown in settings."""
        ctrl, app, client, banner, model = _make_controller(
            auto_apply=True,
            is_user_active=True,
        )

        spy = ModelSpy(model)
        with patch.object(ctrl, '_apply_update'):
            ctrl._on_download_finished(True, '2.0.0')

        assert True in spy.restart_visible

    @staticmethod
    def test_download_failure_shows_error() -> None:
        """A failed download should show an error banner."""
        ctrl, app, client, banner, model = _make_controller()
        spy = ModelSpy(model)
        ctrl._on_download_finished(False, '2.0.0')

        assert banner.state.name == 'ERROR'
        assert ('Download failed', UPDATE_STATUS_ERROR_STYLE) in spy.status


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
        ctrl, _app, _client, banner, model = _make_controller(is_user_active=True)

        with patch.object(ctrl, '_do_check') as mock_check:
            ctrl._on_auto_check()

        mock_check.assert_called_once_with(silent=True)

    @staticmethod
    def test_manual_check_unaffected_by_active_user() -> None:
        """request_check should always call _do_check regardless of user activity."""
        ctrl, _app, _client, banner, model = _make_controller(is_user_active=True)

        with patch.object(ctrl, '_do_check') as mock_check:
            ctrl.request_check()

        mock_check.assert_called_once_with(silent=False)

    @staticmethod
    def test_auto_apply_deferred_when_user_active() -> None:
        """When auto_apply=True but user is active, show READY banner instead of applying."""
        ctrl, app, client, banner, model = _make_controller(
            auto_apply=True,
            is_user_active=True,
        )

        with patch.object(ctrl, '_apply_update') as mock_apply:
            ctrl._on_download_finished(True, '2.0.0')

        mock_apply.assert_not_called()
        assert banner.state.name == 'READY'

    @staticmethod
    def test_auto_apply_proceeds_when_user_inactive() -> None:
        """When auto_apply=True and user is inactive, _apply_update is called."""
        ctrl, app, client, banner, model = _make_controller(
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
        ctrl, app, client, banner, model = _make_controller()
        ctrl._pending_version = '2.0.0'
        ctrl._apply_update()

        client.apply_update_on_exit.assert_called_once_with(restart=True, silent=False)
        app.quit.assert_called_once()

    @staticmethod
    def test_apply_update_noop_without_updater() -> None:
        """_apply_update should be a no-op when client.updater is None."""
        ctrl, app, client, banner, model = _make_controller()
        client.updater = None
        ctrl._apply_update()

        client.apply_update_on_exit.assert_not_called()
        app.quit.assert_not_called()

    @staticmethod
    def test_apply_update_refreshes_startup_registry_when_frozen() -> None:
        """_apply_update should call sync_startup before quitting."""
        ctrl, app, client, banner, model = _make_controller()
        ctrl._pending_version = '2.0.0'

        with (
            patch('synodic_client.application.update_controller.sync_startup') as mock_sync,
            patch('synodic_client.application.update_controller.sys') as mock_sys,
        ):
            mock_sys.executable = r'C:\app\synodic.exe'
            ctrl._apply_update()

        mock_sync.assert_called_once_with(r'C:\app\synodic.exe', auto_start=True)
        client.apply_update_on_exit.assert_called_once()
        app.quit.assert_called_once()


# ---------------------------------------------------------------------------
# Settings changed → immediate check
# ---------------------------------------------------------------------------


class TestConfigChanged:
    """Verify _on_config_changed triggers reinit and immediate check."""

    @staticmethod
    def test_config_changed_triggers_reinit_and_check() -> None:
        """Changing config should reinitialise the updater and check."""
        ctrl, app, client, banner, model = _make_controller()

        new_config = _make_config(update_channel='dev')

        with (
            patch.object(ctrl, '_reinitialize_updater') as mock_reinit,
            patch.object(ctrl, 'check_now') as mock_check,
        ):
            ctrl._on_config_changed(new_config)

        mock_reinit.assert_called_once_with(new_config)
        mock_check.assert_called_once_with(silent=True)

    @staticmethod
    def test_config_changed_updates_auto_apply() -> None:
        """Changing config should update the auto_apply flag."""
        ctrl, app, client, banner, model = _make_controller(auto_apply=True)

        new_config = _make_config(auto_apply=False)

        with (
            patch.object(ctrl, '_reinitialize_updater'),
            patch.object(ctrl, 'check_now'),
        ):
            ctrl._on_config_changed(new_config)

        assert ctrl._auto_apply is False


# ---------------------------------------------------------------------------
# Check error
# ---------------------------------------------------------------------------


class TestCheckError:
    """Verify _on_check_error routes errors correctly."""

    @staticmethod
    def test_check_error_sets_failed_status() -> None:
        """An exception during check should set 'Check failed' status."""
        ctrl, app, client, banner, model = _make_controller()
        spy = ModelSpy(model)
        ctrl._on_check_error('connection refused', silent=False)

        assert ('Check failed', UPDATE_STATUS_ERROR_STYLE) in spy.status

    @staticmethod
    def test_check_error_shows_banner_when_not_silent() -> None:
        """An exception during check should show banner when not silent."""
        ctrl, app, client, banner, model = _make_controller()
        ctrl._on_check_error('timeout', silent=False)

        assert banner.state.name == 'ERROR'

    @staticmethod
    def test_check_error_no_banner_when_silent() -> None:
        """An exception during check should NOT show banner when silent."""
        ctrl, app, client, banner, model = _make_controller()
        ctrl._on_check_error('timeout', silent=True)

        assert banner.state.name == 'HIDDEN'


# ---------------------------------------------------------------------------
# Timestamp sync — _persist_check_timestamp updates config
# ---------------------------------------------------------------------------


class TestPersistCheckTimestamp:
    """Verify _persist_check_timestamp syncs the settings config via the store."""

    @staticmethod
    def test_persist_updates_store() -> None:
        """_persist_check_timestamp should call store.update with a timestamp."""
        ctrl, _app, _client, _banner, model = _make_controller()
        spy = ModelSpy(model)

        fake_resolved = _make_config(last_client_update='2026-03-09T00:00:00+00:00')
        with patch.object(ctrl._store, 'update', return_value=fake_resolved) as mock_update:
            ctrl._persist_check_timestamp()
            mock_update.assert_called_once()

        assert len(spy.last_checked) == 1

    @staticmethod
    def test_on_check_finished_success_syncs_via_store() -> None:
        """A successful check should persist timestamp via the store."""
        ctrl, _app, _client, _banner, model = _make_controller()
        result = UpdateInfo(available=False, current_version=Version('1.0.0'))

        fake_resolved = _make_config(last_client_update='2026-03-09T00:00:00+00:00')
        with patch.object(ctrl._store, 'update', return_value=fake_resolved) as mock_update:
            ctrl._on_check_finished(result, silent=True)
            mock_update.assert_called_once()

    @staticmethod
    def test_download_finished_syncs_via_store() -> None:
        """_on_download_finished should sync via the store and update the label."""
        ctrl, _app, _client, _banner, model = _make_controller(auto_apply=False)
        spy = ModelSpy(model)

        fake_resolved = _make_config(last_client_update='2026-03-09T00:00:00+00:00')
        with patch.object(ctrl._store, 'update', return_value=fake_resolved) as mock_update:
            ctrl._on_download_finished(True, '2.0.0')
            mock_update.assert_called_once()

        assert len(spy.last_checked) == 1


# ---------------------------------------------------------------------------
# Reinitialise updater — stale state cleared
# ---------------------------------------------------------------------------


class TestReinitializeUpdater:
    """Verify _reinitialize_updater clears stale state."""

    @staticmethod
    def test_reinit_resets_state_and_cancels_task() -> None:
        """Reinitialising should clear pending/failed versions and cancel in-flight tasks."""
        ctrl, _app, _client, _banner, _model = _make_controller()
        ctrl._pending_version = '1.0.0'
        ctrl._failed_version = '1.0.0'
        fake_task = MagicMock()
        fake_task.done.return_value = False
        ctrl._update_task = fake_task

        new_config = _make_config(update_channel='dev')
        with patch('synodic_client.application.update_controller.resolve_update_config') as mock_ucfg:
            mock_ucfg.return_value = MagicMock(
                auto_update_interval_minutes=0,
                channel=MagicMock(name='DEVELOPMENT'),
                repo_url='https://example.com',
            )
            ctrl._reinitialize_updater(new_config)

        assert ctrl._pending_version is None  # pyrefly: ignore
        assert ctrl._failed_version is None  # pyrefly: ignore
        fake_task.cancel.assert_called_once()

    @staticmethod
    def test_reinit_then_check_redownloads_same_version() -> None:
        """After reinit, a check for the same version should download instead of showing ready."""
        ctrl, _app, _client, _banner, _model = _make_controller(auto_apply=False)
        ctrl._pending_version = '2.0.0'

        new_config = _make_config(update_channel='dev')
        with patch('synodic_client.application.update_controller.resolve_update_config') as mock_ucfg:
            mock_ucfg.return_value = MagicMock(
                auto_update_interval_minutes=0,
                channel=MagicMock(name='DEVELOPMENT'),
                repo_url='https://example.com',
            )
            ctrl._reinitialize_updater(new_config)

        result = UpdateInfo(available=True, current_version=Version('1.0.0'), latest_version=Version('2.0.0'))
        with patch.object(ctrl, '_start_download') as mock_dl:
            ctrl._on_check_finished(result, silent=True)

        mock_dl.assert_called_once_with('2.0.0', silent=True)


# ---------------------------------------------------------------------------
# Apply without pending download — guard
# ---------------------------------------------------------------------------


class TestApplyGuard:
    """Verify _apply_update rejects apply when no download is pending."""

    @staticmethod
    def test_apply_without_pending_shows_error() -> None:
        """Applying with no pending version should show an error, not crash."""
        ctrl, app, client, banner, model = _make_controller()
        ctrl._pending_version = None

        ctrl._apply_update(silent=False)

        assert banner.state.name == 'ERROR'
        client.apply_update_on_exit.assert_not_called()
        app.quit.assert_not_called()

    @staticmethod
    def test_apply_without_pending_silent_logs_only() -> None:
        """Applying silently with no pending version should not show the banner."""
        ctrl, app, client, banner, model = _make_controller()
        ctrl._pending_version = None

        ctrl._apply_update(silent=True)

        assert banner.state.name == 'HIDDEN'
        client.apply_update_on_exit.assert_not_called()
        app.quit.assert_not_called()
