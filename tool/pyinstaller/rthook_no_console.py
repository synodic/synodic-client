"""PyInstaller runtime hook: suppress console windows for child processes.

When the application is built as a windowed executable (``console=False``),
every ``subprocess.Popen`` call that launches a console program (pip, pipx,
uv, winget, etc.) would briefly flash a visible console window.  This hook
merges ``CREATE_NO_WINDOW`` into *creationflags* for every call, suppressing
those flashes while preserving any flags the caller already set.

Placed as a runtime hook so the patch is active before any application or
library code spawns subprocesses.
"""

import subprocess
import sys
from typing import Any

if sys.platform == 'win32':
    _original_init = subprocess.Popen.__init__

    def _patched_init(self: subprocess.Popen, *args: Any, **kwargs: Any) -> None:
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        _original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init
