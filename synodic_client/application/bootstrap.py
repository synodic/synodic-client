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
from synodic_client.updater import initialize_velopack

_PROTOCOL_SCHEME = 'synodic'

# Parse --dev flag early so logging uses the right filename.
_dev_mode = '--dev' in sys.argv[1:]
set_dev_mode(_dev_mode)

configure_logging()
initialize_velopack()

if not _dev_mode:
    from synodic_client.application.init import run_startup_preamble

    run_startup_preamble(sys.executable)

# Heavy imports happen here — PySide6, porringer, etc.
from synodic_client.application.qt import application

_uri = next((a for a in sys.argv[1:] if a.lower().startswith(f'{_PROTOCOL_SCHEME}://')), None)
application(uri=_uri, dev_mode=_dev_mode)
