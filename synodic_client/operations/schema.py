"""Typed result dataclasses for the operations layer.

Every operation function returns one of these dataclasses.  They are
plain frozen (where practical) dataclasses with no Qt, no I/O, and no
porringer imports so that CLI, GUI, and tests can all consume them
without extra dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from porringer.schema import PluginCapability, SetupAction, SetupActionResult, SetupResults, SkipReason
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


# ---------------------------------------------------------------------------
# Preview stream events
# ---------------------------------------------------------------------------


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
