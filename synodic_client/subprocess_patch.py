"""Suppress console-window flashes for child processes on Windows.

When the application runs as a windowed executable (``console=False``),
every subprocess that launches a console program (pip, pipx, uv, winget,
etc.) would briefly flash a visible console window.  This module patches
``subprocess.Popen.__init__`` to inject two complementary flags:

* ``CREATE_NO_WINDOW`` in *creationflags* — prevents Windows from
  allocating a new console for the child process.
* ``STARTUPINFO`` with ``STARTF_USESHOWWINDOW`` and
  ``wShowWindow=SW_HIDE`` — tells Windows to pass ``SW_HIDE`` as the
  initial ``nCmdShow`` to the child, suppressing the brief window flash
  that some GUI-subsystem tools (e.g. ``winget.exe``) produce even
  without a console.

Since ``asyncio.create_subprocess_exec`` and all other high-level
subprocess APIs ultimately call ``subprocess.Popen``, patching
``Popen.__init__`` is sufficient.

The PyInstaller runtime hook (``rthook_no_console.py``) applies the same
patch for frozen builds.  This module covers the dev-mode entry point
where the rthook does not run.

Call :func:`apply` once at process startup — it is idempotent.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

_applied: list[bool] = []


def apply() -> None:
    """Activate the subprocess-suppression patch (idempotent, Windows-only)."""
    if _applied or sys.platform != 'win32':
        return
    _applied.append(True)

    _patch_popen()


# ------------------------------------------------------------------
# subprocess.Popen patch
# ------------------------------------------------------------------

_CREATE_NO_WINDOW: int = 0
_STARTF_USESHOWWINDOW: int = 0
_SW_HIDE: int = 0
_StartupInfo: type | None = None

if sys.platform == 'win32':
    _CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW  # 0x0800_0000
    _STARTF_USESHOWWINDOW = subprocess.STARTF_USESHOWWINDOW
    _SW_HIDE = 0
    _StartupInfo = subprocess.STARTUPINFO


def _inject_hidden_flags(kwargs: dict[str, Any]) -> None:
    """Mutate *kwargs* so the child process has no visible window.

    Flags are OR-ed (not replaced) so caller-supplied values are
    preserved.  An existing ``startupinfo`` object is augmented
    rather than overwritten.
    """
    if _StartupInfo is None:
        return

    kwargs['creationflags'] = kwargs.get('creationflags', 0) | _CREATE_NO_WINDOW

    startupinfo = kwargs.get('startupinfo') or _StartupInfo()
    startupinfo.dwFlags |= _STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = _SW_HIDE
    kwargs['startupinfo'] = startupinfo


def _patch_popen() -> None:
    _original_init = subprocess.Popen.__init__

    def _patched_init(self: subprocess.Popen, *args: Any, **kwargs: Any) -> None:
        _inject_hidden_flags(kwargs)
        _original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init
