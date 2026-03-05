"""Tests for the Settings window."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from synodic_client.application.screen.settings import SettingsWindow
from synodic_client.application.theme import SETTINGS_WINDOW_MIN_SIZE
from synodic_client.resolution import ResolvedConfig
from synodic_client.schema import DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES, DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

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


def _make_window(config: ResolvedConfig | None = None, version: str = '0.0.0.test') -> SettingsWindow:
    """Create a ``SettingsWindow`` without showing it."""
    cfg = config or _make_config()
    window = SettingsWindow(cfg, version=version)
    return window


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSettingsWindowConstruction:
    """Verify that the settings window builds without errors."""

    @staticmethod
    def test_default_config() -> None:
        """Window title is set correctly."""
        window = _make_window()
        assert window.windowTitle() == 'Synodic Settings'

    @staticmethod
    def test_minimum_size() -> None:
        """Minimum size matches the theme constant."""
        window = _make_window()
        assert window.minimumWidth() == SETTINGS_WINDOW_MIN_SIZE[0]
        assert window.minimumHeight() == SETTINGS_WINDOW_MIN_SIZE[1]

    @staticmethod
    def test_version_label_displays_passed_version() -> None:
        """Version label shows the version string passed to the constructor."""
        window = _make_window(version='1.2.3.dev42')
        assert window._version == '1.2.3.dev42'


# ---------------------------------------------------------------------------
# sync_from_config
# ---------------------------------------------------------------------------


class TestSyncFromConfig:
    """Verify that controls reflect the config after sync."""

    @staticmethod
    def test_channel_stable_default() -> None:
        """Default config selects the Stable channel."""
        window = _make_window(_make_config())
        window.sync_from_config()
        assert window._channel_combo.currentIndex() == 0
        assert window._channel_combo.currentText() == 'Stable'

    @staticmethod
    def test_channel_dev() -> None:
        """Config with update_channel='dev' selects Development."""
        window = _make_window(_make_config(update_channel='dev'))
        window.sync_from_config()
        assert window._channel_combo.currentIndex() == 1
        assert window._channel_combo.currentText() == 'Development'

    @staticmethod
    def test_update_source_blank() -> None:
        """Default config leaves the source field empty."""
        window = _make_window(_make_config())
        window.sync_from_config()
        assert not window._source_edit.text()

    @staticmethod
    def test_update_source_set() -> None:
        """Custom update source is reflected in the line edit."""
        window = _make_window(_make_config(update_source='https://example.com'))
        window.sync_from_config()
        assert window._source_edit.text() == 'https://example.com'

    @staticmethod
    def test_auto_update_interval_default() -> None:
        """Default auto-update interval shows the module default."""
        window = _make_window(_make_config())
        window.sync_from_config()
        assert window._auto_update_spin.value() == DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_auto_update_interval_custom() -> None:
        """Custom auto-update interval is shown in the spinbox."""
        custom_interval = 60
        window = _make_window(_make_config(auto_update_interval_minutes=custom_interval))
        window.sync_from_config()
        assert window._auto_update_spin.value() == custom_interval

    @staticmethod
    def test_tool_update_interval_default() -> None:
        """Default tool-update interval shows the module default."""
        window = _make_window(_make_config())
        window.sync_from_config()
        assert window._tool_update_spin.value() == DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_tool_update_interval_custom() -> None:
        """Custom tool-update interval is shown in the spinbox."""
        custom_interval = 45
        window = _make_window(_make_config(tool_update_interval_minutes=custom_interval))
        window.sync_from_config()
        assert window._tool_update_spin.value() == custom_interval

    @staticmethod
    def test_detect_updates_true_default() -> None:
        """Default detect_updates is checked."""
        window = _make_window(_make_config())
        window.sync_from_config()
        assert window._detect_updates_check.isChecked() is True

    @staticmethod
    def test_detect_updates_false() -> None:
        """Disabled detect_updates is unchecked."""
        window = _make_window(_make_config(detect_updates=False))
        window.sync_from_config()
        assert window._detect_updates_check.isChecked() is False

    @staticmethod
    def test_auto_start_reflects_registry() -> None:
        """Auto-start checkbox mirrors the OS registration state."""
        window = _make_window(_make_config())
        with patch('synodic_client.application.screen.settings.is_startup_registered', return_value=True):
            window.sync_from_config()
        assert window._auto_start_check.isChecked() is True


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestSettingsCallbacks:
    """Verify that control changes persist via update_user_config and emit the signal."""

    @staticmethod
    def test_channel_change_to_dev() -> None:
        """Switching to dev calls update_user_config and emits settings_changed."""
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        new_config = _make_config(update_channel='dev')
        with patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config):
            window._channel_combo.setCurrentIndex(1)

        signal_spy.assert_called_once_with(new_config)

    @staticmethod
    def test_channel_change_to_stable() -> None:
        """Switching from dev to stable persists 'stable'."""
        config = _make_config(update_channel='dev')
        window = _make_window(config)
        window.sync_from_config()

        new_config = _make_config(update_channel='stable')
        target = 'synodic_client.application.screen.settings.update_user_config'
        with patch(target, return_value=new_config) as mock_update:
            window._channel_combo.setCurrentIndex(0)

        mock_update.assert_called_with(update_channel='stable')

    @staticmethod
    def test_source_change() -> None:
        """Editing the source saves and emits."""
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        new_config = _make_config(update_source='https://custom.example.com')
        with patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config):
            window._source_edit.setText('https://custom.example.com')
            window._on_source_changed()

        signal_spy.assert_called_once_with(new_config)

    @staticmethod
    def test_source_blank_sets_none() -> None:
        """Clearing the source field stores None."""
        config = _make_config(update_source='https://old.example.com')
        window = _make_window(config)

        new_config = _make_config(update_source=None)
        target = 'synodic_client.application.screen.settings.update_user_config'
        with patch(target, return_value=new_config) as mock_update:
            window._source_edit.setText('')
            window._on_source_changed()

        mock_update.assert_called_with(update_source=None)

    @staticmethod
    def test_auto_update_interval_change() -> None:
        """Changing auto-update interval saves and emits."""
        new_interval = 90
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        new_config = _make_config(auto_update_interval_minutes=new_interval)
        with patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config):
            window._auto_update_spin.setValue(new_interval)

        signal_spy.assert_called_once_with(new_config)

    @staticmethod
    def test_tool_update_interval_change() -> None:
        """Changing tool-update interval saves and emits."""
        new_interval = 120
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        new_config = _make_config(tool_update_interval_minutes=new_interval)
        with patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config):
            window._tool_update_spin.setValue(new_interval)

        signal_spy.assert_called_once_with(new_config)

    @staticmethod
    def test_detect_updates_change() -> None:
        """Toggling detect_updates saves and emits."""
        config = _make_config()
        window = _make_window(config)
        window.sync_from_config()
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        new_config = _make_config(detect_updates=False)
        with patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config):
            window._detect_updates_check.setChecked(False)

        signal_spy.assert_called_once_with(new_config)

    @staticmethod
    def test_auto_start_registers_startup() -> None:
        """Enabling auto-start calls register_startup."""
        config = _make_config()
        window = _make_window(config)

        new_config = _make_config(auto_start=True)
        with (
            patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config),
            patch('synodic_client.application.screen.settings.register_startup') as mock_register,
            patch('synodic_client.application.screen.settings.is_startup_registered', return_value=False),
        ):
            window._auto_start_check.setChecked(True)

        mock_register.assert_called_once()

    @staticmethod
    def test_auto_start_removes_startup() -> None:
        """Disabling auto-start calls remove_startup."""
        config = _make_config(auto_start=True)
        window = _make_window(config)
        # Manually set initial state without triggering signals
        window._auto_start_check.blockSignals(True)
        window._auto_start_check.setChecked(True)
        window._auto_start_check.blockSignals(False)

        new_config = _make_config(auto_start=False)
        with (
            patch('synodic_client.application.screen.settings.update_user_config', return_value=new_config),
            patch('synodic_client.application.screen.settings.remove_startup') as mock_remove,
        ):
            window._auto_start_check.setChecked(False)

        mock_remove.assert_called_once()


# ---------------------------------------------------------------------------
# sync_from_config does not emit signals
# ---------------------------------------------------------------------------


class TestSyncDoesNotEmit:
    """Verify that sync_from_config does not trigger settings_changed."""

    @staticmethod
    def test_sync_no_signal() -> None:
        """Syncing controls from config must not emit settings_changed."""
        config = _make_config(update_channel='dev', auto_update_interval_minutes=60)
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        window.sync_from_config()

        signal_spy.assert_not_called()


# ---------------------------------------------------------------------------
# Check for Updates button
# ---------------------------------------------------------------------------


class TestCheckForUpdatesButton:
    """Verify the Check for Updates button and inline status label."""

    @staticmethod
    def test_button_and_label_exist() -> None:
        """Window has the check-updates button and status label."""
        window = _make_window()
        assert hasattr(window, '_check_updates_btn')
        assert hasattr(window, '_update_status_label')
        assert window._check_updates_btn.text() == 'Check for Updates\u2026'
        assert not window._update_status_label.text()

    @staticmethod
    def test_click_emits_signal_and_disables() -> None:
        """Clicking the button emits check_updates_requested and disables it."""
        window = _make_window()
        signal_spy = MagicMock()
        window.check_updates_requested.connect(signal_spy)

        window._check_updates_btn.click()

        signal_spy.assert_called_once()
        assert window._check_updates_btn.isEnabled() is False
        assert window._update_status_label.text() == 'Checking\u2026'

    @staticmethod
    def test_set_update_status() -> None:
        """set_update_status sets the label text and style."""
        window = _make_window()
        window.set_update_status('Up to date', 'color: green;')
        assert window._update_status_label.text() == 'Up to date'
        assert 'green' in window._update_status_label.styleSheet()

    @staticmethod
    def test_reset_check_updates_button() -> None:
        """reset_check_updates_button re-enables the button."""
        window = _make_window()
        window._check_updates_btn.setEnabled(False)

        window.reset_check_updates_button()

        assert window._check_updates_btn.isEnabled() is True

    @staticmethod
    def test_set_checking() -> None:
        """set_checking disables the button and shows 'Checking\u2026' status."""
        window = _make_window()
        window.set_checking()
        assert window._check_updates_btn.isEnabled() is False
        assert window._update_status_label.text() == 'Checking\u2026'
