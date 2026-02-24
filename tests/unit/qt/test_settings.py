"""Tests for the Settings window."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.settings import SettingsWindow
from synodic_client.application.theme import SETTINGS_WINDOW_MIN_SIZE
from synodic_client.config import GlobalConfiguration
from synodic_client.updater import DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES, DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

_app = QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: object) -> GlobalConfiguration:
    """Create a ``GlobalConfiguration`` with optional field overrides."""
    return GlobalConfiguration(**overrides)  # type: ignore[arg-type]


def _make_window(config: GlobalConfiguration | None = None) -> SettingsWindow:
    """Create a ``SettingsWindow`` without showing it."""
    cfg = config or _make_config()
    window = SettingsWindow(cfg)
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
    """Verify that control changes mutate config and emit the signal."""

    @staticmethod
    def test_channel_change_to_dev() -> None:
        """Switching to dev mutates config and emits settings_changed."""
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        with patch('synodic_client.application.screen.settings.save_config'):
            window._channel_combo.setCurrentIndex(1)

        assert config.update_channel == 'dev'
        signal_spy.assert_called_once()

    @staticmethod
    def test_channel_change_to_stable() -> None:
        """Switching from dev to stable writes 'stable'."""
        config = _make_config(update_channel='dev')
        window = _make_window(config)
        window.sync_from_config()

        with patch('synodic_client.application.screen.settings.save_config'):
            window._channel_combo.setCurrentIndex(0)

        assert config.update_channel == 'stable'

    @staticmethod
    def test_source_change() -> None:
        """Editing the source saves and emits."""
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        with patch('synodic_client.application.screen.settings.save_config'):
            window._source_edit.setText('https://custom.example.com')
            window._on_source_changed()

        assert config.update_source == 'https://custom.example.com'
        signal_spy.assert_called_once()

    @staticmethod
    def test_source_blank_sets_none() -> None:
        """Clearing the source field stores None."""
        config = _make_config(update_source='https://old.example.com')
        window = _make_window(config)

        with patch('synodic_client.application.screen.settings.save_config'):
            window._source_edit.setText('')
            window._on_source_changed()

        assert config.update_source is None

    @staticmethod
    def test_auto_update_interval_change() -> None:
        """Changing auto-update interval saves and emits."""
        new_interval = 90
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        with patch('synodic_client.application.screen.settings.save_config'):
            window._auto_update_spin.setValue(new_interval)

        assert config.auto_update_interval_minutes == new_interval
        signal_spy.assert_called_once()

    @staticmethod
    def test_tool_update_interval_change() -> None:
        """Changing tool-update interval saves and emits."""
        new_interval = 120
        config = _make_config()
        window = _make_window(config)
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        with patch('synodic_client.application.screen.settings.save_config'):
            window._tool_update_spin.setValue(new_interval)

        assert config.tool_update_interval_minutes == new_interval
        signal_spy.assert_called_once()

    @staticmethod
    def test_detect_updates_change() -> None:
        """Toggling detect_updates saves and emits."""
        config = _make_config()
        window = _make_window(config)
        window.sync_from_config()
        signal_spy = MagicMock()
        window.settings_changed.connect(signal_spy)

        with patch('synodic_client.application.screen.settings.save_config'):
            window._detect_updates_check.setChecked(False)

        assert config.detect_updates is False
        signal_spy.assert_called_once()

    @staticmethod
    def test_auto_start_registers_startup() -> None:
        """Enabling auto-start calls register_startup."""
        config = _make_config()
        window = _make_window(config)

        with (
            patch('synodic_client.application.screen.settings.save_config'),
            patch('synodic_client.application.screen.settings.register_startup') as mock_register,
            patch('synodic_client.application.screen.settings.is_startup_registered', return_value=False),
        ):
            window._auto_start_check.setChecked(True)

        assert config.auto_start is True
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

        with (
            patch('synodic_client.application.screen.settings.save_config'),
            patch('synodic_client.application.screen.settings.remove_startup') as mock_remove,
        ):
            window._auto_start_check.setChecked(False)

        assert config.auto_start is False
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
