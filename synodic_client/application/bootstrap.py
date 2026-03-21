"""Bootstrap entry point for PyInstaller builds.

Runs the lightweight startup preamble — logging, Velopack hooks, and
protocol registration — **before** importing heavy modules (PySide6,
porringer).  Velopack's install/uninstall/update hooks have strict
timeouts (15–30 s) and must complete before the process is killed.

Import order matters:
    1. stdlib + config (pure-Python, fast)
    2. configure_logging() — now Qt-free
    3. sync_startup() — refresh Windows auto-startup registry **before**
       Velopack, which may exit the process during post-update hooks
    4. initialize_velopack() — hooks run with logging active
    5. run_startup_preamble() — protocol, config seed, auto-startup
    6. import qt.application — PySide6 / porringer loaded here
"""

import logging
import sys
import traceback


def bootstrap() -> None:
    """Execute the ordered bootstrap sequence."""
    try:
        from synodic_client.config import set_dev_mode
        from synodic_client.logging import configure_logging
        from synodic_client.protocol import extract_uri_from_args
        from synodic_client.subprocess_patch import apply as _apply_subprocess_patch
        from synodic_client.updater import initialize_velopack
    except Exception:
        # Last-resort crash log when imports fail before logging is configured.
        import os

        _fallback = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'Synodic', 'logs', 'bootstrap-crash.log')
        os.makedirs(os.path.dirname(_fallback), exist_ok=True)
        with open(_fallback, 'a', encoding='utf-8') as _f:
            _f.write(traceback.format_exc())
        raise

    # Parse flags early so logging uses the right filename and level.
    dev_mode = '--dev' in sys.argv[1:]
    debug = '--debug' in sys.argv[1:]
    set_dev_mode(dev_mode)
    _apply_subprocess_patch()

    configure_logging(debug=debug)

    logger = logging.getLogger(__name__)
    logger.info('Bootstrap started (exe=%s, argv=%s)', sys.executable, sys.argv)

    # Refresh the Windows auto-startup registry entry BEFORE Velopack
    # initialisation.  App.run() may exit the current process during
    # post-update lifecycle hooks, so sync_startup must run first to
    # ensure the registry path stays current after an update.
    if not dev_mode:
        from synodic_client.resolution import resolve_config
        from synodic_client.startup import sync_startup

        config = resolve_config()
        sync_startup(sys.executable, auto_start=config.auto_start)

    initialize_velopack()

    if not dev_mode:
        from synodic_client.application.init import run_startup_preamble

        run_startup_preamble(sys.executable)

    # Heavy imports happen here — PySide6, porringer, etc.

    from synodic_client.application.qt import application

    application(uri=extract_uri_from_args(), dev_mode=dev_mode, debug=debug)


bootstrap()
