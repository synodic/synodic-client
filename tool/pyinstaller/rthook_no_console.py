"""PyInstaller runtime hook: suppress console windows for child processes.

When the application is built as a windowed executable (``console=False``),
every ``subprocess.Popen`` call that launches a console program (pip, pipx,
uv, winget, etc.) would briefly flash a visible console window.  This hook
patches every ``subprocess.Popen`` call with two complementary mitigations:

* ``CREATE_NO_WINDOW`` in *creationflags* — prevents Windows from allocating
  a new console for the child process.
* ``STARTUPINFO`` with ``STARTF_USESHOWWINDOW`` and ``wShowWindow=SW_HIDE``
  — tells Windows to pass ``SW_HIDE`` as the initial ``nCmdShow`` to the
  child, suppressing the brief window flash that some GUI-subsystem tools
  (e.g. ``winget.exe``) produce even without a console.

Placed as a runtime hook so the patch is active before any application or
library code spawns subprocesses.
"""

import subprocess
import sys
from typing import Any

if sys.platform == 'win32':
    import subprocess as _sp

    _SW_HIDE = 0
    _STARTF_USESHOWWINDOW = _sp.STARTF_USESHOWWINDOW
    _CREATE_NO_WINDOW = _sp.CREATE_NO_WINDOW

    # [DIAG] Toggle to log every subprocess spawn to stderr.
    _SUBPROCESS_LOGGING = True

    _original_init = subprocess.Popen.__init__

    def _patched_init(self: subprocess.Popen, *args: Any, **kwargs: Any) -> None:
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | _CREATE_NO_WINDOW

        startupinfo = kwargs.get('startupinfo') or _sp.STARTUPINFO()
        startupinfo.dwFlags |= _STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = _SW_HIDE
        kwargs['startupinfo'] = startupinfo

        if _SUBPROCESS_LOGGING:
            cmd = args[0] if args else kwargs.get('args', '<unknown>')
            print(f'[DIAG] subprocess.Popen: {cmd}', file=sys.stderr, flush=True)

        _original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init
