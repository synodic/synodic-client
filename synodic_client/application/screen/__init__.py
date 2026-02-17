"""The ``synodic_client.application.screen`` package — shared display helpers.

Label mappings and helpers used by both the install module and the
execution log panel live here to avoid circular imports.
"""

from __future__ import annotations

from porringer.schema import SkipReason
from porringer.schema.plugin import PluginKind

ACTION_KIND_LABELS: dict[PluginKind | None, str] = {
    PluginKind.PACKAGE: 'Package',
    PluginKind.TOOL: 'Tool',
    PluginKind.PROJECT: 'Project',
    PluginKind.RUNTIME: 'Runtime',
    PluginKind.SCM: 'SCM',
    None: 'Command',
}

PLUGIN_KIND_GROUP_LABELS: dict[PluginKind, str] = {
    PluginKind.PACKAGE: 'Packages',
    PluginKind.TOOL: 'Tools',
    PluginKind.PROJECT: 'Projects',
    PluginKind.RUNTIME: 'Runtimes',
    PluginKind.SCM: 'Source Control',
}
"""Human-readable group headings for the plugins view.

Unknown kinds fall back to a title-cased version of the enum name so
newly added :class:`PluginKind` values are handled automatically.
"""


def plugin_kind_group_label(kind: PluginKind) -> str:
    """Return the display label for a plugin-kind group header.

    Falls back to a title-cased version of the enum member name when
    *kind* is not in :data:`PLUGIN_KIND_GROUP_LABELS`.
    """
    return PLUGIN_KIND_GROUP_LABELS.get(kind, kind.name.replace('_', ' ').title())


SKIP_REASON_LABELS: dict[SkipReason, str] = {
    SkipReason.ALREADY_INSTALLED: 'Already installed',
    SkipReason.NO_PROJECT_DIRECTORY: 'No project directory',
}


def skip_reason_label(reason: SkipReason | None) -> str:
    """Return a human-readable label for a skip reason."""
    if reason is None:
        return 'Skipped'
    return SKIP_REASON_LABELS.get(reason, reason.name.replace('_', ' ').capitalize())
