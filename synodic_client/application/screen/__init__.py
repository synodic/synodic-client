"""The ``synodic_client.application.screen`` package — shared display helpers.

Label mappings and helpers used by both the install module and the
execution log panel live here to avoid circular imports.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from porringer.schema import SetupAction, SetupActionResult
from porringer.schema.plugin import PluginKind

from synodic_client.operations.schema import (
    SKIP_REASON_LABELS as SKIP_REASON_LABELS,
)
from synodic_client.operations.schema import (
    resolve_action_status as resolve_action_status,
)
from synodic_client.operations.schema import (
    skip_reason_label as skip_reason_label,
)

_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24

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


def format_cli_command(
    action: SetupAction,
    *,
    result: SetupActionResult | None = None,
    suppress_description: bool = False,
) -> str:
    """Return a human-readable CLI command string for *action*.

    Prefers ``result.cli_command`` (populated after dry-run), falls
    back to ``action.command``, then synthesises an
    ``installer install <package>`` string for package actions, and
    finally returns the action description as a last resort.

    When *suppress_description* is ``True`` the final description
    fallback returns an empty string instead.
    """
    if result is not None and result.cli_command:
        return ' '.join(result.cli_command)
    if action.command:
        return ' '.join(action.command)
    if action.kind == PluginKind.PACKAGE and action.package:
        return f'{action.installer or "pip"} install {action.package}'
    return '' if suppress_description else action.description


def _format_relative_time(iso_timestamp: str) -> str:
    """Format an ISO 8601 timestamp as a human-readable relative time.

    Returns strings like ``'just now'``, ``'5m ago'``, ``'2h ago'``,
    ``'3d ago'``.  Returns an empty string if the timestamp cannot be
    parsed.
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - dt
        seconds = max(int(delta.total_seconds()), 0)
        if seconds < _SECONDS_PER_MINUTE:
            return 'just now'
        minutes = seconds // _SECONDS_PER_MINUTE
        if minutes < _MINUTES_PER_HOUR:
            return f'{minutes}m ago'
        hours = minutes // _MINUTES_PER_HOUR
        if hours < _HOURS_PER_DAY:
            return f'{hours}h ago'
        days = hours // _HOURS_PER_DAY
        return f'{days}d ago'
    except ValueError, TypeError:
        return ''


def is_version_specifier(value: str) -> bool:
    """Return whether *value* looks like a PEP 440 version specifier.

    Returns ``True`` when the string contains comparison operators
    (``>=``, ``<=``, ``!=``, ``~=``, ``==``, ``>``, ``<``) or
    caret/tilde shorthand (``^``, ``~`` not followed by ``=``).
    This distinguishes constraint strings like ``">=0.8.0"`` from
    resolved version numbers like ``"0.9.1"``.
    """
    return bool(re.search(r'[><=!~^]', value))
