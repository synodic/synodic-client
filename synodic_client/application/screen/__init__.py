"""The ``synodic_client.application.screen`` package — shared display helpers.

Label mappings and helpers used by both the install module and the
execution log panel live here to avoid circular imports.
"""

from __future__ import annotations

from porringer.schema import PluginKind, SkipReason

ACTION_KIND_LABELS: dict[PluginKind | None, str] = {
    PluginKind.PACKAGE: 'Package',
    PluginKind.TOOL: 'Tool',
    PluginKind.PROJECT: 'Project',
    PluginKind.RUNTIME: 'Runtime',
    PluginKind.SCM: 'SCM',
    None: 'Command',
}

SKIP_REASON_LABELS: dict[SkipReason, str] = {
    SkipReason.ALREADY_INSTALLED: 'Already installed',
    SkipReason.NO_PROJECT_DIRECTORY: 'No project directory',
}


def skip_reason_label(reason: SkipReason | None) -> str:
    """Return a human-readable label for a skip reason."""
    if reason is None:
        return 'Skipped'
    return SKIP_REASON_LABELS.get(reason, reason.name.replace('_', ' ').capitalize())
