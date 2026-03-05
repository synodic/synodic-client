"""Tray screen for the application."""

import logging

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
from synodic_client.client import Client
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_config,
)

logger = logging.getLogger(__name__)


class TrayScreen:
    """Tray screen for the application."""

    def __init__(
        self,
        app: QApplication,
        client: Client,
        window: MainWindow,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialize the tray icon.

        Args:
            app: The running ``QApplication``.
            client: The Synodic Client service.
            window: The main application window.
            config: Optional pre-resolved configuration.  When ``None``,
                the configuration is resolved from disk on demand.
        """
        self._app = app
        self._client = client
        self._window = window
        self._config = config

        self.tray_icon = app_icon()

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(True)

        self._build_menu(app, window)

        # Settings window (created once, shown/hidden on demand)
        self._settings_window = SettingsWindow(
            self._resolve_config(),
            version=str(self._client.version),
        )
        self._settings_window.settings_changed.connect(self._on_settings_changed)

        # MainWindow gear button -> open settings
        window.settings_requested.connect(self._show_settings)

        # Update controller - owns the self-update lifecycle & timer
        self._banner = window.update_banner
        self._update_controller = UpdateController(
            app,
            client,
            self._banner,
            settings_window=self._settings_window,
            config=config,
        )
        self._update_controller.set_user_active_predicate(self._is_user_active)

        # Tool update orchestrator - owns tool/package update lifecycle
        self._tool_orchestrator = ToolUpdateOrchestrator(
            window,
            self._resolve_config,
            self.tray,
            is_user_active=self._is_user_active,
        )
        self._tool_orchestrator.restart_tool_update_timer()

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

    # -- Config helpers --

    def _resolve_config(self) -> ResolvedConfig:
        """Return the injected config or resolve from disk."""
        if self._config is not None:
            return self._config
        return resolve_config()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (e.g. double-click)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _show_settings(self) -> None:
        """Show the settings window."""
        self._settings_window.show()

    def _is_user_active(self) -> bool:
        """Return ``True`` when the user has a visible application window.

        Checks all top-level ``QMainWindow`` instances (main window,
        settings, install previews) so that auto-apply is deferred
        whenever *any* window is open.
        """
        return any(w.isVisible() for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow))

    def _on_settings_changed(self, config: ResolvedConfig) -> None:
        """React to a change made in the settings window."""
        self._config = config
        # Delegate updater reinit + immediate check to the controller
        self._update_controller.on_settings_changed(config)
        # Restart tool-update timer with new config
        self._tool_orchestrator.restart_tool_update_timer()
