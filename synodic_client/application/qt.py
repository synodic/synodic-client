"""GUI entry point for the Synodic Client application."""

import logging
import sys
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from porringer.api import API
from porringer.schema import ListPluginsParameters, LocalConfiguration
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from synodic_client.application.instance import SingleInstance
from synodic_client.application.screen.install import InstallPreviewWindow
from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.client import Client
from synodic_client.logging import configure_logging
from synodic_client.protocol import register_protocol
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


def _init_services(logger: logging.Logger) -> tuple[Client, API]:
    """Create and configure core services.

    Returns:
        A (Client, porringer API) tuple.
    """
    config = resolve_config()
    client = Client()

    local_config = LocalConfiguration()
    porringer = API(local_config)

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

    return client, porringer


def _process_uri(uri: str, handler: Callable[[str], None]) -> None:
    """Parse a ``synodic://`` URI and dispatch install actions."""
    parsed_data = parse_uri(uri)
    action = parsed_data.get('action')
    if action == 'install':
        manifests = parsed_data.get('manifest')
        if isinstance(manifests, list) and manifests:
            handler(manifests[0])


def application() -> None:
    """Application entry point."""
    # Initialize Velopack early, before any UI
    initialize_velopack()
    register_protocol(sys.executable)

    configure_logging()
    logger = logging.getLogger('synodic_client')

    uri = find_uri(sys.argv[1:])
    if uri:
        logger.info('Received URI: %s', uri)

    client, porringer = _init_services(logger)

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance(app)
    if instance.try_send_to_existing(uri or ''):
        logger.info('Another instance is already running, exiting')
        sys.exit(0)
    instance.start_server()

    with Client.resource(Client.icon) as icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setAttribute(Qt.ApplicationAttribute.AA_CompressHighFrequencyEvents)

    _screen = Screen(porringer)
    _tray = TrayScreen(app, client, Client.icon, _screen.window)

    # Keep install preview windows alive until the app exits
    _install_windows: list[InstallPreviewWindow] = []

    def _handle_install_uri(manifest_url: str) -> None:
        window = InstallPreviewWindow(porringer, manifest_url)
        _install_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        window.start()

    instance.uri_received.connect(lambda received_uri: _process_uri(received_uri, _handle_install_uri))

    if uri:
        _process_uri(uri, _handle_install_uri)

    # sys.exit ensures proper cleanup and exit code propagation
    # Leading underscore indicates references kept alive intentionally until exec() returns
    sys.exit(app.exec())


if __name__ == '__main__':
    application()
