"""Bootstrap entry point for PyInstaller builds.

Runs the lightweight startup preamble — logging, Velopack hooks, and
protocol registration — **before** importing heavy modules (PySide6,
porringer).  Velopack's install/uninstall/update hooks have strict
timeouts (15–30 s) and must complete before the process is killed.

Import order matters:
    1. stdlib + config (pure-Python, fast)
    2. configure_logging() — now Qt-free
    3. initialize_velopack() — hooks run with logging active
    4. run_startup_preamble() — protocol, config seed, auto-startup
    5. import qt.application — PySide6 / porringer loaded here
"""

import sys

from synodic_client.config import set_dev_mode
from synodic_client.logging import configure_logging
from synodic_client.subprocess_patch import apply as _apply_subprocess_patch
from synodic_client.protocol import extract_uri_from_args
from synodic_client.updater import initialize_velopack

# Parse flags early so logging uses the right filename and level.
_dev_mode = '--dev' in sys.argv[1:]
_debug = '--debug' in sys.argv[1:]
set_dev_mode(_dev_mode)
_apply_subprocess_patch()

configure_logging(debug=_debug)
initialize_velopack()

if not _dev_mode:
    from synodic_client.application.init import run_startup_preamble

    run_startup_preamble(sys.executable)

# Heavy imports happen here — PySide6, porringer, etc.
from synodic_client.application.qt import application

application(uri=extract_uri_from_args(), dev_mode=_dev_mode, debug=_debug)
