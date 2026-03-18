"""Typed result dataclasses for the operations layer.

Every operation function returns one of these dataclasses.  They are
plain frozen (where practical) dataclasses with no Qt, no I/O, and no
porringer imports so that CLI, GUI, and tests can all consume them
without extra dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from porringer.schema import PluginCapability, SetupAction, SetupActionResult, SetupResults, SkipReason, SyncStrategy
from porringer.schema.plugin import PluginKind

# ---------------------------------------------------------------------------
# Status resolution helpers
# ---------------------------------------------------------------------------

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


def resolve_action_status(result: SetupActionResult, action: SetupAction) -> str:
    """Derive a human-readable status string from a dry-run result.

    This is the single source of truth for mapping porringer's
    :class:`SetupActionResult` to a display label.
    """
    if result.skipped:
        return skip_reason_label(result.skip_reason)
    if not result.success:
        return 'Failed'
    if action.kind is None:
        return 'Pending'
    if action.kind == PluginKind.PROJECT:
        return 'Ready'
    return 'Needed'


_STATUS_BUCKETS: dict[str, str] = {
    'Needed': 'needed',
    'Pending': 'pending',
    'Ready': 'ready',
    'Not installed': 'unavailable',
    'Failed': 'failed',
    'Already installed': 'satisfied',
    'Already latest': 'satisfied',
}


def classify_status(status: str) -> str:
    """Classify a resolved status string into a summary bucket.

    Returns one of ``'needed'``, ``'satisfied'``, ``'pending'``,
    ``'ready'``, ``'unavailable'``, ``'failed'``, or ``'unknown'``.
    Upgradability is determined separately from skip reason, so it
    is not included here.
    """
    bucket = _STATUS_BUCKETS.get(status)
    if bucket is not None:
        return bucket
    if '\u2713' in status:
        return 'satisfied'
    return 'unknown'


# ---------------------------------------------------------------------------
# Install plan computation
# ---------------------------------------------------------------------------

#: Statuses that mean the action is already handled — nothing to install.
_SATISFIED_STATUSES: frozenset[str] = frozenset({'Already installed', 'Already latest'})


@dataclass(frozen=True, slots=True)
class ActionCheckResult:
    """A single action's dry-run result paired with its resolved status.

    Mirrors :class:`PreviewActionChecked` but carries the ``action``
    object directly, making it usable outside the streaming context.
    """

    index: int
    """Original action index (porringer ordering)."""

    action: SetupAction
    """The porringer setup action."""

    result: SetupActionResult
    """Dry-run result for this action."""

    status: str
    """Pre-resolved human-readable status label."""


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """Deterministic, immutable plan computed from dry-run results.

    The single source of truth for what the Install button should do,
    what gets skipped, and whether post-sync commands exist.  Both the
    GUI and CLI consume this dataclass without re-deriving the logic.
    """

    install_indices: tuple[int, ...]
    """Action indices that need execution (``Needed`` / ``Ready``)."""

    satisfied_indices: tuple[int, ...]
    """Action indices already satisfied (``Already installed``/``Already latest``).

    **Display-only** — porringer handles skipping internally.  These
    indices are used for the UI summary (``pre_skipped_count``) and
    ``install_enabled`` determination, not for execution filtering."""

    upgradable_indices: tuple[int, ...]
    """Action indices with updates available — excluded from install."""

    post_sync_indices: tuple[int, ...]
    """Action indices for post-sync commands (``kind is None``)."""

    strategy: SyncStrategy
    """Sync strategy to use for the install."""

    install_enabled: bool
    """Whether there are actions worth running an install for."""

    has_post_sync: bool
    """Whether the manifest contains post-sync commands."""

    summary: str
    """Pre-formatted status summary for the UI."""


def _classify_action(cr: ActionCheckResult) -> tuple[str, str | None]:
    """Return ``(bucket, list_name)`` for a single check result.

    ``list_name`` is ``'install'``, ``'satisfied'``, ``'upgradable'``,
    ``'post_sync'``, or ``None`` (not assigned to an index list).
    ``bucket`` is one of the counter keys used for the summary.
    """
    bucket = classify_status(cr.status)

    if cr.action.kind is None:
        return ('pending' if bucket == 'pending' else 'post_sync_only'), 'post_sync'

    if cr.status == 'Update available':
        return 'upgradable', 'upgradable'
    if bucket == 'satisfied':
        return 'satisfied', 'satisfied'
    if bucket in {'needed', 'ready'}:
        return bucket, 'install'
    if bucket in {'unavailable', 'failed'}:
        return bucket, None
    # Unknown status — include in install to be safe
    return 'needed', 'install'


def compute_install_plan(check_results: list[ActionCheckResult]) -> InstallPlan:
    """Derive an :class:`InstallPlan` from a completed dry-run.

    This is a **pure function** — no I/O, no side effects.  It is the
    single place where "what to do" is decided, consumed identically
    by the GUI and CLI.

    Args:
        check_results: Completed dry-run results for every action.

    Returns:
        An immutable :class:`InstallPlan`.
    """
    lists: dict[str, list[int]] = {
        'install': [],
        'satisfied': [],
        'upgradable': [],
        'post_sync': [],
    }
    counts: dict[str, int] = {
        'needed': 0,
        'satisfied': 0,
        'upgradable': 0,
        'pending': 0,
        'ready': 0,
        'unavailable': 0,
        'failed': 0,
    }

    for cr in check_results:
        bucket, list_name = _classify_action(cr)
        if list_name is not None:
            lists[list_name].append(cr.index)
        if bucket in counts:
            counts[bucket] += 1

    # Build summary text
    total = len(check_results)
    label_map = {
        'needed': 'needed',
        'upgradable': 'upgradable (manage in Tools)',
        'satisfied': 'already satisfied',
        'ready': 'ready',
        'pending': 'pending',
        'unavailable': 'unavailable (plugin not installed)',
        'failed': 'failed',
    }
    parts = [f'{counts[k]} {v}' for k, v in label_map.items() if counts[k]]

    actionable = counts['needed'] + counts['ready']
    if actionable == 0 and counts['unavailable'] == 0 and counts['failed'] == 0:
        summary = f'{total} action(s) \u2014 all already satisfied.'
    else:
        summary = f'{total} action(s): {", ".join(parts)}.'

    return InstallPlan(
        install_indices=tuple(lists['install']),
        satisfied_indices=tuple(lists['satisfied']),
        upgradable_indices=tuple(lists['upgradable']),
        post_sync_indices=tuple(lists['post_sync']),
        strategy=SyncStrategy.MINIMAL,
        install_enabled=actionable > 0,
        has_post_sync=len(lists['post_sync']) > 0,
        summary=summary,
    )


def format_install_summary(
    install_results: list[SetupActionResult] | None = None,
    post_sync_results: list[SetupActionResult] | None = None,
    pre_skipped_count: int = 0,
) -> str:
    """Build a unified completion summary string.

    Pure function that formats the results of install + post-sync phases
    into a single human-readable string.

    Args:
        install_results: Results from the install phase (may be ``None``
            if only post-sync was executed).
        post_sync_results: Results from the post-sync phase (may be
            ``None`` if no post-sync commands exist).
        pre_skipped_count: Number of actions pre-skipped (already
            satisfied, excluded from execution).

    Returns:
        A formatted summary string.
    """
    parts: list[str] = []

    if install_results is not None:
        succeeded = sum(1 for r in install_results if r.success and not r.skipped)
        skipped = sum(1 for r in install_results if r.skipped)
        failed = sum(1 for r in install_results if not r.success)
        if succeeded:
            parts.append(f'{succeeded} succeeded')
        if skipped:
            parts.append(f'{skipped} skipped')
        if failed:
            parts.append(f'{failed} failed')

    if pre_skipped_count:
        parts.append(f'{pre_skipped_count} already satisfied')

    install_summary = ', '.join(parts) if parts else 'No actions executed.'

    if post_sync_results is not None:
        ps_succeeded = sum(1 for r in post_sync_results if r.success and not r.skipped)
        ps_failed = sum(1 for r in post_sync_results if not r.success)
        ps_parts: list[str] = []
        if ps_succeeded:
            ps_parts.append(f'{ps_succeeded} ran')
        if ps_failed:
            ps_parts.append(f'{ps_failed} failed')
        ps_summary = ', '.join(ps_parts) if ps_parts else 'none ran'
        return f'Done \u2014 {install_summary}. Post-sync: {ps_summary}.'

    return f'Done \u2014 {install_summary}'


@dataclass(frozen=True, slots=True)
class PreviewManifestParsed:
    """Fast event emitted once the manifest JSON is parsed."""

    manifest: SetupResults
    manifest_path: str
    temp_dir: str


@dataclass(frozen=True, slots=True)
class PreviewPluginsQueried:
    """Plugin availability discovered."""

    availability: dict[str, bool]
    capabilities: dict[str, frozenset[PluginCapability]]


@dataclass(frozen=True, slots=True)
class PreviewReady:
    """All actions resolved — full manifest loaded."""

    manifest: SetupResults
    manifest_path: str
    temp_dir: str


@dataclass(frozen=True, slots=True)
class PreviewActionChecked:
    """A single action's dry-run result has been resolved."""

    index: int
    result: SetupActionResult
    status: str


