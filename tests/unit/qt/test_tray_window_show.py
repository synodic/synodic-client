"""Tests that the tray only brings the window to the front on manual actions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from synodic_client.application.schema import ToolUpdateResult
from synodic_client.application.screen.tray import TrayScreen


@pytest.fixture
def tray_screen():
    """Build a minimal ``TrayScreen`` with mocked collaborators."""
    with (
        patch('synodic_client.application.screen.tray.resolve_config'),
        patch('synodic_client.application.screen.tool_update_controller.resolve_update_config') as mock_ucfg,
        patch('synodic_client.application.screen.tray.UpdateController'),
    ):
        # Disable timers by setting intervals to 0
        mock_ucfg.return_value = MagicMock(
            auto_update_interval_minutes=0,
            tool_update_interval_minutes=0,
        )

        app = MagicMock()
        client = MagicMock()
        window = MagicMock()
        # SettingsWindow expects a ResolvedConfig – pass a mock
        with patch('synodic_client.application.screen.tray.SettingsWindow'):
            ts = TrayScreen(app, client, window)

        return ts


class TestToolUpdateWindowShow:
    """_on_tool_update_finished should only show the window for manual updates."""

    @staticmethod
    def test_auto_update_does_not_show_window(tray_screen) -> None:
        """Periodic (automatic) tool update must not bring the window forward."""
        result = ToolUpdateResult(manifests_processed=1, updated=1)
        tray_screen._tool_orchestrator._on_tool_update_finished(result)
        tray_screen._window.show.assert_not_called()

    @staticmethod
    def test_manual_plugin_update_shows_window(tray_screen) -> None:
        """A user-initiated single-plugin update should show the window."""
        result = ToolUpdateResult(manifests_processed=1, updated=1)
        tray_screen._tool_orchestrator._on_tool_update_finished(result, updating_plugin='pipx', manual=True)
        tray_screen._window.show.assert_called_once()

    @staticmethod
    def test_manual_package_update_shows_window(tray_screen) -> None:
        """A user-initiated single-package update should show the window."""
        result = ToolUpdateResult(manifests_processed=1, updated=1)
        tray_screen._tool_orchestrator._on_tool_update_finished(
            result,
            updating_package=('pipx', 'ruff'),
            manual=True,
        )
        tray_screen._window.show.assert_called_once()

    @staticmethod
    def test_auto_update_with_no_changes_does_not_show(tray_screen) -> None:
        """An automatic check with nothing to update must stay hidden."""
        result = ToolUpdateResult(manifests_processed=1, already_latest=1)
        tray_screen._tool_orchestrator._on_tool_update_finished(result)
        tray_screen._window.show.assert_not_called()
