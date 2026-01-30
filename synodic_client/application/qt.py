"""gui"""

import logging
import sys

from porringer.api import API, APIParameters
from porringer.schema import ListPluginsParameters, LocalConfiguration
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.client import Client
from synodic_client.updater import UpdateChannel, UpdateConfig, initialize_velopack


def application() -> None:
    """Entrypoint"""
    # Initialize Velopack early, before any UI
    initialize_velopack()

    client = Client()

    logger = logging.getLogger('synodic_client')
    logging.basicConfig(level=logging.INFO)

    local_config = LocalConfiguration()
    api_params = APIParameters(logger)
    porringer = API(local_config, api_params)

    # Initialize the updater
    # Use DEVELOPMENT channel if running from source (not frozen)
    is_dev = not getattr(sys, 'frozen', False)
    update_channel = UpdateChannel.DEVELOPMENT if is_dev else UpdateChannel.STABLE
    update_config = UpdateConfig(channel=update_channel)
    client.initialize_updater(update_config)

    logger.info('Synodic Client v%s started (channel: %s)', client.version, update_channel.name)

    list_params = ListPluginsParameters()
    porringer.plugin.list(list_params)

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    # Reduce CPU usage when idle - process events less aggressively
    app.setAttribute(Qt.ApplicationAttribute.AA_CompressHighFrequencyEvents)

    _screen = Screen()
    _tray = TrayScreen(app, client, Client.icon, _screen.window)

    # sys.exit ensures proper cleanup and exit code propagation
    # Leading underscore indicates references kept alive intentionally until exec() returns
    sys.exit(app.exec())


if __name__ == '__main__':
    application()