PreviewEvent = PreviewManifestParsed | PreviewPluginsQueried | PreviewReady | PreviewActionChecked


# ---------------------------------------------------------------------------
# Project operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    """Summary of a single cached project directory."""

    path: str
    """Filesystem path of the directory."""

    name: str
    """Human-readable label (usually the directory stem)."""

    exists: bool
    """Whether the directory still exists on disk."""

    has_manifest: bool
    """Whether the directory contains a recognised manifest file."""


@dataclass(frozen=True, slots=True)
class ActionInfo:
    """One action from a project manifest preview."""

    description: str
    kind: str | None = None
    status: str = ''
    package: str | None = None
    constraint: str | None = None
    installer: str | None = None


@dataclass(frozen=True, slots=True)
class StatusSummary:
    """Aggregate counts for a project status preview."""

    needed: int = 0
    satisfied: int = 0
    pending: int = 0
    upgradable: int = 0


@dataclass(frozen=True, slots=True)
class ProjectStatus:
    """Full status preview for a single project directory."""

    path: str
    phase: str
    action_count: int = 0
    checked_count: int = 0
    actions: list[ActionInfo] = field(default_factory=list)
    summary: StatusSummary = field(default_factory=StatusSummary)


# ---------------------------------------------------------------------------
# Tool / package operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TagInfo:
    """A project-scoped occurrence tag for a package."""

    project_path: str
    is_transitive: bool = False


