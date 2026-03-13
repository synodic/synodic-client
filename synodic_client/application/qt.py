"""GUI entry point for the Synodic Client application."""

import asyncio
import ctypes
import importlib.metadata
import logging
import signal
import sys
import traceback
import types
from collections.abc import Callable

import qasync
from porringer.api import API
from porringer.schema import LocalConfiguration
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from synodic_client.application.config_store import ConfigStore
from synodic_client.application.debug import DebugHandler, DebugServices
from synodic_client.application.icon import app_icon
from synodic_client.application.init import run_startup_preamble
from synodic_client.application.instance import SingleInstance
from synodic_client.application.screen.install import InstallPreviewWindow
from synodic_client.application.screen.screen import Screen
from synodic_client.application.screen.tray import TrayScreen
from synodic_client.application.uri import parse_uri
from synodic_client.client import Client
from synodic_client.config import set_dev_mode
from synodic_client.logging import configure_logging, log_path, set_debug_level
from synodic_client.protocol import extract_uri_from_args
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_config,
    resolve_update_config,
)
from synodic_client.subprocess_patch import apply as _apply_subprocess_patch
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
    logger.debug(
        'Resolved config: update_source=%s update_channel=%s auto_update=%dm tool_update=%dm '
        'auto_apply=%s auto_start=%s debug_logging=%s prerelease_packages=%s plugin_auto_update=%s',
        config.update_source,
        config.update_channel,
        config.auto_update_interval_minutes,
        config.tool_update_interval_minutes,
        config.auto_apply,
        config.auto_start,
        config.debug_logging,
        config.prerelease_packages,
        config.plugin_auto_update,
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


def _cancel_all_tasks(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel every pending asyncio task on *loop*.

    Called synchronously from the ``aboutToQuit`` handler.  Each task
    receives a cancellation request; when the event loop processes its
    remaining iterations the ``CancelledError`` propagates and the
    tasks finish cleanly.
    """
    _logger = logging.getLogger(__name__)
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not pending:
        return
    _logger.info('Cancelling %d pending async task(s)', len(pending))
    for task in pending:
        task.cancel()


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


class _TopLevelShowFilter(QObject):
    """[DIAG] Application-wide event filter that logs Show/WindowActivate on top-level widgets."""

    _diag_logger = logging.getLogger('synodic_client.diag.window')

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            event.type() in {QEvent.Type.Show, QEvent.Type.WindowActivate}
            and isinstance(obj, QWidget)
            and obj.isWindow()
        ):
            geo = obj.geometry()
            stack = ''.join(traceback.format_stack(limit=12))
            self._diag_logger.debug(
                '[DIAG] Top-level window %s: class=%s title=%r geo=(%d,%d %dx%d) visible=%s\n%s',
                event.type().name,
                type(obj).__qualname__,
                obj.windowTitle(),
                geo.x(),
                geo.y(),
                geo.width(),
                geo.height(),
                obj.isVisible(),
                stack,
            )
        return False


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

    # Install the diagnostic event filter only when debug-level logging is
    # active — it calls traceback.format_stack() on every top-level Show
    # event, which is measurable overhead in normal operation.
    if logging.getLogger('synodic_client').isEnabledFor(logging.DEBUG):
        diag_filter = _TopLevelShowFilter(app)  # parented to app, prevented from GC
        app.installEventFilter(diag_filter)

    # Allow Ctrl+C in the terminal to terminate the application.
    # Qt's event loop blocks Python's default SIGINT handling, so we
    # install our own handler and use a short timer to let Python
    # process it between Qt events.
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    _signal_timer = QTimer(app)
    _signal_timer.start(500)
    _signal_timer.timeout.connect(lambda: None)

    return app


def application(*, uri: str | None = None, dev_mode: bool = False, debug: bool = False) -> None:
    """Application entry point.

    Args:
        uri: Optional ``synodic://`` URI to process on launch.
        dev_mode: When ``True``, activate dev-mode isolation so that
            the development instance does not share configuration,
            log files, or single-instance locks with the user-installed
            application.  Velopack initialisation and protocol
            registration are skipped.
        debug: When ``True``, enable DEBUG-level file logging.
    """
    # Activate dev-mode namespacing before anything reads config paths.
    set_dev_mode(dev_mode)
    _apply_subprocess_patch()

    # Configure logging before Velopack so install/uninstall hooks and
    # first-run diagnostics are captured in the log file.
    configure_logging(debug=debug)
    logger = logging.getLogger('synodic_client')

    logger.info('Log file: %s', log_path())
    logger.info(
        'Environment: Python %s | PySide6 %s | porringer %s | platform=%s | frozen=%s',
        sys.version.split()[0],
        importlib.metadata.version('PySide6'),
        importlib.metadata.version('porringer'),
        sys.platform,
        getattr(sys, 'frozen', False),
    )

    _install_exception_hook(logger)

    if not dev_mode:
        # All three functions are idempotent — safe to call even when
        # bootstrap.py has already executed them before heavy imports.
        initialize_velopack()
        run_startup_preamble(sys.executable)

    if uri:
        logger.info('Received URI: %s', uri)

    client, porringer, config = _init_services(logger)

    # Honour the persisted debug_logging preference unless the --debug
    # flag already activated it.
    if not debug and config.debug_logging:
        set_debug_level(enabled=True)

    app = _init_app()

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    instance = SingleInstance(app)
    if instance.try_send_to_existing(uri or ''):
        logger.info('Another instance is already running, exiting')
        sys.exit(0)
    instance.start_server()

    _store = ConfigStore(config)
    _screen = Screen(porringer, _store)
    _tray = TrayScreen(app, client, _screen.window, store=_store)

    # Keep install preview windows alive until the app exits
    _install_windows: list[InstallPreviewWindow] = []

    def _handle_install_uri(manifest_url: str) -> None:
        logger.info('Opening install preview for: %s', manifest_url)
        window = InstallPreviewWindow(
            porringer,
            manifest_url,
            config=_store.config,
        )
        _install_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        window.start()

    _debug_handler = DebugHandler(
        DebugServices(
            client=client,
            porringer=porringer,
            coordinator=_screen.window.coordinator,
            config_store=_store,
            update_controller=_tray.update_controller,
            update_model=_tray.update_model,
            tool_orchestrator=_tray.tool_orchestrator,
            main_window=_screen.window,
            settings_window=_tray.settings_window,
        )
    )
    instance.set_debug_handler(_debug_handler.handle)

    instance.uri_received.connect(lambda received_uri: _process_uri(received_uri, _handle_install_uri))

    if uri:
        _process_uri(uri, _handle_install_uri)

    # --- Graceful shutdown ---
    # aboutToQuit fires synchronously when app.quit() is called but
    # before the event loop stops, giving us a window to cancel
    # in-flight async tasks and stop timers.

    def _on_about_to_quit() -> None:
        logger.info('Application shutting down — cancelling async tasks')
        _tray.shutdown()
        _cancel_all_tasks(loop)

    app.aboutToQuit.connect(_on_about_to_quit)

    # qasync integrates the asyncio event loop with Qt's event loop,
    # enabling async/await usage in the GUI layer without dedicated threads.
    with loop:
        loop.run_forever()


if __name__ == '__main__':
    application(uri=extract_uri_from_args())
