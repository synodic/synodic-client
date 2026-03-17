"""Async background workers for the Synodic Client application.

.. deprecated::
    All worker functions have been moved to the operations layer
    (``synodic_client.operations.tool`` and
    ``synodic_client.operations.update``).  This module is kept for
    backward compatibility but will be removed in a future release.
"""

from synodic_client.operations.tool import update_all_tools as run_tool_updates
from synodic_client.operations.tool import update_runtime_plugin as run_runtime_package_updates
from synodic_client.operations.update import check_self_update as check_for_update
from synodic_client.operations.update import download_self_update as download_update

__all__ = [
    'check_for_update',
    'download_update',
    'run_runtime_package_updates',
    'run_tool_updates',
]