@dataclass(frozen=True, slots=True)
class PackageInfo:
    """Display-ready info about a single installed package."""

    name: str
    version: str = ''
    has_update: bool = False
    update_version: str | None = None
    timestamp: str | None = None
    tags: list[TagInfo] = field(default_factory=list)
    is_global: bool = False
    auto_update: bool = False
    host_tool: str = ''


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """A single plugin provider (installer) with its packages."""

    plugin_name: str
    plugin_version: str | None = None
    installed: bool = True
    kind: str = ''
    runtime_tag: str | None = None
    packages: list[PackageInfo] = field(default_factory=list)
    has_updates: bool = False


@dataclass(frozen=True, slots=True)
class ToolSection:
    """A section grouping providers by plugin kind (e.g. Tool, Package)."""

    kind: str
    providers: list[ProviderInfo] = field(default_factory=list)


@dataclass(slots=True)
class UpdateResult:
    """Summary of a tool/package update run."""

    plugin: str = ''
    packages_updated: list[str] = field(default_factory=list)
    packages_failed: list[str] = field(default_factory=list)
    already_latest: list[str] = field(default_factory=list)
    manifests_processed: int = 0
    updated_packages: set[str] = field(default_factory=set)
    version_map: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Mapping of ``package_name → (old_version, new_version)``."""

    @property
    def updated(self) -> int:
        """Number of packages successfully updated."""
        return len(self.packages_updated)

    @property
    def failed(self) -> int:
        """Number of packages that failed to update."""
        return len(self.packages_failed)


# ---------------------------------------------------------------------------
# Install operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Result of a manifest preview (dry-run)."""

    manifest_key: str = ''
    project_name: str = ''
    description: str = ''
    actions: list[ActionInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Self-update operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    """Result of a self-update availability check."""

    available: bool
    current_version: str = ''
    version: str | None = None
    channel: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Result of a self-update download."""

    success: bool
    version: str = ''
    error: str | None = None


# ---------------------------------------------------------------------------
# Config operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfigKeyInfo:
    """Metadata about a single configuration key."""

    name: str
    type_hint: str = ''
    description: str = ''
    current_value: object = None


# ---------------------------------------------------------------------------
# Debug actions registry
# ---------------------------------------------------------------------------

DEBUG_ACTIONS: dict[str, str] = {
    'check_update': 'Trigger a self-update check.',
    'tool_update': 'Run tool/package updates for all plugins.',
    'refresh_data': 'Mark cached data as stale (next refresh re-fetches).',
    'show_main': 'Show and raise the main window.',
    'show_settings': 'Show the settings window.',
    'apply_update': 'Apply a downloaded update and restart.',
    'list_projects': 'List cached project directories with validation status.',
    'add_project': 'Add a directory to the project cache. Arg: <path>',
    'remove_project': 'Remove a directory from the project cache. Arg: <path>',
    'project_status': 'Dump per-action preview status. Arg (optional): <path>',
    'select_project': 'Select a project in the sidebar. Arg: <path>',
}

#: Actions that require a live GUI instance (IPC via ``--live``).
GUI_ONLY_ACTIONS: frozenset[str] = frozenset({
    'check_update',
    'tool_update',
    'refresh_data',
    'show_main',
    'show_settings',
    'apply_update',
    'select_project',
})
