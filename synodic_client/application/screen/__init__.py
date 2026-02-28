"""The ``synodic_client.application.screen`` package — shared display helpers.

Label mappings and helpers used by both the install module and the
execution log panel live here to avoid circular imports.
"""

from __future__ import annotations

from porringer.schema import SetupAction, SkipReason
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
    SkipReason.NOT_INSTALLED: 'Not installed',
    SkipReason.ALREADY_LATEST: 'Already latest',
    SkipReason.NO_PROJECT_DIRECTORY: 'No project directory',
    SkipReason.UPDATE_AVAILABLE: 'Update available',
}


def skip_reason_label(reason: SkipReason | None) -> str:
    """Return a human-readable label for a skip reason."""
    if reason is None:
        return 'Skipped'
    return SKIP_REASON_LABELS.get(reason, reason.name.replace('_', ' ').capitalize())


def format_cli_command(action: SetupAction) -> str:
    """Return a human-readable CLI command string for *action*.

    Prefers ``cli_command``, falls back to ``command``, then synthesises
    an ``installer install <package>`` string for package actions, and
    finally returns the action description as a last resort.
    """
    if parts := (action.cli_command or action.command):
        return ' '.join(parts)
    if action.kind == PluginKind.PACKAGE and action.package:
        return f'{action.installer or "pip"} install {action.package}'
    return action.description
