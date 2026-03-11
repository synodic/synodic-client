"""Shared startup preamble for frozen and CLI entry points.

Encapsulates the one-time initialisation that both
:mod:`synodic_client.application.bootstrap` (PyInstaller) and
:mod:`synodic_client.application.qt` (CLI / dev-script) need to
perform before the GUI event loop starts:

1. Seed user config from the build config (one-time propagation).
2. Register the ``synodic://`` URI protocol handler.
3. Synchronise the Windows auto-startup registry entry with the
   persisted ``auto_start`` preference.

Heavy dependencies (PySide6, porringer) are **not** imported here so
that the bootstrap path can call this before loading them.
"""

import logging
import sys

from synodic_client.protocol import register_protocol
from synodic_client.resolution import resolve_config, seed_user_config_from_build
from synodic_client.startup import sync_startup

logger = logging.getLogger(__name__)


class _PreambleState:
    """Module-level mutable state (avoids ``global`` statements)."""

    done: bool = False


def run_startup_preamble(exe_path: str | None = None) -> None:
    """Run the shared startup preamble for non-dev-mode launches.

    Both the frozen entry point
    (:mod:`~synodic_client.application.bootstrap`) and the CLI entry
    point (:func:`~synodic_client.application.qt.application`) call
    this unconditionally.  An internal guard ensures the work only
    executes once per process.

    Args:
        exe_path: Absolute path to the application executable.  Defaults
            to ``sys.executable`` when not supplied.
    """
    if _PreambleState.done:
        return
    _PreambleState.done = True

    if exe_path is None:
        exe_path = sys.executable

    # Seed user config from the build config (one-time propagation).
    seed_user_config_from_build()

    frozen = getattr(sys, 'frozen', False)

    if frozen:
        register_protocol(exe_path)

    config = resolve_config()
    sync_startup(exe_path, auto_start=config.auto_start)

    logger.info('Startup preamble complete (auto_start=%s, frozen=%s)', config.auto_start, frozen)
