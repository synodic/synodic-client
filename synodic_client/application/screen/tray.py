"""Tray screen for the application."""

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen.screen import MainWindow
from synodic_client.application.screen.settings import SettingsWindow
from synodic_client.application.screen.tool_update_controller import ToolUpdateOrchestrator
from synodic_client.application.update_controller import UpdateController
from synodic_client.application.update_model import UpdateModel
from synodic_client.client import Client

if TYPE_CHECKING:
    from synodic_client.application.config_store import ConfigStore

logger = logging.getLogger(__name__)


class TrayScreen:
    """Tray screen for the application."""

    def __init__(
        self,
        app: QApplication,
        client: Client,
        window: MainWindow,
        *,
        store: ConfigStore,
    ) -> None:
        """Initialize the tray icon.

        Args:
            app: The running ``QApplication``.
            client: The Synodic Client service.
            window: The main application window.
            store: The centralised :class:`ConfigStore`.
        """
        self._app = app
        self._client = client
        self._window = window
        self._store = store

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(app_icon())
        self.tray.activated.connect(self._on_tray_activated)

        self._build_menu()
        self.tray.setContextMenu(self._menu)

        # At early Windows login the notification area may not be ready.
        # Poll until the tray is available, then show the icon.
        self._tray_poll = QTimer()
        self._tray_poll.setInterval(2000)
        self._tray_poll.timeout.connect(self._try_show_tray_icon)
        self._try_show_tray_icon()

        # Settings window (created once, shown/hidden on demand)
        self._settings_window = SettingsWindow(
            self._store,
            version=str(self._client.version),
        )

        # MainWindow gear button -> open settings
        window.settings_requested.connect(self._show_settings)

        # Update model — centralised observable state for the update lifecycle
        self._update_model = UpdateModel()

        # Update controller - owns the self-update lifecycle & timer
        self._banner = window.update_banner
        self._update_controller = UpdateController(
            app,
            client,
            self._update_model,
            store=self._store,
        )
        self._update_controller.set_user_active_predicate(self._is_user_active)

        # Connect views to the model
        self._banner.connect_model(self._update_model)
        self._settings_window.connect_model(self._update_model)

        # Wire user-action signals back to the controller
        self._banner.restart_requested.connect(self._update_controller.request_apply)
        self._banner.retry_requested.connect(self._update_controller.request_retry)
        self._settings_window.check_updates_requested.connect(self._update_controller.request_check)
        self._settings_window.restart_requested.connect(self._update_controller.request_apply)

        # Tool update orchestrator - owns tool/package update lifecycle
        self._tool_orchestrator = ToolUpdateOrchestrator(
            window,
            self._store,
            self.tray,
            is_user_active=self._is_user_active,
        )
        self._tool_orchestrator.restart_tool_update_timer()

        # Restart tool timer when config changes (e.g. interval edited)
        self._store.changed.connect(lambda _: self._tool_orchestrator.restart_tool_update_timer())

        # Connect ToolsView signals - deferred because ToolsView is created lazily
        window.tools_view_created.connect(self._tool_orchestrator.connect_tools_view)

    def _build_menu(self) -> None:
        """Build the tray context menu."""
        self._menu = QMenu()

        self._open_action = QAction('Open', self._menu)
        self._menu.addAction(self._open_action)
        self._open_action.triggered.connect(self._show_window)

        self._menu.addSeparator()

        self._settings_action = QAction('Settings\u2026', self._menu)
        self._settings_action.triggered.connect(self._show_settings)
        self._menu.addAction(self._settings_action)

        self._menu.addSeparator()

        self._quit_action = QAction('Quit', self._menu)
        self._quit_action.triggered.connect(self._on_quit_triggered)
        self._menu.addAction(self._quit_action)

        self._menu.aboutToShow.connect(lambda: logger.debug('Tray context menu about to show'))

    def _try_show_tray_icon(self) -> None:
        """Show the tray icon once the system tray is available."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_poll.stop()
            self.tray.setVisible(True)
            logger.debug('System tray icon shown')
        elif not self._tray_poll.isActive():
            logger.warning('System tray not available, polling until ready')
            self._tray_poll.start()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation."""
        logger.debug('Tray activated: reason=%s', reason.name)
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _show_window(self) -> None:
        """Show, raise, and focus the main window."""
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_quit_triggered(self) -> None:
        """Handle the Quit menu action."""
        logger.info('Quit requested via tray menu')
        self._app.quit()

    def _show_settings(self) -> None:
        """Show the settings window."""
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    @staticmethod
    def _is_user_active() -> bool:
        """Return ``True`` when the user has a visible application window.

        Checks all top-level ``QMainWindow`` instances (main window,
        settings, install previews) so that auto-apply is deferred
        whenever *any* window is open.
        """
        return any(w.isVisible() for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow))

    @property
    def update_controller(self) -> UpdateController:
        """Return the self-update controller."""
        return self._update_controller

    @property
    def update_model(self) -> UpdateModel:
        """Return the self-update observable model."""
        return self._update_model

    @property
    def tool_orchestrator(self) -> ToolUpdateOrchestrator:
        """Return the tool-update orchestrator."""
        return self._tool_orchestrator

    @property
    def settings_window(self) -> SettingsWindow:
        """Return the settings window."""
        return self._settings_window

    def shutdown(self) -> None:
        """Stop all timers and cancel in-flight tasks for a clean exit."""
        self._tray_poll.stop()
        self._update_controller.shutdown()
        self._tool_orchestrator.shutdown()
        logger.info('TrayScreen shut down')
