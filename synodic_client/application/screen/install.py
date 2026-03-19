"""Install preview widgets and workers.

Provides a reusable :class:`SetupPreviewWidget` for displaying dry-run
previews and executing porringer setup actions, along with the standalone
:class:`InstallPreviewWindow` used for URI-based manifest installs.

Preview and install operations run as ``asyncio`` coroutines on the
qasync main-thread event loop, with callbacks delivering real-time
output to the :class:`~synodic_client.application.screen.log_panel.ExecutionLogPanel`.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path
from typing import Any

from porringer.api import API
from porringer.backend.command.core.discovery import DiscoveredPlugins
from porringer.schema import (
    SetupAction,
    SetupActionResult,
    SetupResults,
    SubActionProgress,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QShowEvent
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

from synodic_client.application.package_state import PackageStateStore
from synodic_client.application.screen.action_card import ActionCardList
from synodic_client.application.screen.card import CardFrame
from synodic_client.application.screen.install_workers import run_install, run_post_sync, run_preview
from synodic_client.application.screen.log_panel import ExecutionLogPanel
from synodic_client.application.screen.schema import (
    ActionState,
    InstallCallbacks,
    InstallConfig,
    PreviewConfig,
    PreviewModel,
    PreviewPhase,
)
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
from synodic_client.application.uri import normalize_manifest_key, resolve_local_path, safe_rmtree
from synodic_client.resolution import ResolvedConfig, update_user_config

logger = logging.getLogger(__name__)


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

    #: Emitted with ``(installer, package_name)`` when the user clicks an
    #: 'Update available' card to navigate to the Tools view.
    navigate_to_tool_requested = Signal(str, str)

    def __init__(
        self,
        porringer: API,
        parent: QWidget | None = None,
        *,
        show_close: bool = True,
        config: ResolvedConfig | None = None,
        package_store: PackageStateStore | None = None,
    ) -> None:
        """Initialize the preview widget.

        Args:
            porringer: The porringer API instance.
            parent: Optional parent widget.
            show_close: Whether to show the Close button.  Set ``False``
                when embedding inside a persistent view (e.g. a tab).
            config: Global configuration for per-manifest pre-release state.
            package_store: Shared package update state registry.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._show_close = show_close
        self._config = config
        self._package_store = package_store
        self._discovered_plugins: DiscoveredPlugins | None = None

        self._model = PreviewModel()
        self._task: asyncio.Task[None] | None = None
        self._install_results: SetupResults | None = None

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
        self._card_list.navigate_to_tool.connect(self.navigate_to_tool_requested.emit)
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

        self._run_commands_btn = QPushButton('Run Commands')
        self._run_commands_btn.setToolTip('Execute post-sync commands from the manifest')
        self._run_commands_btn.setEnabled(False)
        self._run_commands_btn.hide()
        self._run_commands_btn.clicked.connect(self._on_run_commands)
        button_bar.addWidget(self._run_commands_btn)

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
    ) -> None:
        """Load a manifest preview, or skip if the same manifest is already showing results.

        If the widget is in :attr:`PreviewPhase.DONE` and *path_or_url*
        matches the current manifest key, the load is silently skipped
        so that execution logs remain visible.  Otherwise the widget
        resets and starts a new :class:`PreviewWorker`.

        Args:
            path_or_url: Manifest path or URL.
            project_directory: Working directory for project sync actions.
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

        self._task = asyncio.create_task(
            self._run_preview_task(
                path_or_url,
                project_directory=self._model.project_directory,
                prerelease_packages=overrides,
            ),
        )

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
        self._run_commands_btn.setEnabled(False)
        self._run_commands_btn.hide()
        self._install_results = None
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
        """Cancel any running preview or install task."""
        self._prerelease_debounce.stop()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None

    async def _run_preview_task(
        self,
        path_or_url: str,
        *,
        project_directory: Path | None = None,
        prerelease_packages: set[str] | None = None,
    ) -> None:
        """Run the preview coroutine and route completion/errors."""
        try:
            await run_preview(
                self._porringer,
                path_or_url,
                config=PreviewConfig(
                    project_directory=project_directory,
                    prerelease_packages=prerelease_packages,
                ),
                on_event=self._on_preview_event,
                plugins=self._discovered_plugins,
            )
            self._on_preview_finished()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception('Preview failed')
            self._on_preview_error(str(exc))

    async def _run_install_task(
        self,
        manifest_path: Path,
        config: InstallConfig,
    ) -> None:
        """Run the install coroutine and route completion/errors."""
        try:
            results = await run_install(
                self._porringer,
                manifest_path,
                config,
                InstallCallbacks(
                    on_action_started=self._on_action_started,
                    on_sub_progress=self._on_sub_progress,
                    on_progress=self._on_action_progress,
                ),
                plugins=self._discovered_plugins,
                exclude_post_sync=self._model.has_post_sync,
            )
            self._on_install_finished(results)
        except asyncio.CancelledError:
            self._on_install_finished(SetupResults(actions=[]))
        except Exception as exc:
            logger.exception('Install execution failed')
            self._on_install_error(str(exc))

    # --- Preview event dispatcher ---

    def _on_preview_event(self, event: object) -> None:
        """Route a :data:`PreviewEvent` to the appropriate handler."""
        from synodic_client.operations.schema import (
            PreviewActionChecked,
            PreviewManifestParsed,
            PreviewPluginsQueried,
            PreviewReady,
        )

        if isinstance(event, PreviewManifestParsed):
            self._on_manifest_parsed(event.manifest, event.manifest_path, event.temp_dir)
        elif isinstance(event, PreviewPluginsQueried):
            self._on_plugins_queried(event.availability, event.capabilities)
        elif isinstance(event, PreviewReady):
            self._on_preview_resolved(event.manifest, event.manifest_path, event.temp_dir)
        elif isinstance(event, PreviewActionChecked):
            self._on_action_checked(event.index, event.result, event.status)

    # --- Preview callbacks (wired by load()) ---

    def _on_manifest_parsed(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle the fast MANIFEST_PARSED event — show cards immediately."""
        self._model.temp_dir = temp_dir_path

        if preview.metadata:
            self.metadata_ready.emit(preview)

        self._on_preview_ready(preview, manifest_path, temp_dir_path)

    def _on_plugins_queried(
        self,
        mapping: dict[str, bool],
        capabilities: dict[str, frozenset],
    ) -> None:
        """Store plugin presence and capability data for annotating the action cards."""
        self._model.plugin_installed = mapping
        self._model.plugin_capabilities = capabilities

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
        """Handle the fully-resolved preview.

        Called after ``MANIFEST_LOADED`` — cards are already visible
        from the earlier ``_on_manifest_parsed`` handler.  This updates
        the temp-dir reference.
        """
        if self._model.preview is None:
            return

        self._model.temp_dir = temp_dir_path

    def _on_action_checked(self, row: int, result: SetupActionResult, status: str) -> None:
        """Update the model and action card with a dry-run result.

        This callback performs only two things:
        1. Update the ``ActionState.status`` in the model.
        2. Update the ``ActionCard`` widget visually.

        Cross-component side effects (PackageStateStore writes) are
        deferred to :meth:`_on_preview_finished` for one-way data flow.
        """
        m = self._model

        if 0 <= row < len(m.action_states):
            m.action_states[row].status = status

        logger.debug(
            'Action checked [%d]: status=%s success=%s skipped=%s skip_reason=%s installed=%s available=%s',
            row,
            status,
            result.success,
            result.skipped,
            result.skip_reason,
            result.installed_version,
            result.available_version,
        )

        # Update the card widget
        if m.preview and 0 <= row < len(m.preview.actions):
            card = self._card_list.card_for_action_index(row)
            if card is not None:
                card.set_check_result(result, status)

        # Update phase text
        m.checked_count += 1
        total = len(m.action_states)
        self._status_label.setText(
            f'{total} action(s) \u2014 checking status ({m.checked_count}/{total})\u2026',
        )

    def _on_preview_finished(self) -> None:
        """Finalize the preview after the dry-run check completes.

        Computes the :class:`InstallPlan` via the operations layer,
        batch-writes to :class:`PackageStateStore`, and updates all
        button states.  This is the single point where preview results
        are materialised into actionable decisions.
        """
        from synodic_client.operations.schema import ActionCheckResult, compute_install_plan

        m = self._model
        if not m.action_states:
            return

        self._card_list.finalize_all_checking()

        finalized: list[str] = []
        for state in m.action_states:
            if state.status == 'Checking\u2026':
                finalized.append(state.action.description)
                state.status = 'Needed'
        if finalized:
            logger.warning(
                'Finalized %d action(s) from Checking to Needed (no dry-run result received): %s',
                len(finalized),
                finalized,
            )

        # Build check results for the plan computation
        check_results: list[ActionCheckResult] = []
        for i, state in enumerate(m.action_states):
            # We need the dry-run result — reconstruct a minimal one from the status
            # The actual result was already applied to the card; here we use the
            # status string which is the canonical output of resolve_action_status.
            check_results.append(
                ActionCheckResult(
                    index=i,
                    action=state.action,
                    result=SetupActionResult(action=state.action, success=True),
                    status=state.status,
                ),
            )

        plan = compute_install_plan(check_results)
        m.install_plan = plan

        # Batch-write to PackageStateStore (one-way, after plan is computed)
        if self._package_store is not None and m.preview is not None:
            for state in m.action_states:
                action = state.action
                if action.installer and action.package:
                    self._package_store.record_action_result(
                        action.installer,
                        str(action.package.name),
                        installed_version='',
                        available_version='',
                        has_update=state.status == 'Update available',
                    )

        # Update UI from the plan
        self._status_label.setText(plan.summary)
        self._install_btn.setEnabled(plan.install_enabled)
        if not plan.install_enabled:
            self._install_btn.setToolTip('No packages to install')
        else:
            self._install_btn.setToolTip('')

        # Show/enable the Run Commands button if post-sync exists
        if plan.has_post_sync:
            self._run_commands_btn.show()
            self._run_commands_btn.setEnabled(True)

        self._set_phase(PreviewPhase.READY)

        logger.info(
            'Preview complete: %d total, %d to install, %d satisfied, %d upgradable, %d post-sync, install_enabled=%s',
            len(m.action_states),
            len(plan.install_indices),
            len(plan.satisfied_indices),
            len(plan.upgradable_indices),
            len(plan.post_sync_indices),
            plan.install_enabled,
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
        """Handle the Install button click.

        Uses the pre-computed :class:`InstallPlan` to determine the
        sync strategy.  Post-sync commands are excluded from this
        execution — they are handled by :meth:`_on_run_commands`.
        """
        m = self._model
        if m.manifest_path is None or m.install_plan is None:
            return

        self._prerelease_debounce.stop()
        self._set_phase(PreviewPhase.INSTALLING)
        self._install_btn.setEnabled(False)
        self._run_commands_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        m.completed_count = 0

        self._status_label.setText('Installing\u2026')

        # Show the unified execution log panel
        self._log_panel.clear()
        self._log_panel.show()

        # Strategy and post-sync exclusion come from the plan
        strategy = m.install_plan.strategy

        self._task = asyncio.create_task(
            self._run_install_task(
                m.manifest_path,
                InstallConfig(
                    project_directory=m.project_directory,
                    strategy=strategy,
                    prerelease_packages=m.prerelease_overrides or None,
                ),
            ),
        )

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
        if self._task is not None and not self._task.done():
            self._task.cancel()

    def _on_install_finished(self, results: SetupResults) -> None:
        """Handle install completion.

        If the plan includes post-sync commands and no actions failed,
        automatically triggers :meth:`_on_run_commands`.
        """
        from synodic_client.operations.schema import format_install_summary

        m = self._model
        pre_skipped = len(m.install_plan.satisfied_indices) if m.install_plan else 0
        failed = sum(1 for r in results.results if not r.success)

        # Auto-run post-sync if install succeeded and post-sync exists
        if m.has_post_sync and failed == 0:
            summary = format_install_summary(
                install_results=list(results.results),
                pre_skipped_count=pre_skipped,
            )
            self._status_label.setText(f'{summary}. Running post-sync commands\u2026')
            self._run_commands_btn.setEnabled(False)
            self._task = asyncio.create_task(self._run_post_sync_task())
            self._install_results = results  # Stash for final summary
            return

        self._set_phase(PreviewPhase.DONE)
        summary = format_install_summary(
            install_results=list(results.results),
            pre_skipped_count=pre_skipped,
        )
        self._status_label.setText(summary)
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        if m.has_post_sync:
            self._run_commands_btn.setEnabled(True)
        self.install_finished.emit(results)

    def _on_install_error(self, message: str) -> None:
        """Handle install error."""
        self._set_phase(PreviewPhase.ERROR)
        self._status_label.setText(f'Install failed: {message}')
        self._install_btn.setEnabled(True)
        self._close_btn.setEnabled(True)

    # --- Post-sync execution ---

    def _on_run_commands(self) -> None:
        """Handle the Run Commands button click."""
        m = self._model
        if m.manifest_path is None:
            return

        self._run_commands_btn.setEnabled(False)
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(False)

        self._status_label.setText('Running post-sync commands\u2026')

        if not self._log_panel.isVisible():
            self._log_panel.clear()
            self._log_panel.show()

        self._install_results = None
        self._task = asyncio.create_task(self._run_post_sync_task())

    async def _run_post_sync_task(self) -> None:
        """Run the post-sync coroutine and route completion/errors."""
        assert self._model.manifest_path is not None
        try:
            results = await run_post_sync(
                self._porringer,
                self._model.manifest_path,
                project_directory=self._model.project_directory,
                callbacks=InstallCallbacks(
                    on_action_started=self._on_action_started,
                    on_sub_progress=self._on_sub_progress,
                    on_progress=self._on_action_progress,
                ),
                plugins=self._discovered_plugins,
            )
            self._on_post_sync_finished(results)
        except asyncio.CancelledError:
            self._on_post_sync_finished(SetupResults(actions=[]))
        except Exception as exc:
            logger.exception('Post-sync execution failed')
            self._on_install_error(f'Post-sync failed: {exc}')

    def _on_post_sync_finished(self, results: SetupResults) -> None:
        """Handle post-sync completion."""
        from synodic_client.operations.schema import format_install_summary

        m = self._model
        m.post_sync_completed = True
        m.post_sync_results = list(results.results)

        self._set_phase(PreviewPhase.DONE)

        pre_skipped = len(m.install_plan.satisfied_indices) if m.install_plan else 0

        # If we have stashed install results (auto-run path), use combined summary
        install_results = list(self._install_results.results) if self._install_results else None
        summary = format_install_summary(
            install_results=install_results,
            post_sync_results=m.post_sync_results,
            pre_skipped_count=pre_skipped,
        )
        self._status_label.setText(summary)
        self._install_btn.setEnabled(False)
        self._run_commands_btn.setEnabled(False)
        self._close_btn.setEnabled(True)

        # Only emit when coming from the auto-run path (install_finished
        # was not yet emitted).  On the manual "Run Commands" path the
        # signal was already emitted by _on_install_finished.
        if self._install_results is not None:
            self.install_finished.emit(results)


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

    def showEvent(self, event: QShowEvent) -> None:
        """[DIAG] Log every show event with a stack trace."""
        geo = self.geometry()
        stack = ''.join(traceback.format_stack(limit=10))
        logger.warning(
            '[DIAG] InstallPreviewWindow.showEvent: geo=(%d,%d %dx%d) visible=%s\n%s',
            geo.x(),
            geo.y(),
            geo.width(),
            geo.height(),
            self.isVisible(),
            stack,
        )
        super().showEvent(event)

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

    def closeEvent(self, event: Any) -> None:
        """Clean up the temp directory when the window is closed."""
        logger.info('Install preview window closing')
        temp = self._preview_widget.model.temp_dir
        if temp:
            safe_rmtree(temp)
        super().closeEvent(event)

    # --- Public API ---

    def start(self) -> None:
        """Download the manifest and populate the preview.

        Call this after ``show()`` to begin the download → preview flow.
        """
        logger.info('Starting install preview for: %s', self._manifest_url)
        self._url_label.setText(f'<b>Manifest:</b> {self._manifest_url}')

        self._preview_widget.load(
            self._manifest_url,
            project_directory=self._project_directory,
        )

    # --- Callbacks ---

    def _on_metadata_ready(self, preview: object) -> None:
        """Update the window title when metadata arrives."""
        if hasattr(preview, 'metadata') and preview.metadata and preview.metadata.name:
            self.setWindowTitle(f'Install Preview \u2014 {preview.metadata.name}')
