"""Install preview widgets and workers.

Provides a reusable :class:`SetupPreviewWidget` for displaying dry-run
previews and executing porringer setup actions, along with the standalone
:class:`InstallPreviewWindow` used for URI-based manifest installs.

Execution runs on a background ``QThread`` with real-time output routed
to a unified :class:`~synodic_client.application.screen.log_panel.ExecutionLogPanel`.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from porringer.api import API
from porringer.schema import (
    CancellationToken,
    DownloadParameters,
    ProgressEventKind,
    SetupAction,
    SetupActionResult,
    SetupParameters,
    SetupResults,
    SkipReason,
    SubActionProgress,
    SyncStrategy,
)
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen import skip_reason_label
from synodic_client.application.screen.action_card import ActionCardList, action_key
from synodic_client.application.screen.card import CardFrame
from synodic_client.application.screen.log_panel import ExecutionLogPanel
from synodic_client.application.theme import (
    ACTION_CARD_SKELETON_BAR_STYLE,
    CARD_SPACING,
    COMPACT_MARGINS,
    CONTENT_MARGINS,
    HEADER_STYLE,
    INSTALL_PREVIEW_MIN_SIZE,
    METADATA_SKELETON_HEIGHT,
    METADATA_SKELETON_STYLE,
    MUTED_STYLE,
    NO_MARGINS,
)
from synodic_client.resolution import ResolvedConfig, update_user_config

logger = logging.getLogger(__name__)


def normalize_manifest_key(path_or_url: str) -> str:
    """Return a canonical key for a manifest path or URL.

    Local paths are resolved to absolute form so that the same manifest on
    disk always maps to the same config entry regardless of how it was
    referenced (relative, symlinked, etc.).  Remote URLs are returned
    unchanged.
    """
    parsed = urlparse(path_or_url)
    if parsed.scheme in {'http', 'https'}:
        return path_or_url
    try:
        return str(Path(path_or_url).resolve())
    except Exception:
        return path_or_url


# ---------------------------------------------------------------------------
# PreviewPhase / ActionState / PreviewModel — data layer
# ---------------------------------------------------------------------------


class PreviewPhase(enum.Enum):
    """Lifecycle phase of a :class:`SetupPreviewWidget`.

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
    :class:`ActionCard` widgets can be destroyed and recreated
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

    Holds all state that the :class:`SetupPreviewWidget` needs to
    display and that must survive :class:`ActionCard` widget destruction.
    The model is replaced wholesale when a new preview is loaded; during
    an install it is updated in-place and outlives any UI refresh.
    """

    def __init__(self) -> None:
        self.phase: PreviewPhase = PreviewPhase.IDLE
        self.preview: SetupResults | None = None
        self.manifest_path: Path | None = None
        self.manifest_key: str | None = None
        self.project_directory: Path | None = None
        self.plugin_installed: dict[str, bool] = {}
        self.prerelease_overrides: set[str] = set()
        self.action_states: list[ActionState] = []
        self.upgradable_keys: set[tuple[object, ...]] = set()
        self.checked_count: int = 0
        self.completed_count: int = 0
        self.temp_dir: str | None = None

    # -- Computed helpers --------------------------------------------------

    @property
    def actionable_count(self) -> int:
        """Number of needed + upgradable actions."""
        needed = sum(1 for s in self.action_states if s.status == 'Needed')
        upgradable = len(self.upgradable_keys)
        return needed + upgradable

    @property
    def install_enabled(self) -> bool:
        """Whether the install button should be enabled."""
        if self.phase not in {PreviewPhase.READY}:
            return False
        return self.actionable_count > 0 or any(s.action.kind is None for s in self.action_states)

    def action_state_for(self, act: SetupAction) -> ActionState | None:
        """Look up :class:`ActionState` by content key."""
        key = action_key(act)
        for s in self.action_states:
            if action_key(s.action) == key:
                return s
        return None

    def has_same_manifest(self, key: str) -> bool:
        """Return ``True`` if *key* matches the current manifest key."""
        return self.manifest_key is not None and self.manifest_key == normalize_manifest_key(key)


@dataclass(frozen=True, slots=True)
class InstallConfig:
    """Optional execution parameters for :class:`InstallWorker`."""

    project_directory: Path | None = None
    strategy: SyncStrategy = SyncStrategy.MINIMAL
    prerelease_packages: set[str] | None = field(default=None)


class InstallWorker(QThread):
    """Background worker that executes setup actions via porringer.

    Uses the ``execute_stream`` async generator to consume progress events
    and emits per-action progress signals for GUI updates.
    """

    finished = Signal(object)  # SetupResults
    progress = Signal(object, object)  # (SetupAction, SetupActionResult)
    action_started = Signal(object)  # SetupAction
    sub_progress = Signal(object, object)  # (SetupAction, SubActionProgress)
    error = Signal(str)

    def __init__(
        self,
        porringer: API,
        manifest_path: Path,
        cancellation_token: CancellationToken,
        config: InstallConfig | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            manifest_path: Path to the manifest file to execute.
            cancellation_token: Token for cooperative cancellation.
            config: Optional execution parameters (directory, strategy,
                prerelease overrides).
        """
        super().__init__()
        self._porringer = porringer
        self._manifest_path = manifest_path
        self._cancellation_token = cancellation_token
        self._config = config or InstallConfig()

    def run(self) -> None:
        """Execute the setup actions on this thread's event loop."""
        try:
            results = asyncio.run(self._execute())
            self.finished.emit(results)
        except asyncio.CancelledError:
            self.finished.emit(SetupResults(actions=[]))
        except Exception as exc:
            logger.exception('Install execution failed')
            self.error.emit(str(exc))

    async def _execute(self) -> SetupResults:
        """Stream execution events and collect results."""
        params = SetupParameters(
            paths=[self._manifest_path],
            project_directory=self._config.project_directory,
            strategy=self._config.strategy,
            prerelease_packages=self._config.prerelease_packages,
        )
        actions: list[SetupAction] = []
        collected: list[SetupActionResult] = []
        manifest_result: SetupResults | None = None

        async for event in self._porringer.sync.execute_stream(params):
            if self._cancellation_token.is_cancelled:
                raise asyncio.CancelledError

            if event.kind == ProgressEventKind.MANIFEST_LOADED and event.manifest:
                manifest_result = event.manifest
                actions = list(event.manifest.actions)

            if event.kind == ProgressEventKind.ACTION_STARTED and event.action:
                self.action_started.emit(event.action)

            if event.kind == ProgressEventKind.SUB_ACTION_PROGRESS and event.action and event.sub_action:
                self.sub_progress.emit(event.action, event.sub_action)

            if event.kind == ProgressEventKind.ACTION_COMPLETED and event.result:
                collected.append(event.result)
                self.progress.emit(event.action, event.result)

        return SetupResults(
            actions=actions,
            results=collected,
            manifest_path=manifest_result.manifest_path if manifest_result else None,
            metadata=manifest_result.metadata if manifest_result else None,
        )


