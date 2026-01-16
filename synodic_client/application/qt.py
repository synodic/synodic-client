"""gui"""

import logging
from typing import LiteralString

from porringer.api import API, APIParameters
from porringer.schema import ListPluginsParameters, LocalConfiguration
from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.client import Client

icon: LiteralString = 'icon.png'


def application() -> None:
    """Entrypoint"""
    client = Client()

    logger = logging.getLogger('synodic_client')

    local_config = LocalConfiguration()
    api_params = APIParameters(logger)
    porringer = API(local_config, api_params)

    list_params = ListPluginsParameters()
    list_results = porringer.plugin.list(list_params)

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    screen = Screen()

    tray = TrayScreen(app, client, icon, screen.window)

    app.exec_()


if __name__ == '__main__':
    application()
