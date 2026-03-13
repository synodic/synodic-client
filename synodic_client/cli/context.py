"""Service context for standalone CLI commands.

Provides lazy initialisation of porringer ``API`` and ``Client`` so that
data commands can run without Qt.  When a running GUI instance is
detected, IPC is preferred for GUI-control commands.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from porringer.api import API

    from synodic_client.client import Client
    from synodic_client.schema import ResolvedConfig


@functools.cache
def get_services() -> tuple[Client, API, ResolvedConfig]:
    """Return ``(Client, API, ResolvedConfig)`` for standalone CLI usage.

    The result is cached so subsequent calls in the same process reuse
    the same instances.
    """
    from synodic_client.operations.bootstrap import init_services

    return init_services()