# ---------------------------------------------------------------------------
# SetupPreviewWidget — reusable preview + install widget
# ---------------------------------------------------------------------------


class SetupPreviewWidget(QWidget):
    """Reusable widget that displays a dry-run preview and executes installs.

    This widget is embedded by both :class:`InstallPreviewWindow` (for
    URI-based installs) and ``ProjectsView`` (for cached-directory
    projects).  It owns the entire preview → install lifecycle including
    the :class:`PreviewWorker` and :class:`InstallWorker` threads.

    State is held in a :class:`PreviewModel` that survives widget
    rebuilds so execution logs are never lost.  The widget manages its
    own phase transitions via :class:`PreviewPhase` — callers only need
    to call :meth:`load`.
    """

    #: Emitted when the user clicks Close (or after a fatal preview error).
    close_requested = Signal()

    #: Emitted after a successful install completes.
    install_finished = Signal(object)  # SetupResults

    #: Emitted when manifest metadata becomes available (name, author, …).
    metadata_ready = Signal(object)  # SetupResults

    #: Emitted whenever the lifecycle phase changes.
    phase_changed = Signal(object)  # PreviewPhase

    def __init__(
        self,
        porringer: API,
        parent: QWidget | None = None,
        *,
        show_close: bool = True,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialize the preview widget.

        Args:
            porringer: The porringer API instance.
            parent: Optional parent widget.
            show_close: Whether to show the Close button.  Set ``False``
                when embedding inside a persistent view (e.g. a tab).
            config: Global configuration for per-manifest pre-release state.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._show_close = show_close
        self._config = config

        self._model = PreviewModel()
        self._runner: QThread | None = None
        self._cancellation_token: CancellationToken | None = None

        # Debounce timer for per-row pre-release checkbox changes
        self._prerelease_debounce = QTimer(self)
        self._prerelease_debounce.setSingleShot(True)
        self._prerelease_debounce.setInterval(500)
        self._prerelease_debounce.timeout.connect(self._flush_prerelease_overrides)

        self._init_ui()

    # --- UI construction ---

    def _init_ui(self) -> None:
        """Build the layout.

        Top section (fixed): metadata card (or skeleton), status/phase label.
        Middle section: single scroll area containing the
        :class:`ActionCardList` and the :class:`ExecutionLogPanel`.
        Bottom section (fixed): button bar.
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*NO_MARGINS)
        outer.setSpacing(CARD_SPACING)

        # --- Metadata skeleton (shown during loading, replaced by real card) ---
        self._metadata_skeleton = self._make_metadata_skeleton()
        outer.addWidget(self._metadata_skeleton)

        # --- Real metadata card (hidden until preview data arrives) ---
        self._init_metadata_card()
        outer.addWidget(self._metadata_card)

        self._status_label = QLabel()
        outer.addWidget(self._status_label)

        # --- Single scroll area for cards + execution log ---
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(CARD_SPACING)

        self._card_list = ActionCardList()
        self._card_list.prerelease_toggled.connect(self._on_prerelease_row_toggled)
        scroll_layout.addWidget(self._card_list)

        self._log_panel = ExecutionLogPanel()
        self._log_panel.hide()
        scroll_layout.addWidget(self._log_panel)

        scroll_layout.addStretch()

        self._scroll_area.setWidget(scroll_content)
        outer.addWidget(self._scroll_area, stretch=1)

        # --- Button bar (fixed at bottom) ---
        button_bar = self._init_button_bar()
        outer.addLayout(button_bar)

    @staticmethod
    def _make_metadata_skeleton() -> QFrame:
        """Create a fixed-height skeleton placeholder for the metadata card."""
        frame = QFrame()
        frame.setObjectName('card')
        frame.setStyleSheet(METADATA_SKELETON_STYLE)
        frame.setFixedHeight(METADATA_SKELETON_HEIGHT)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        bar1 = QFrame()
        bar1.setStyleSheet(ACTION_CARD_SKELETON_BAR_STYLE)
        bar1.setFixedSize(140, 14)
        layout.addWidget(bar1)

        bar2 = QFrame()
        bar2.setStyleSheet(ACTION_CARD_SKELETON_BAR_STYLE)
        bar2.setFixedSize(260, 12)
        layout.addWidget(bar2)

        layout.addStretch()
        frame.hide()
        return frame

    def _init_metadata_card(self) -> None:
        """Create the metadata card (hidden until preview metadata arrives)."""
        self._metadata_card = CardFrame('Project', collapsible=True)
        self._metadata_card.hide()

        self._name_label = QLabel()
        self._name_label.setStyleSheet(HEADER_STYLE)
        self._name_label.hide()
        self._metadata_card.content_layout.addWidget(self._name_label)

        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        self._description_label.hide()
        self._metadata_card.content_layout.addWidget(self._description_label)

        self._meta_label = QLabel()
        self._meta_label.setStyleSheet(MUTED_STYLE)
        self._meta_label.hide()
        self._metadata_card.content_layout.addWidget(self._meta_label)

    def _init_button_bar(self) -> QHBoxLayout:
        """Create the bottom button bar."""
        button_bar = QHBoxLayout()
        button_bar.addStretch()

        self._install_btn = QPushButton('Install')
        self._install_btn.setEnabled(False)
        self._install_btn.clicked.connect(self._on_install)
        button_bar.addWidget(self._install_btn)

        self._close_btn = QPushButton('Close')
        self._close_btn.clicked.connect(self.close_requested.emit)
        if not self._show_close:
            self._close_btn.hide()
        button_bar.addWidget(self._close_btn)

        return button_bar

    # --- Public API ---

    @property
    def model(self) -> PreviewModel:
        """Return the current preview model (read-only access for hosts)."""
        return self._model

    @property
    def phase(self) -> PreviewPhase:
        """Return the current lifecycle phase."""
        return self._model.phase

    @property
    def prerelease_overrides(self) -> set[str] | None:
        """Return the current per-item pre-release overrides.

        Returns ``None`` when no user overrides are active.  The
        returned set contains canonical (lowered) package names.
        """
        return self._model.prerelease_overrides or None

    def set_project_directory(self, path: Path) -> None:
        """Set the project directory used for install execution.

        Args:
            path: Working directory for project sync actions.
        """
        self._model.project_directory = path

    def load(
        self,
        path_or_url: str,
        *,
        project_directory: Path | None = None,
        detect_updates: bool = True,
    ) -> None:
        """Load a manifest preview, or skip if the same manifest is already showing results.

        If the widget is in :attr:`PreviewPhase.DONE` and *path_or_url*
        matches the current manifest key, the load is silently skipped
        so that execution logs remain visible.  Otherwise the widget
        resets and starts a new :class:`PreviewWorker`.

        Args:
            path_or_url: Manifest path or URL.
            project_directory: Working directory for project sync actions.
            detect_updates: Query package indices for newer versions.
        """
        key = normalize_manifest_key(path_or_url)

        # Preserve post-install results when re-selecting the same manifest
        if self._model.phase == PreviewPhase.DONE and self._model.has_same_manifest(key):
            return

        self._stop_preview()

        # Build a fresh model, carrying over config-based state
        self._model = PreviewModel()
        self._model.manifest_key = key
        if project_directory is not None:
            self._model.project_directory = project_directory

        # Load persisted prerelease overrides from config
        if self._config is not None and self._config.prerelease_packages:
            self._model.prerelease_overrides = set(
                self._config.prerelease_packages.get(key, []),
            )

        self._set_phase(PreviewPhase.LOADING)

        # Validate local paths before spawning the worker
        local = resolve_local_path(path_or_url)
        if local is not None:
            if not local.exists():
                self._show_error_inline(f'Path not found: {local}')
                return
            if not self._porringer.sync.has_manifest(local):
                self._show_error_inline(f'No manifest found at: {local}')
                return

        overrides = self._model.prerelease_overrides or None

        preview_worker = PreviewWorker(
            self._porringer,
            path_or_url,
            project_directory=self._model.project_directory,
            detect_updates=detect_updates,
            prerelease_packages=overrides,
        )
        preview_worker.manifest_parsed.connect(self._on_manifest_parsed)
        preview_worker.plugins_queried.connect(self._on_plugins_queried)
        preview_worker.preview_ready.connect(self._on_preview_resolved)
        preview_worker.action_checked.connect(self._on_action_checked)
        preview_worker.finished.connect(self._on_preview_finished)
        preview_worker.error.connect(self._on_preview_error)

        self._runner = preview_worker
        self._runner.start()

    def reset(self) -> None:
        """Clear all state and UI for a fresh preview.

        Callers should prefer :meth:`load` which handles resets
        internally.  This method is provided for explicit teardown when
        the widget is being repurposed (e.g. tab destruction).
        """
        self._stop_preview()
        self._model = PreviewModel()
        self._prerelease_debounce.stop()

        self._card_list.clear()
        self._name_label.hide()
        self._description_label.hide()
        self._meta_label.hide()
        self._metadata_card.hide()
        self._metadata_skeleton.hide()
        self._status_label.setText('')
        self._status_label.setStyleSheet('')
        self._install_btn.setEnabled(False)
        self._log_panel.clear()
        self._log_panel.hide()

    def show_not_found(self, message: str) -> None:
        """Display a muted 'not found' message in the status label.

        Used by callers that want to report a missing directory or manifest
        without popping a modal dialog.

        Args:
            message: The human-readable error or not-found description.
        """
        self._status_label.setText(message)
        self._status_label.setStyleSheet(MUTED_STYLE)

    # --- Phase management ---

    def _set_phase(self, phase: PreviewPhase) -> None:
        """Transition to *phase* and update the UI accordingly."""
        self._model.phase = phase
        self.phase_changed.emit(phase)

        if phase == PreviewPhase.LOADING:
            self._card_list.clear()
            self._name_label.hide()
            self._description_label.hide()
            self._meta_label.hide()
            self._metadata_card.hide()
            self._metadata_skeleton.show()
            self._card_list.show_skeletons(3)
            self._status_label.setText('Downloading manifest\u2026')
            self._status_label.setStyleSheet(MUTED_STYLE)
            self._install_btn.setEnabled(False)
            self._log_panel.clear()
            self._log_panel.hide()
        elif phase == PreviewPhase.ERROR:
            self._metadata_skeleton.hide()
            self._install_btn.setEnabled(False)

    def _show_error_inline(self, message: str) -> None:
        """Display a muted error and transition to ERROR phase."""
        self._set_phase(PreviewPhase.ERROR)
        self._card_list.clear()
        self._status_label.setText(message)
        self._status_label.setStyleSheet(MUTED_STYLE)

    # --- Per-item pre-release overrides ---

    def _on_prerelease_row_toggled(self, package_name: str, checked: bool) -> None:
        """Handle a per-row pre-release checkbox toggle."""
        key = package_name.lower()
        if checked:
            self._model.prerelease_overrides.add(key)
        else:
            self._model.prerelease_overrides.discard(key)
        self._prerelease_debounce.start()

    def _flush_prerelease_overrides(self) -> None:
        """Persist overrides to config.

        During :attr:`PreviewPhase.READY` this also triggers an
        internal reload so the preview reflects the new setting.
        During :attr:`PreviewPhase.INSTALLING` or
        :attr:`PreviewPhase.DONE` the config is saved but no reload
        occurs — execution logs are preserved.
        """
        if self._config is None or self._model.manifest_key is None:
            return

        pkgs = dict(self._config.prerelease_packages or {})
        if self._model.prerelease_overrides:
            pkgs[self._model.manifest_key] = sorted(self._model.prerelease_overrides)
        else:
            pkgs.pop(self._model.manifest_key, None)

        new_value = pkgs if pkgs else None
        self._config = update_user_config(prerelease_packages=new_value)
        logger.info(
            'Pre-release overrides for %s: %s',
            self._model.manifest_key,
            self._model.prerelease_overrides,
        )

        if self._model.phase == PreviewPhase.READY:
            # Re-run the preview with updated overrides
            self.load(
                self._model.manifest_key,
                project_directory=self._model.project_directory,
            )

    # --- Internal worker management ---

    def _stop_preview(self) -> None:
        """Wait for any running worker to finish before starting a new one."""
        self._prerelease_debounce.stop()
        if self._runner is not None and self._runner.isRunning():
            self._runner.quit()
            self._runner.wait()
            self._runner = None

    # --- Preview callbacks (wired by load()) ---

    def _on_manifest_parsed(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle the fast MANIFEST_PARSED event — show cards immediately."""
        self._model.temp_dir = temp_dir_path

        if preview.metadata:
            self.metadata_ready.emit(preview)

        self._on_preview_ready(preview, manifest_path, temp_dir_path)

    def _on_plugins_queried(self, mapping: dict[str, bool]) -> None:
        """Store plugin presence data for annotating the action cards."""
        self._model.plugin_installed = mapping

    def _on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle a successful preview — populate action cards."""
        logger.info('Preview ready: %d action(s) from %s', len(preview.actions), manifest_path)
        m = self._model
        m.preview = preview
        m.manifest_path = Path(manifest_path)
        m.temp_dir = temp_dir_path

        # Infer project directory from manifest result when available
        if preview.root_directory and m.project_directory is None:
            m.project_directory = preview.root_directory

        self._status_label.setStyleSheet('')
        self._metadata_skeleton.hide()

        self._show_metadata(preview)

        if preview.metadata:
            self.metadata_ready.emit(preview)

        if not preview.actions:
            self._card_list.clear()
            self._status_label.setText('No actions to perform — the manifest is empty.')
            self._set_phase(PreviewPhase.READY)
            return

        # Build action states
        m.action_states = [ActionState(action=a) for a in preview.actions]
        m.checked_count = 0

        total = len(preview.actions)
        self._status_label.setText(f'{total} action(s) \u2014 checking status\u2026')
        self._set_phase(PreviewPhase.PREVIEWING)

        self._card_list.populate(
            preview.actions,
            plugin_installed=m.plugin_installed,
            prerelease_overrides=m.prerelease_overrides,
        )

        # Mark installer-missing actions in the model
        for state in m.action_states:
            action = state.action
            installer_missing = (
                action.installer is not None
                and action.installer in m.plugin_installed
                and not m.plugin_installed[action.installer]
            )
            if installer_missing:
                state.status = 'Not installed'

        self._install_btn.setEnabled(True)

    def _on_preview_resolved(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle the fully-resolved preview (CLI commands populated).

        Called after ``MANIFEST_LOADED`` — cards are already visible
        from the earlier ``_on_manifest_parsed`` handler.  This only
        updates CLI command text and the temp-dir reference.
        """
        if self._model.preview is None:
            return

        self._model.temp_dir = temp_dir_path

        if preview.metadata:
            self.metadata_ready.emit(preview)

        for action in preview.actions:
            if action.cli_command:
                card = self._card_list.get_card(action)
                if card is not None:
                    card.update_command(action)

    def _on_action_checked(self, row: int, result: SetupActionResult) -> None:
        """Update the model and action card with a dry-run result."""
        m = self._model
        if result.skipped and result.skip_reason == SkipReason.UPDATE_AVAILABLE:
            label = skip_reason_label(result.skip_reason)
            if 0 <= row < len(m.action_states):
                m.upgradable_keys.add(action_key(m.action_states[row].action))
        elif result.skipped:
            label = skip_reason_label(result.skip_reason)
        elif not result.success:
            label = 'Failed'
        else:
            label = 'Needed'

        if 0 <= row < len(m.action_states):
            m.action_states[row].status = label

        # Update the card widget
        if m.preview and 0 <= row < len(m.preview.actions):
            action = m.preview.actions[row]
            card = self._card_list.get_card(action)
            if card is not None:
                card.set_check_result(result)

        # Update phase text
        m.checked_count += 1
        total = len(m.action_states)
        self._status_label.setText(
            f'{total} action(s) \u2014 checking status ({m.checked_count}/{total})\u2026',
        )

    def _on_preview_finished(self) -> None:
        """Finalize the preview after the dry-run check completes."""
        m = self._model
        if not m.action_states:
            return

        self._card_list.finalize_all_checking()

        for state in m.action_states:
            if state.status == 'Checking\u2026':
                state.status = 'Needed'

        # Compute summary
        total = len(m.action_states)
        needed = sum(1 for s in m.action_states if s.status == 'Needed')
        upgradable = len(m.upgradable_keys)
        unavailable = sum(1 for s in m.action_states if s.status == 'Not installed')
        failed = sum(1 for s in m.action_states if s.status == 'Failed')
        satisfied = total - needed - upgradable - unavailable - failed

        parts: list[str] = []
        if needed:
            parts.append(f'{needed} needed')
        if upgradable:
            parts.append(f'{upgradable} upgradable')
        if satisfied:
            parts.append(f'{satisfied} already satisfied')
        if unavailable:
            parts.append(f'{unavailable} unavailable (plugin not installed)')
        if failed:
            parts.append(f'{failed} failed')

        actionable = needed + upgradable
        if actionable == 0 and unavailable == 0 and failed == 0:
            self._status_label.setText(f'{total} action(s) \u2014 all already satisfied.')
            self._install_btn.setEnabled(False)
        else:
            self._status_label.setText(f'{total} action(s): {", ".join(parts)}.')

        self._set_phase(PreviewPhase.READY)

        logger.info(
            'Preview complete: %d total, %d needed, %d upgradable, %d satisfied, %d unavailable, %d failed',
            total,
            needed,
            upgradable,
            satisfied,
            unavailable,
            failed,
        )

    def _on_preview_error(self, message: str) -> None:
        """Handle a preview error."""
        logger.error('Preview failed: %s', message)
        self._set_phase(PreviewPhase.ERROR)
        self._metadata_skeleton.hide()
        self._card_list.clear()
        self._status_label.setText('')
        QMessageBox.critical(self, 'Preview Failed', message)
        self.close_requested.emit()

    # --- Metadata ---

    def _show_metadata(self, preview: SetupResults) -> None:
        """Display manifest metadata labels if available."""
        metadata = preview.metadata
        if not metadata:
            return

        has_content = False
        if metadata.name:
            self._name_label.setText(metadata.name)
            self._name_label.show()
            has_content = True
        if metadata.description:
            self._description_label.setText(metadata.description)
            self._description_label.show()
            has_content = True

        meta_parts: list[str] = []
        if metadata.author:
            meta_parts.append(f'Author: {metadata.author}')
        if metadata.url:
            meta_parts.append(f'URL: {metadata.url}')
        if meta_parts:
            self._meta_label.setText('  |  '.join(meta_parts))
            self._meta_label.show()
            has_content = True

        if has_content:
            self._metadata_card.show()

    # --- Install execution ---

    def _on_install(self) -> None:
        """Handle the Install button click."""
        m = self._model
        if m.manifest_path is None:
            return

        self._prerelease_debounce.stop()
        self._set_phase(PreviewPhase.INSTALLING)
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        m.completed_count = 0

        self._cancellation_token = CancellationToken()

        self._status_label.setText('Installing\u2026')

        # Show the unified execution log panel
        self._log_panel.clear()
        self._log_panel.show()

        # Choose LATEST strategy when there are upgradable actions so
        # porringer actually upgrades the already-installed packages.
        strategy = SyncStrategy.LATEST if m.upgradable_keys else SyncStrategy.MINIMAL

        # Worker thread
        worker = InstallWorker(
            self._porringer,
            m.manifest_path,
            self._cancellation_token,
            InstallConfig(
                project_directory=m.project_directory,
                strategy=strategy,
                prerelease_packages=m.prerelease_overrides or None,
            ),
        )
        worker.action_started.connect(self._on_action_started)
        worker.sub_progress.connect(self._on_sub_progress)
        worker.progress.connect(self._on_action_progress)
        worker.finished.connect(self._on_install_finished)
        worker.error.connect(self._on_install_error)

        self._runner = worker
        self._runner.start()

    def _on_action_started(self, action: SetupAction) -> None:
        """Handle an action starting execution — update card badge and add a log section."""
        card = self._card_list.get_card(action)
        if card is not None:
            card.set_executing()

        section = self._log_panel.add_section(action)
        self._scroll_area.ensureWidgetVisible(section)

    def _on_sub_progress(self, action: SetupAction, progress: SubActionProgress) -> None:
        """Handle a sub-action progress event — route output to the log panel and model."""
        # Store in model so logs survive widget rebuilds
        state = self._model.action_state_for(action)
        if state is not None:
            if progress.output is not None:
                state.log_lines.append((progress.output, progress.stream))
            elif progress.message is not None:
                state.log_lines.append((progress.message, None))

        self._log_panel.on_sub_progress(action, progress)

        # Auto-scroll the single scroll area to the bottom
        scrollbar = self._scroll_area.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def _on_action_progress(self, action: SetupAction, result: SetupActionResult) -> None:
        """Handle a single action completion from the worker."""
        m = self._model
        m.completed_count += 1

        card = self._card_list.get_card(action)
        if card is not None:
            card.set_result(result)

        self._log_panel.on_action_completed(action, result)

        total = len(m.action_states)
        self._status_label.setText(f'Installing\u2026 ({m.completed_count}/{total})')

    def _on_cancel(self) -> None:
        """Handle cancel request."""
        if self._cancellation_token:
            self._cancellation_token.cancel()

    def _on_install_finished(self, results: SetupResults) -> None:
        """Handle install completion."""
        self._set_phase(PreviewPhase.DONE)

        succeeded = sum(1 for r in results.results if r.success and not r.skipped)
        skipped = sum(1 for r in results.results if r.skipped)
        failed = sum(1 for r in results.results if not r.success)

        parts = []
        if succeeded:
            parts.append(f'{succeeded} succeeded')
        if skipped:
            parts.append(f'{skipped} skipped')
        if failed:
            parts.append(f'{failed} failed')

        summary = ', '.join(parts) if parts else 'No actions executed.'
        self._status_label.setText(f'Done \u2014 {summary}')
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        self.install_finished.emit(results)

    def _on_install_error(self, message: str) -> None:
        """Handle install error."""
        self._set_phase(PreviewPhase.ERROR)
        self._status_label.setText(f'Install failed: {message}')
        self._install_btn.setEnabled(True)
        self._close_btn.setEnabled(True)


# ---------------------------------------------------------------------------
# InstallPreviewWindow — standalone URI-based install window
# ---------------------------------------------------------------------------


class InstallPreviewWindow(QMainWindow):
    """Standalone window that previews and executes a URI-based manifest install.

    A thin shell around :class:`SetupPreviewWidget`.  The widget owns the
    full preview → install lifecycle; this window only provides the
    source-card UI and project-directory field.
    """

    def __init__(
        self,
        porringer: API,
        manifest_url: str,
        parent: QWidget | None = None,
        *,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialize the install preview window.

        Args:
            porringer: The porringer API instance.
            manifest_url: The URL of the manifest to install.
            parent: Optional parent widget.
            config: Resolved configuration for per-manifest pre-release
                state and update detection flags.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._manifest_url = manifest_url
        self._config = config

        # Default project directory to the current working directory
        self._project_directory: Path = Path.cwd()

        self.setWindowTitle('Install Preview')
        self.setMinimumSize(*INSTALL_PREVIEW_MIN_SIZE)

        self._init_ui()

    def _init_ui(self) -> None:
        """Build the UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(*CONTENT_MARGINS)
        layout.setSpacing(CARD_SPACING)

        # Source card — manifest URL + project directory
        source_card = CardFrame('Source')

        self._url_label = QLabel()
        self._url_label.setWordWrap(True)
        source_card.content_layout.addWidget(self._url_label)
        source_card.content_layout.addLayout(self._init_project_dir_row())

        layout.addWidget(source_card)

        # Shared preview widget — owns the full lifecycle
        self._preview_widget = SetupPreviewWidget(self._porringer, self, config=self._config)
        self._preview_widget.close_requested.connect(self.close)
        self._preview_widget.metadata_ready.connect(self._on_metadata_ready)
        self._preview_widget.set_project_directory(self._project_directory)
        layout.addWidget(self._preview_widget)

    def _init_project_dir_row(self) -> QHBoxLayout:
        """Create the project directory input row."""
        row = QHBoxLayout()
        row.setContentsMargins(*COMPACT_MARGINS)

        label = QLabel('Project path:')
        row.addWidget(label)

        self._project_dir_field = QLineEdit(str(self._project_directory))
        self._project_dir_field.setToolTip('Working directory for project sync and post-sync commands')
        self._project_dir_field.textChanged.connect(self._on_project_dir_changed)
        row.addWidget(self._project_dir_field)

        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(self._on_browse_project_dir)
        row.addWidget(browse_btn)

        return row

    def _on_project_dir_changed(self, text: str) -> None:
        """Update the project directory from the text field."""
        self._project_directory = Path(text)
        self._preview_widget.set_project_directory(self._project_directory)

    def _on_browse_project_dir(self) -> None:
        """Open a directory picker for the project path."""
        chosen = QFileDialog.getExistingDirectory(
            self,
            'Select Project Directory',
            str(self._project_directory),
        )
        if chosen:
            self._project_directory = Path(chosen)
            self._project_dir_field.setText(chosen)

    # --- Lifecycle ---

    def showEvent(self, event: Any) -> None:
        """Log when the window becomes visible."""
        super().showEvent(event)
        logger.info('Install preview window shown (visible=%s)', self.isVisible())

    def closeEvent(self, event: Any) -> None:
        """Clean up the temp directory when the window is closed."""
        logger.info('Install preview window closing')
        temp = self._preview_widget.model.temp_dir
        if temp:
            _safe_rmtree(temp)
        super().closeEvent(event)

    # --- Public API ---

    def start(self) -> None:
        """Download the manifest and populate the preview.

        Call this after ``show()`` to begin the download → preview flow.
        """
        logger.info('Starting install preview for: %s', self._manifest_url)
        self._url_label.setText(f'<b>Manifest:</b> {self._manifest_url}')

        detect = self._config.detect_updates if self._config else True
        self._preview_widget.load(
            self._manifest_url,
            project_directory=self._project_directory,
            detect_updates=detect,
        )

    # --- Callbacks ---

    def _on_metadata_ready(self, preview: object) -> None:
        """Update the window title when metadata arrives."""
        if hasattr(preview, 'metadata') and preview.metadata and preview.metadata.name:
            self.setWindowTitle(f'Install Preview \u2014 {preview.metadata.name}')


class PreviewWorker(QThread):
    """Background worker that downloads a manifest and performs a dry-run.

    Combines two stages into a single background pipeline:

    1. Download the manifest (if remote).
    2. Run ``execute_stream`` with ``dry_run=True`` to stream events.

    The worker emits signals in phases:

    * ``manifest_parsed`` — emitted as soon as the JSON is loaded,
      before plugin discovery.  GUI clients can populate cards
      immediately from this.
    * ``plugins_queried`` — emitted after porringer discovers plugins,
      carrying plugin name → installed mapping.
    * ``preview_ready`` — emitted once CLI commands are resolved.
    * ``action_checked`` — emitted per-action as dry-run results
      stream in (may arrive out of order due to parallel checks).
    """

    manifest_parsed = Signal(object, str, str)  # (SetupResults, manifest_path, temp_dir_path) — fast preview
    preview_ready = Signal(object, str, str)  # (SetupResults, manifest_path, temp_dir_path) — fully resolved
    action_checked = Signal(int, object)  # (row_index, SetupActionResult)
    plugins_queried = Signal(object)  # dict[str, bool] — plugin name → installed
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        porringer: API,
        url: str,
        *,
        project_directory: Path | None = None,
        detect_updates: bool = True,
        prerelease_packages: set[str] | None = None,
    ) -> None:
        """Initialize the preview worker.

        Args:
            porringer: The porringer API instance.
            url: Manifest URL or local path.
            project_directory: Working directory for project sync actions.
            detect_updates: Query package indices for newer versions.
            prerelease_packages: Package names whose ``include_prereleases``
                flag should be forced to ``True``, overriding the manifest
                default.
        """
        super().__init__()
        self._porringer = porringer
        self._url = url
        self._project_directory = project_directory
        self._detect_updates = detect_updates
        self._prerelease_packages = prerelease_packages

    def run(self) -> None:
        """Download the manifest and perform a dry-run to check status."""
        logger.info('PreviewWorker starting for: %s', self._url)
        temp_dir = None
        try:
            local_path = resolve_local_path(self._url)

            if local_path is not None:
                if not local_path.exists():
                    self.error.emit(f'Manifest not found:\n{local_path}')
                    return
                manifest_path = local_path
            else:
                temp_dir = tempfile.mkdtemp(prefix='synodic_install_')
                dest = Path(temp_dir) / 'porringer.json'

                params = DownloadParameters(url=self._url, destination=dest, timeout=3)
                result = API.download(params)

                if not result.success:
                    _safe_rmtree(temp_dir)
                    self.error.emit(f'Failed to download manifest:\n{result.message}')
                    return

                manifest_path = dest

            # Dry-run: parses manifest, resolves actions, and checks status
            asyncio.run(self._dry_run(manifest_path, temp_dir or ''))

            self.finished.emit()

        except Exception as exc:
            if temp_dir:
                _safe_rmtree(temp_dir)
            logger.exception('Preview failed')
            self.error.emit(str(exc))

    async def _dry_run(self, manifest_path: Path, temp_dir: str) -> None:
        """Stream dry-run events, emitting signals as each phase completes.

        The new event pipeline is:

        1. ``MANIFEST_PARSED`` → emit ``manifest_parsed`` (fast, before discovery)
        2. ``PLUGINS_DISCOVERED`` → emit ``plugins_queried``
        3. ``MANIFEST_LOADED`` → emit ``preview_ready`` (CLI commands populated)
        4. ``ACTION_COMPLETED`` → emit ``action_checked`` (per-action status)

        Falls back to the previous behaviour when the porringer version
        does not emit the newer event kinds (``MANIFEST_PARSED`` /
        ``PLUGINS_DISCOVERED``).
        """
        params = SetupParameters(
            paths=[manifest_path],
            dry_run=True,
            project_directory=self._project_directory,
            detect_updates=self._detect_updates,
            prerelease_packages=self._prerelease_packages,
        )
        action_index: dict[int, int] = {}
        got_parsed = False

        async for event in self._porringer.sync.execute_stream(params):
            if event.kind == ProgressEventKind.MANIFEST_PARSED and event.manifest:
                # Fast path: cards can be shown immediately
                action_index = {id(a): i for i, a in enumerate(event.manifest.actions)}
                self.manifest_parsed.emit(event.manifest, str(manifest_path), temp_dir)
                got_parsed = True

            elif event.kind == ProgressEventKind.PLUGINS_DISCOVERED:
                # Use the plugin availability from porringer's own discovery
                # rather than making a separate plugin.list() call.
                if event.plugin_availability is not None:
                    self.plugins_queried.emit(event.plugin_availability)
                elif event.plugin_names is not None:
                    # Fallback: only names available, assume all installed
                    self.plugins_queried.emit({name: True for name in event.plugin_names})

            elif event.kind == ProgressEventKind.MANIFEST_LOADED and event.manifest:
                # Fully-resolved preview with CLI commands
                if not got_parsed:
                    # Fallback: older porringer without MANIFEST_PARSED
                    action_index = {id(a): i for i, a in enumerate(event.manifest.actions)}
                self.preview_ready.emit(event.manifest, str(manifest_path), temp_dir)

            elif event.kind == ProgressEventKind.ACTION_COMPLETED and event.result and event.action:
                row = action_index.get(id(event.action))
                if row is not None:
                    self.action_checked.emit(row, event.result)


def resolve_local_path(manifest_ref: str) -> Path | None:
    r"""Return a ``Path`` if *manifest_ref* points to a local file, else ``None``.

    Recognised forms:
    * ``file:///C:/path/to/porringer.json``
    * An absolute OS path (``C:\...`` or ``/...``)
    * A relative path that exists on disk
    """
    parsed = urlparse(manifest_ref)

    if parsed.scheme == 'file':
        # file:///C:/Users/... → C:/Users/...
        return Path(url2pathname(parsed.path))

    if parsed.scheme in {'http', 'https'}:
        return None

    # No scheme — treat as a filesystem path
    candidate = Path(manifest_ref)
    if candidate.is_absolute() or candidate.exists():
        return candidate

    return None


def _safe_rmtree(path: str) -> None:
    """Remove a directory tree, ignoring errors."""
    try:
        shutil.rmtree(path)
    except OSError:
        logger.debug('Failed to clean up temp dir: %s', path)
