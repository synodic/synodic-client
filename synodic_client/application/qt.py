"""GUI entry point for the Synodic Client application."""

import logging
import sys
from urllib.parse import parse_qs, urlparse

from porringer.api import API, APIParameters
from porringer.schema import ListPluginsParameters, LocalConfiguration
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from synodic_client.application.instance import SingleInstance
from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.client import Client
from synodic_client.resolution import resolve_config, resolve_update_config
from synodic_client.updater import initialize_velopack

_PROTOCOL_SCHEME = 'synodic'


def find_uri(args: list[str]) -> str | None:
    """Find a ``synodic://`` URI in the command-line arguments.

    Args:
        args: Command-line arguments (typically ``sys.argv[1:]``).

    Returns:
        The first ``synodic://`` URI found, or None.
    """
    for arg in args:
        if arg.lower().startswith(f'{_PROTOCOL_SCHEME}://'):
            return arg
    return None


def parse_uri(uri: str) -> dict[str, str | list[str]]:
    """Parse a ``synodic://`` URI into its components.

    Example:
        ``synodic://install?manifest=https://example.com/foo.toml``
        returns ``{'action': 'install', 'manifest': ['https://example.com/foo.toml']}``.

    Args:
        uri: A ``synodic://`` URI string.

    Returns:
        A dict with ``'action'`` (the host/path) and any query parameters.
    """
    parsed = urlparse(uri)
    result: dict[str, str | list[str]] = {
        'action': parsed.netloc or parsed.path.strip('/'),
    }
    result.update(parse_qs(parsed.query))
    return result


def application() -> None:
    """Application entry point."""
    # Initialize Velopack early, before any UI
    initialize_velopack()

    logger = logging.getLogger('synodic_client')
    logging.basicConfig(level=logging.INFO)

    # Check for a synodic:// URI in arguments
    uri = find_uri(sys.argv[1:])
    if uri:
        logger.info('Received URI: %s', uri)

    # Load persistent configuration
    config = resolve_config()

    client = Client()

    local_config = LocalConfiguration()
    api_params = APIParameters(logger)
    porringer = API(local_config, api_params)

    # Determine update channel and source from persistent config
    update_config = resolve_update_config(config)
    client.initialize_updater(update_config)

    logger.info(
        'Synodic Client v%s started (channel: %s, source: %s)',
        client.version,
        update_config.channel.name,
        update_config.repo_url,
    )

    list_params = ListPluginsParameters()
    porringer.plugin.list(list_params)

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    # Single-instance management
    instance = SingleInstance(app)

    if instance.try_send_to_existing(uri or ''):
        # Another instance is running — forward the URI (if any) and exit
        logger.info('Another instance is already running, exiting')
        sys.exit(0)

    instance.start_server()

    with Client.resource(Client.icon) as icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))

    # Reduce CPU usage when idle - process events less aggressively
    app.setAttribute(Qt.ApplicationAttribute.AA_CompressHighFrequencyEvents)

    _screen = Screen(porringer)
    _tray = TrayScreen(app, client, Client.icon, _screen.window)

    # When another instance sends us a URI, log it
    # TODO: Hook this up to the install preview GUI
    def _on_uri_received(received_uri: str) -> None:
        parsed = urlparse(received_uri)
        logger.info('Received URI from another instance: %s (action: %s)', received_uri, parsed.netloc)

    instance.uri_received.connect(_on_uri_received)

    # If we were launched with a URI, process it now
    if uri:
        parsed = urlparse(uri)
        logger.info('Processing launch URI: %s (action: %s)', uri, parsed.netloc)
        # TODO: Show install preview GUI for the parsed URI

    # sys.exit ensures proper cleanup and exit code propagation
    # Leading underscore indicates references kept alive intentionally until exec() returns
    sys.exit(app.exec())


if __name__ == '__main__':
    application()
