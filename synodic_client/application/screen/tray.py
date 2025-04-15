"""Tray screen for the application."""

from typing import LiteralString

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from synodic_client.application.screen.screen import MainWindow
from synodic_client.client import Client


class TrayScreen:
    """Tray screen for the application."""

    def __init__(self, app: QApplication, client: Client, icon_name: LiteralString, window: MainWindow) -> None:
        """Initialize the tray icon."""
        self._app = app

        with client.resource(icon_name) as icon_path:
            self.tray_icon = QIcon(str(icon_path))

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)

        self.tray.setVisible(True)

        menu = QMenu()

        open_action = QAction('Open')
        menu.addAction(open_action)
        open_action.triggered.connect(window.show)

        settings_action = QAction('Settings')
        menu.addAction(settings_action)

        quit_action = QAction('Quit')
        quit_action.triggered.connect(app.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
