"""gui"""

from typing import LiteralString

from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.client import Client

icon: LiteralString = 'icon.png'


def application() -> None:
    """Entrypoint"""
    client = Client()

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    screen = Screen()

    tray = TrayScreen(app, client, icon, screen.window)

    app.exec_()
