"""Tests for the UpdateBanner widget."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.update_banner import UpdateBanner, UpdateBannerState

_app = QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestUpdateBannerConstruction:
    """Basic construction and default state."""

    def test_starts_hidden(self) -> None:
        banner = UpdateBanner()
        assert banner.state == UpdateBannerState.HIDDEN
        assert banner.maximumHeight() == 0
        assert not banner.isVisible()

    def test_progress_bar_hidden_initially(self) -> None:
        banner = UpdateBanner()
        assert not banner._progress.isVisible()

    def test_action_btn_hidden_initially(self) -> None:
        banner = UpdateBanner()
        assert not banner._action_btn.isVisible()


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestUpdateBannerStateTransitions:
    """Verify visual state transitions."""

    def test_show_downloading(self) -> None:
        banner = UpdateBanner()
        banner.show_downloading('1.2.3')
        assert banner.state == UpdateBannerState.DOWNLOADING
        assert banner._target_version == '1.2.3'
        assert banner._progress.isVisible()
        assert not banner._action_btn.isVisible()
        assert '1.2.3' in banner._message.text()

    def test_show_downloading_progress(self) -> None:
        banner = UpdateBanner()
        banner.show_downloading('1.0.0')
        # First progress value switches from indeterminate to determinate
        banner.show_downloading_progress(42)
        assert banner._progress.maximum() == 100
        assert banner._progress.value() == 42

    def test_show_downloading_progress_ignored_when_not_downloading(self) -> None:
        banner = UpdateBanner()
        banner.show_ready('1.0.0')
        # Should be a no-op, not crash
        banner.show_downloading_progress(50)
        assert banner.state == UpdateBannerState.READY

    def test_show_ready(self) -> None:
        banner = UpdateBanner()
        banner.show_ready('2.0.0')
        assert banner.state == UpdateBannerState.READY
        assert banner._action_btn.isVisible()
        assert banner._action_btn.text() == 'Restart Now'
        assert not banner._progress.isVisible()
        assert '2.0.0' in banner._message.text()

    def test_show_error(self) -> None:
        banner = UpdateBanner()
        banner.show_error('Something broke')
        assert banner.state == UpdateBannerState.ERROR
        assert banner._action_btn.isVisible()
        assert banner._action_btn.text() == 'Retry'
        assert 'Something broke' in banner._message.text()

    def test_hide_banner(self) -> None:
        banner = UpdateBanner()
        banner.show_ready('1.0.0')
        assert banner.state == UpdateBannerState.READY
        banner.hide_banner()
        assert banner.state == UpdateBannerState.HIDDEN

    def test_hide_banner_noop_when_already_hidden(self) -> None:
        banner = UpdateBanner()
        banner.hide_banner()  # should not raise
        assert banner.state == UpdateBannerState.HIDDEN

    def test_downloading_to_ready_transition(self) -> None:
        banner = UpdateBanner()
        banner.show_downloading('3.0.0')
        assert banner.state == UpdateBannerState.DOWNLOADING
        banner.show_ready('3.0.0')
        assert banner.state == UpdateBannerState.READY
        assert not banner._progress.isVisible()

    def test_error_to_downloading_transition(self) -> None:
        banner = UpdateBanner()
        banner.show_error('fail')
        assert banner.state == UpdateBannerState.ERROR
        banner.show_downloading('4.0.0')
        assert banner.state == UpdateBannerState.DOWNLOADING


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class TestUpdateBannerSignals:
    """Verify signal emissions from user actions."""

    def test_restart_signal_on_ready_action(self) -> None:
        banner = UpdateBanner()
        banner.show_ready('1.0.0')

        received = []
        banner.restart_requested.connect(lambda: received.append(True))
        banner._action_btn.click()
        assert received == [True]

    def test_retry_signal_on_error_action(self) -> None:
        banner = UpdateBanner()
        banner.show_error('oops')

        received = []
        banner.retry_requested.connect(lambda: received.append(True))
        banner._action_btn.click()
        assert received == [True]

    def test_dismissed_signal_on_dismiss(self) -> None:
        banner = UpdateBanner()
        banner.show_ready('1.0.0')

        received = []
        banner.dismissed.connect(lambda: received.append(True))
        banner._dismiss_btn.click()
        assert received == [True]
        assert banner.state == UpdateBannerState.HIDDEN

    def test_action_btn_click_when_hidden_is_noop(self) -> None:
        """Clicking the action button when hidden should emit no signal."""
        banner = UpdateBanner()

        received: list[str] = []
        banner.restart_requested.connect(lambda: received.append('restart'))
        banner.retry_requested.connect(lambda: received.append('retry'))
        banner._action_btn.click()
        assert received == []


# ---------------------------------------------------------------------------
# Error auto-dismiss
# ---------------------------------------------------------------------------


class TestUpdateBannerAutoDismiss:
    """Verify the error banner auto-dismiss timer."""

    def test_error_auto_dismiss_resets_to_hidden(self) -> None:
        """The error banner should auto-dismiss after the configured delay."""
        banner = UpdateBanner()
        banner.show_error('transient error')
        assert banner.state == UpdateBannerState.ERROR

        # Directly invoke the auto-dismiss slot instead of waiting
        banner._auto_dismiss_error()
        assert banner.state == UpdateBannerState.HIDDEN

    def test_auto_dismiss_noop_if_state_changed(self) -> None:
        """If the state changed before the timer fires, it's a no-op."""
        banner = UpdateBanner()
        banner.show_error('oops')
        banner.show_ready('1.0.0')  # state changed to READY
        banner._auto_dismiss_error()  # should not reset to HIDDEN
        assert banner.state == UpdateBannerState.READY
