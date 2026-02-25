"""GUI entry point for the Synodic Client application."""

import asyncio
import ctypes
import logging
import signal
import sys
import types
from collections.abc import Callable

import qasync
from porringer.api import API
from porringer.schema import LocalConfiguration
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from synodic_client.application.icon import app_icon
from synodic_client.application.instance import SingleInstance
from synodic_client.application.screen.install import InstallPreviewWindow
from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.application.uri import parse_uri
from synodic_client.client import Client
from synodic_client.config import set_dev_mode
from synodic_client.logging import configure_logging
from synodic_client.protocol import register_protocol
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_auto_start,
    resolve_config,
    resolve_update_config,
    seed_user_config_from_build,
)
from synodic_client.startup import register_startup, remove_startup
from synodic_client.updater import initialize_velopack


def _init_services(logger: logging.Logger) -> tuple[Client, API, ResolvedConfig]:
    """Create and configure core services.

    Returns:
        A (Client, porringer API, resolved config) tuple.
    """
    config = resolve_config()
    client = Client()

    local_config = LocalConfiguration()
    porringer = API(local_config)

    update_config = resolve_update_config(config)
    client.initialize_updater(update_config)

    cached_dirs = porringer.cache.list_directories()

    logger.info(
        'Synodic Client v%s started (channel: %s, source: %s, cached_projects: %d)',
        client.version,
        update_config.channel.name,
        update_config.repo_url,
        len(cached_dirs),
    )

    return client, porringer, config


def _process_uri(uri: str, handler: Callable[[str], None]) -> None:
    """Parse a ``synodic://`` URI and dispatch install actions."""
    parsed_data = parse_uri(uri)
    action = parsed_data.get('action')
    if action == 'install':
        manifests = parsed_data.get('manifest')
        if isinstance(manifests, list) and manifests:
            handler(manifests[0])


def _install_exception_hook(logger: logging.Logger) -> None:
    """Redirect unhandled exceptions to the log file.

    Ensures tracebacks are visible even in windowed (``console=False``)
    PyInstaller builds.
    """
    _original_excepthook = sys.excepthook

    def _exception_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: types.TracebackType | None,
    ) -> None:
        logger.critical('Unhandled exception', exc_info=(exc_type, exc_value, exc_tb))
        _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _exception_hook


def _init_app() -> QApplication:
    """Create and configure the ``QApplication``."""
    # Set the App User Model ID so Windows uses our icon on the taskbar
    # instead of the generic python.exe icon.
    if sys.platform == 'win32':
        windll = getattr(ctypes, 'windll', None)
        if windll is not None:
            windll.shell32.SetCurrentProcessExplicitAppUserModelID('synodic.client')

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    app.setAttribute(Qt.ApplicationAttribute.AA_CompressHighFrequencyEvents)

    # Allow Ctrl+C in the terminal to terminate the application.
    # Qt's event loop blocks Python's default SIGINT handling, so we
    # install our own handler and use a short timer to let Python
    # process it between Qt events.
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    _signal_timer = QTimer(app)
    _signal_timer.start(500)
    _signal_timer.timeout.connect(lambda: None)

    return app


def application(*, uri: str | None = None, dev_mode: bool = False) -> None:
    """Application entry point.

    Args:
        uri: Optional ``synodic://`` URI to process on launch.
        dev_mode: When ``True``, activate dev-mode isolation so that
            the development instance does not share configuration,
            log files, or single-instance locks with the user-installed
            application.  Velopack initialisation and protocol
            registration are skipped.
    """
    # Activate dev-mode namespacing before anything reads config paths.
    set_dev_mode(dev_mode)

    # Configure logging before Velopack so install/uninstall hooks and
    # first-run diagnostics are captured in the log file.
    configure_logging()
    logger = logging.getLogger('synodic_client')
    _install_exception_hook(logger)

    if not dev_mode:
        # Initialize Velopack early, before any UI.
        # Console window suppression for subprocesses is handled by the
        # PyInstaller runtime hook (rthook_no_console.py).
        initialize_velopack()
        register_protocol(sys.executable)

        # Seed user config from build config (one-time propagation).
        seed_user_config_from_build()

        startup_config = resolve_config()
        if resolve_auto_start(startup_config):
            register_startup(sys.executable)
        else:
            remove_startup()

    if uri:
        logger.info('Received URI: %s', uri)

    client, porringer, config = _init_services(logger)

    app = _init_app()

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    instance = SingleInstance(app)
    if instance.try_send_to_existing(uri or ''):
        logger.info('Another instance is already running, exiting')
        sys.exit(0)
    instance.start_server()

    _screen = Screen(porringer, config)
    _tray = TrayScreen(app, client, _screen.window, config=config)

    # Keep install preview windows alive until the app exits
    _install_windows: list[InstallPreviewWindow] = []

    def _handle_install_uri(manifest_url: str) -> None:
        logger.info('Opening install preview for: %s', manifest_url)
        window = InstallPreviewWindow(
            porringer,
            manifest_url,
            config=config,
        )
        _install_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        window.start()

    instance.uri_received.connect(lambda received_uri: _process_uri(received_uri, _handle_install_uri))

    if uri:
        _process_uri(uri, _handle_install_uri)

    # qasync integrates the asyncio event loop with Qt's event loop,
    # enabling async/await usage in the GUI layer without dedicated threads.
    with loop:
        loop.run_forever()


_PROTOCOL_SCHEME = 'synodic'

if __name__ == '__main__':
    _uri = next((a for a in sys.argv[1:] if a.lower().startswith(f'{_PROTOCOL_SCHEME}://')), None)
    application(uri=_uri)
