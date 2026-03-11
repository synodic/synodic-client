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

        self.tray_icon = app_icon()

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)
        self.tray.activated.connect(self._on_tray_activated)

        # At early Windows login the notification area may not be ready.
        # Retry with back-off so the icon eventually appears.
        self._tray_retry_count = 0
        self._tray_retry_timer: QTimer | None = None
        self._show_tray_icon()

        self._build_menu(app, window)

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

    def _build_menu(self, app: QApplication, window: MainWindow) -> None:
        """Build the tray context menu."""
        self.menu = QMenu()

        self.open_action = QAction('Open', self.menu)
        self.menu.addAction(self.open_action)
        self.open_action.triggered.connect(window.show)

        self.menu.addSeparator()

        self.settings_action = QAction('Settings\u2026', self.menu)
        self.settings_action.triggered.connect(self._show_settings)
        self.menu.addAction(self.settings_action)

        self.menu.addSeparator()

        self.quit_action = QAction('Quit', self.menu)
        self.quit_action.triggered.connect(app.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)

    # Maximum number of tray-visibility retries at startup.
    _TRAY_MAX_RETRIES = 5
    # Delay between retries in milliseconds.
    _TRAY_RETRY_DELAY_MS = 2000

    def _show_tray_icon(self) -> None:
        """Show the tray icon, retrying if the system tray is not ready."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.setVisible(True)
            logger.debug('System tray icon shown')
            return

        if self._tray_retry_count < self._TRAY_MAX_RETRIES:
            self._tray_retry_count += 1
            logger.warning(
                'System tray not available, retrying (%d/%d)',
                self._tray_retry_count,
                self._TRAY_MAX_RETRIES,
            )
            self._tray_retry_timer = QTimer()
            self._tray_retry_timer.setSingleShot(True)
            self._tray_retry_timer.timeout.connect(self._show_tray_icon)
            self._tray_retry_timer.start(self._TRAY_RETRY_DELAY_MS)
        else:
            # Exhausted retries — show anyway as a best-effort fallback.
            logger.warning(
                'System tray still not available after %d retries, forcing visibility',
                self._TRAY_MAX_RETRIES,
            )
            self.tray.setVisible(True)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (e.g. double-click)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _show_settings(self) -> None:
        """Show the settings window."""
        self._settings_window.show()

    @staticmethod
    def _is_user_active() -> bool:
        """Return ``True`` when the user has a visible application window.

        Checks all top-level ``QMainWindow`` instances (main window,
        settings, install previews) so that auto-apply is deferred
        whenever *any* window is open.
        """
        return any(w.isVisible() for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow))

    def shutdown(self) -> None:
        """Stop all timers and cancel in-flight tasks for a clean exit."""
        self._update_controller.shutdown()
        self._tool_orchestrator.shutdown()
        logger.info('TrayScreen shut down')
