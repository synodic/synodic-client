"""Screen-layer data models and enums.

Contains all dataclasses, enums, and plain data classes used by the
install preview, tools view, update banner, and related screen widgets.
Keeping them in a dedicated module avoids circular imports between
widget files.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from porringer.schema import (
    PluginCapability,
    PluginInfo,
    SetupAction,
    SetupActionResult,
    SetupResults,
    SubActionProgress,
    SyncStrategy,
)
from porringer.schema.plugin import RuntimePackageResult

from synodic_client.application.uri import normalize_manifest_key
from synodic_client.operations.schema import InstallPlan

# ---------------------------------------------------------------------------
# Package gathering & display (from screen.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PackageEntry:
    """A single package returned by a gather query.

    Replaces ad-hoc tuples returned by ``_gather_packages`` and
    ``_gather_tool_plugins``.
    """

    name: str
    """Package name (e.g. ``"pdm"``, ``"ruff"``)."""

    project_label: str = ''
    """Human-readable project directory label, or empty for global packages."""

    version: str = ''
    """Installed version string, or empty if unknown."""

    host_tool: str = ''
    """Name of the host package when injected (e.g. ``"pdm"``), otherwise empty."""

    project_path: str = ''
    """Directory path string for project-scoped packages, or empty for global ones."""


@dataclass(slots=True)
class ProjectInstance:
    """A single project-scoped occurrence of a package.

    Represents the package as found in one project venv.  Multiple
    instances may exist when the same package appears in several
    cached projects.
    """

    project_label: str
    """Human-readable project directory label."""

    project_path: str
    """Filesystem path of the project directory."""

    version: str = ''
    """Installed version string in this project."""

    is_transitive: bool = False
    """``True`` when the package is not declared in the project manifest."""


@dataclass(slots=True)
class DisplayPackage:
    """Two-tier view of a package for the ToolsView widget tree.

    Replaces :class:`MergedPackage` with an explicit global/project
    split.  The ``global_version`` indicates whether the package is
    installed in the global environment; ``project_instances`` lists
    each project venv where it was found.
    """

    name: str
    """Package name (e.g. ``"ruff"``)."""

    global_version: str | None = None
    """Version in the global environment, or ``None`` when not global."""

    is_global: bool = False
    """``True`` when the package is installed globally."""

    host_tool: str = ''
    """Host-tool annotation for injected packages."""

    project_instances: list[ProjectInstance] = field(default_factory=list)
    """Project-scoped occurrences of this package."""


@dataclass(slots=True)
class PluginRowData:
    """Bundled display data for constructing a ``PluginRow``.

    Groups the many display parameters into a single object
    to keep the constructor signature concise.
    """

    name: str
    """Package or tool name."""

    project: str = ''
    """Comma-separated project labels, or empty for global / bare rows."""

    version: str = ''
    """Installed version string."""

    plugin_name: str = ''
    """Name of the managing plugin (e.g. ``"pipx"``)."""

    auto_update: bool = False
    """Current per-package auto-update toggle state."""

    show_toggle: bool = False
    """Whether to show the inline *Auto* toggle button."""

    has_update: bool = False
    """Whether an update is available for this package."""

    is_global: bool = False
    """``True`` when the package is globally installed."""

    host_tool: str = ''
    """Host-tool name for injected packages."""

    runtime_tag: str = ''
    """Runtime tag for per-runtime packages (e.g. ``\"3.12\"``)."""

    project_paths: list[str] = field(default_factory=list)
    """Filesystem paths for project-scoped packages."""

    project_instances: list[ProjectInstance] = field(default_factory=list)
    """Project-scoped occurrences of this package, displayed as inline tags."""

    last_updated: str = ''
    """ISO 8601 timestamp of the last successful update, or empty."""


@dataclass(slots=True)
class RefreshData:
    """Internal data bundle returned by ``ToolsView._gather_refresh_data``."""

    plugins: list[PluginInfo]
    """All discovered plugins."""

    packages_map: dict[str, list[PackageEntry]]
    """Mapping of plugin name → gathered packages."""

    manifest_packages: dict[str, set[str]]
    """Mapping of plugin name → manifest-referenced package names."""

    runtime_packages: dict[str, list[RuntimePackageResult]] = field(default_factory=dict)
    """Mapping of plugin name → per-runtime package results (RuntimeConsumer plugins only)."""

    default_runtime_executable: Path | None = None
    """Executable path of the resolved default runtime, if any."""


# ---------------------------------------------------------------------------
# Install preview data models (from install.py)
# ---------------------------------------------------------------------------


class PreviewPhase(enum.Enum):
    """Lifecycle phase of a ``SetupPreviewWidget``.

    The widget transitions through these phases and uses them to decide
    whether certain operations (like reloading the preview or toggling
    buttons) are allowed.  Having an explicit enum replaces the previous
    ``_installing`` boolean flag and status-label-text-based implicit state.
    """

    IDLE = 'idle'
    """No preview loaded."""

    LOADING = 'loading'
    """Skeleton placeholders displayed; preview worker running."""

    PREVIEWING = 'previewing'
    """Cards populated; dry-run status checks in progress."""

    READY = 'ready'
    """Dry-run complete; install button may be enabled."""

    INSTALLING = 'installing'
    """Install worker running."""

    DONE = 'done'
    """Install finished; execution logs visible."""

    ERROR = 'error'
    """Preview or install failed."""


@dataclass
class ActionState:
    """Per-action data that survives widget rebuilds.

    Each entry stores the authoritative execution log so that
    ``ActionCard`` widgets can be destroyed and recreated
    without losing output.
    """

    action: SetupAction
    """The porringer setup action."""

    status: str = 'Checking\u2026'
    """Human-readable dry-run status label."""

    log_lines: list[tuple[str, str | None]] = field(default_factory=list)
    """Accumulated execution log: ``(text, stream)`` pairs."""


class PreviewModel:
    """Data model for a single preview / install session.

    Holds all state that the ``SetupPreviewWidget`` needs to
    display and that must survive ``ActionCard`` widget destruction.
    The model is replaced wholesale when a new preview is loaded; during
    an install it is updated in-place and outlives any UI refresh.
    """

    def __init__(self) -> None:
        """Initialise a blank preview model."""
        self.phase: PreviewPhase = PreviewPhase.IDLE
        self.preview: SetupResults | None = None
        self.manifest_path: Path | None = None
        self.manifest_key: str | None = None
        self.project_directory: Path | None = None
        self.plugin_installed: dict[str, bool] = {}
        self.plugin_capabilities: dict[str, frozenset[PluginCapability]] = {}
        self.prerelease_overrides: set[str] = set()
        self.action_states: list[ActionState] = []
        self._action_state_map: dict[SetupAction, ActionState] = {}
        self._action_state_map_len: int = 0
        self.install_plan: InstallPlan | None = None
        self.checked_count: int = 0
        self.completed_count: int = 0
        self.temp_dir: str | None = None

        # Post-sync tracking (independent from install)
        self.post_sync_completed: bool = False
        self.post_sync_results: list[SetupActionResult] | None = None

    # -- Computed helpers --------------------------------------------------

    def _ensure_action_state_map(self) -> dict[SetupAction, ActionState]:
        """Return the action → state lookup, rebuilding if stale."""
        if len(self.action_states) != self._action_state_map_len:
            self._action_state_map = {s.action: s for s in self.action_states}
            self._action_state_map_len = len(self.action_states)
        return self._action_state_map

    @property
    def install_enabled(self) -> bool:
        """Whether the install button should be enabled.

        Delegates to :attr:`install_plan` when available; falls back
        to ``False`` when no plan has been computed yet.
        """
        if self.phase not in {PreviewPhase.READY}:
            return False
        if self.install_plan is not None:
            return self.install_plan.install_enabled
        return False

    @property
    def has_post_sync(self) -> bool:
        """Whether the manifest has post-sync commands."""
        if self.install_plan is not None:
            return self.install_plan.has_post_sync
        return False

    def action_state_for(self, act: SetupAction) -> ActionState | None:
        """Look up :class:`ActionState` for *act* (O(1) amortized)."""
        return self._ensure_action_state_map().get(act)

    def has_same_manifest(self, key: str) -> bool:
        """Return ``True`` if *key* matches the current manifest key."""
        return self.manifest_key is not None and self.manifest_key == normalize_manifest_key(key)


@dataclass(frozen=True, slots=True)
class InstallConfig:
    """Optional execution parameters for the install worker."""

    project_directory: Path | None = None
    strategy: SyncStrategy = SyncStrategy.MINIMAL
    prerelease_packages: set[str] | None = field(default=None)


@dataclass(frozen=True, slots=True)
class InstallCallbacks:
    """Callbacks for :func:`run_install` progress reporting."""

    on_action_started: Callable[[SetupAction], None] | None = None
    """Called when an action begins execution."""

    on_sub_progress: Callable[[SetupAction, SubActionProgress], None] | None = None
    """Called for sub-action progress events."""

    on_progress: Callable[[SetupAction, SetupActionResult], None] | None = None
    """Called when a single action completes."""


@dataclass(frozen=True, slots=True)
class PreviewConfig:
    """Optional execution parameters for :func:`run_preview`."""

    project_directory: Path | None = None
    prerelease_packages: set[str] | None = None


@dataclass(frozen=True, slots=True)
class UpdateTarget:
    """Identifies the scope of a manual tool update.

    Passed to the shared completion handler so it can clear the correct
    updating state and derive timestamp keys.  ``None`` (the default in
    the handler) means the update was periodic / automatic.

    When *package* is empty the update targeted an entire plugin;
    otherwise it targeted one specific package within the plugin.
    *plugin* always carries the signal key (possibly composite
    ``"plugin:tag"``).
    """

    plugin: str
    """Signal key for the plugin (may be composite ``"name:tag"``)."""

    package: str = ''
    """Package name, or empty when the whole plugin was updated."""
