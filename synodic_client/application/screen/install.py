"""Install preview widgets and workers.

Provides a reusable :class:`SetupPreviewWidget` for displaying dry-run
previews and executing porringer setup actions, along with the standalone
:class:`InstallPreviewWindow` used for URI-based manifest installs.

Execution runs on a background ``QThread`` with real-time inline
log output in each :class:`~synodic_client.application.screen.action_card.ActionCard`.
"""

from __future__ import annotations

import asyncio
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
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen import skip_reason_label
from synodic_client.application.screen.action_card import ActionCardList
from synodic_client.application.screen.card import CardFrame
from synodic_client.application.theme import (
    ACTION_CARD_SKELETON_BAR_STYLE,
    CARD_SPACING,
    COMMAND_HEADER_STYLE,
    COMPACT_MARGINS,
    CONTENT_MARGINS,
    COPY_BTN_SIZE,
    COPY_BTN_STYLE,
    COPY_FEEDBACK_MS,
    COPY_ICON,
    HEADER_STYLE,
    INSTALL_PREVIEW_MIN_SIZE,
    METADATA_SKELETON_HEIGHT,
    METADATA_SKELETON_STYLE,
    MONOSPACE_FAMILY,
    MONOSPACE_SIZE,
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


def format_cli_command(action: SetupAction) -> str:
    """Return a copyable CLI command string for *action*."""
    if parts := (action.cli_command or action.command):
        return ' '.join(parts)
    if action.kind == PluginKind.PACKAGE and action.package:
        return f'{action.installer or "pip"} install {action.package}'
    return action.description


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


class PostInstallSection(QWidget):
    """Always-visible section showing bare-command (post-install) actions.

    Bare-command actions (``kind is None``) cannot be dry-run checked, so
    they are excluded from the main actions table.  This widget gives
    them a dedicated, always-visible home with copyable CLI text.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the section (hidden until :meth:`populate` is called)."""
        super().__init__(parent)
        self.hide()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*NO_MARGINS)
        self._layout.setSpacing(4)

        header = QLabel('Post-Install Commands')
        header.setStyleSheet(COMMAND_HEADER_STYLE)
        self._layout.addWidget(header)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(*NO_MARGINS)
        self._content_layout.setSpacing(4)
        self._layout.addWidget(self._content)

    def populate(self, actions: list[SetupAction]) -> None:
        """Show command actions from *actions*.

        Only actions whose ``kind`` is ``None`` are shown.  If there are
        none the widget stays hidden.

        Args:
            actions: The full list of setup actions.
        """
        # Clear previous content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        commands = [(i, a) for i, a in enumerate(actions, 1) if a.kind is None]
        if not commands:
            self.hide()
            return

        mono = QFont(MONOSPACE_FAMILY, MONOSPACE_SIZE)
        for idx, action in commands:
            desc = action.package_description or action.description
            label = QLabel(f'{idx}. {desc}')
            label.setStyleSheet(COMMAND_HEADER_STYLE)
            self._content_layout.addWidget(label)

            field = QLineEdit(format_cli_command(action))
            field.setReadOnly(True)
            field.setFont(mono)

            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(*NO_MARGINS)
            row_layout.setSpacing(4)
            row_layout.addWidget(field)
            row_layout.addWidget(_make_copy_button(field))

            row_widget = QWidget()
            row_widget.setLayout(row_layout)
            self._content_layout.addWidget(row_widget)

        self.show()


def _make_copy_button(field: QLineEdit) -> QToolButton:
    """Create a copy-to-clipboard button bound to *field*."""
    btn = QToolButton()
    btn.setText(COPY_ICON)
    btn.setToolTip('Copy to clipboard')
    btn.setFixedSize(*COPY_BTN_SIZE)
    btn.setStyleSheet(COPY_BTN_STYLE)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(lambda: _copy_command(field, btn))
    return btn


def _copy_command(field: QLineEdit, button: QToolButton) -> None:
    """Copy the field text to the clipboard and briefly show a check mark."""
    clipboard = QApplication.clipboard()
    if clipboard:
        clipboard.setText(field.text())
    button.setText('\u2713')
    button.setToolTip('Copied!')

    def _restore() -> None:
        try:
            button.setText(COPY_ICON)
            button.setToolTip('Copy to clipboard')
        except RuntimeError:
            pass

    QTimer.singleShot(COPY_FEEDBACK_MS, _restore)


# ---------------------------------------------------------------------------
# SetupPreviewWidget — reusable preview + install widget
# ---------------------------------------------------------------------------


class SetupPreviewWidget(QWidget):
    """Reusable widget that displays a dry-run preview and executes installs.

    This widget is embedded by both :class:`InstallPreviewWindow` (for
    URI-based installs) and ``ProjectsView`` (for cached-directory
    projects).  It owns the action card list, command section, metadata
    display, status label, and install execution pipeline.

    The caller is responsible for providing a manifest path and project
    directory.  Preview data is fed in via
    :meth:`on_preview_ready` / :meth:`on_action_checked` /
    :meth:`on_preview_finished` / :meth:`on_preview_error` signal slots.
    """

    #: Emitted when the user clicks Close (or after a fatal preview error).
    close_requested = Signal()

    #: Emitted after a successful install completes.
    install_finished = Signal(object)  # SetupResults

    #: Emitted when per-item pre-release overrides change (debounced).
    prerelease_changed = Signal()

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
        self._manifest_key: str | None = None
        self._preview: SetupResults | None = None
        self._manifest_path: Path | None = None
        self._project_directory: Path | None = None
        self._runner: QThread | None = None
        self._cancellation_token: CancellationToken | None = None
        self._completed_count = 0
        self._checked_count = 0
        self._action_statuses: list[str] = []
        self._upgradable_rows: set[int] = set()
        self._action_index_map: dict[int, int] = {}
        self._plugin_installed: dict[str, bool] = {}
        self._prerelease_overrides: set[str] = set()
        self._installing = False

        # Debounce timer for per-row pre-release checkbox changes
        self._prerelease_debounce = QTimer(self)
        self._prerelease_debounce.setSingleShot(True)
        self._prerelease_debounce.setInterval(500)
        self._prerelease_debounce.timeout.connect(self._flush_prerelease_overrides)

        self._init_ui()

    # --- UI construction ---

    def _init_ui(self) -> None:
        """Build the two-pane layout.

        Top pane (fixed): metadata card (or skeleton), status/phase label,
        button bar.  Bottom pane (scrollable): :class:`ActionCardList`
        holding one :class:`ActionCard` per action, with inline execution
        logs and per-card spinners.  No global overlay spinner.
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

        # --- Scrollable card list (fills remaining space) ---
        self._card_list = ActionCardList()
        self._card_list.prerelease_toggled.connect(self._on_prerelease_row_toggled)
        outer.addWidget(self._card_list, stretch=1)

        # Post-install section lives below the card list but still scrolls.
        # It starts hidden and is inserted into the layout after populate().
        self._post_install_section = PostInstallSection()

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
    def prerelease_overrides(self) -> set[str] | None:
        """Return the current per-item pre-release overrides.

        Returns ``None`` when no user overrides are active.  The
        returned set contains canonical (lowered) package names.
        """
        return self._prerelease_overrides or None

    def set_manifest_key(self, key: str) -> None:
        """Set the manifest key and load persisted pre-release overrides.

        The key is normalised so that equivalent paths always resolve
        to the same config entry.

        Args:
            key: Manifest path or URL identifying this preview.
        """
        self._manifest_key = normalize_manifest_key(key)
        if self._config is not None and self._config.prerelease_packages:
            self._prerelease_overrides = set(self._config.prerelease_packages.get(self._manifest_key, []))
        else:
            self._prerelease_overrides = set()

    def set_project_directory(self, path: Path) -> None:
        """Set the project directory used for install execution.

        Args:
            path: Working directory for project sync actions.
        """
        self._project_directory = path

    def reset(self) -> None:
        """Clear all state and UI for a fresh preview."""
        self._preview = None
        self._manifest_path = None
        self._manifest_key = None
        self._runner = None
        self._cancellation_token = None
        self._completed_count = 0
        self._checked_count = 0
        self._action_statuses = []
        self._upgradable_rows = set()
        self._action_index_map = {}
        self._plugin_installed = {}
        self._prerelease_overrides = set()
        self._installing = False
        self._prerelease_debounce.stop()

        self._card_list.clear()
        self._post_install_section.hide()
        self._name_label.hide()
        self._description_label.hide()
        self._meta_label.hide()
        self._metadata_card.hide()
        self._metadata_skeleton.hide()
        self._status_label.setText('')
        self._status_label.setStyleSheet('')
        self._install_btn.setEnabled(False)

    def start_loading(self) -> None:
        """Show skeleton placeholders for the metadata card and action cards.

        The metadata skeleton reserves the space that the real metadata
        card will occupy.  Each action card skeleton shows placeholder
        bars with a per-card spinner built in.
        """
        self._metadata_skeleton.show()
        self._card_list.show_skeletons(3)
        self._status_label.setText('Downloading manifest\u2026')
        self._status_label.setStyleSheet(MUTED_STYLE)

    def show_not_found(self, message: str) -> None:
        """Display a muted 'not found' message in the status label.

        Used by callers that want to report a missing directory or manifest
        without popping a modal dialog.

        Args:
            message: The human-readable error or not-found description.
        """
        self._status_label.setText(message)
        self._status_label.setStyleSheet(MUTED_STYLE)

    # --- Per-item pre-release overrides ---

    def _on_prerelease_row_toggled(self, package_name: str, checked: bool) -> None:
        """Handle a per-row pre-release checkbox toggle."""
        key = package_name.lower()
        if checked:
            self._prerelease_overrides.add(key)
        else:
            self._prerelease_overrides.discard(key)
        self._prerelease_debounce.start()

    def _flush_prerelease_overrides(self) -> None:
        """Persist overrides to config and emit the changed signal.

        Skips the signal emission (but still saves the config) while an
        install is in progress to prevent the parent from reloading the
        preview and wiping the execution log.
        """
        if self._config is None or self._manifest_key is None:
            return

        pkgs = dict(self._config.prerelease_packages or {})
        if self._prerelease_overrides:
            pkgs[self._manifest_key] = sorted(self._prerelease_overrides)
        else:
            pkgs.pop(self._manifest_key, None)

        new_value = pkgs if pkgs else None
        self._config = update_user_config(prerelease_packages=new_value)
        logger.info('Pre-release overrides for %s: %s', self._manifest_key, self._prerelease_overrides)

        if not self._installing:
            self.prerelease_changed.emit()

    # --- Preview callbacks (connect to PreviewWorker signals) ---

    def on_plugins_queried(self, mapping: dict[str, bool]) -> None:
        """Store plugin presence data for annotating the action cards.

        Called before :meth:`on_preview_ready` so that card population
        can flag actions whose installer plugin is not installed.

        Args:
            mapping: Plugin name → installed status.
        """
        self._plugin_installed = mapping

    def on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle a successful preview — populate action cards.

        Args:
            preview: The setup preview results.
            manifest_path: Path to the manifest file.
            temp_dir_path: Path to the temp directory (kept alive for execution).
        """
        logger.info('Preview ready: %d action(s) from %s', len(preview.actions), manifest_path)
        self._preview = preview
        self._manifest_path = Path(manifest_path)
        self._status_label.setStyleSheet('')
        self._metadata_skeleton.hide()

        self._show_metadata(preview)

        if not preview.actions:
            self._card_list.clear()
            self._status_label.setText('No actions to perform — the manifest is empty.')
            return

        self._action_statuses = ['Checking\u2026'] * len(preview.actions)
        self._checked_count = 0

        # Build the action-index → identity map for card lookup during execution
        self._action_index_map = {id(a): i for i, a in enumerate(preview.actions)}

        total = len(preview.actions)
        self._status_label.setText(f'{total} action(s) \u2014 checking status\u2026')

        self._card_list.populate(
            preview.actions,
            plugin_installed=self._plugin_installed,
            prerelease_overrides=self._prerelease_overrides,
        )

        # Mark installer-missing actions as 'Not installed' in the status list
        for i, action in enumerate(preview.actions):
            if action.kind is None:
                continue
            installer_missing = (
                action.installer is not None
                and action.installer in self._plugin_installed
                and not self._plugin_installed[action.installer]
            )
            if installer_missing:
                self._action_statuses[i] = 'Not installed'

        # Populate post-install commands and place them after all cards.
        self._post_install_section.populate(preview.actions)
        self._card_list._layout.insertWidget(
            self._card_list._layout.count() - 1,
            self._post_install_section,
        )

        self._install_btn.setEnabled(True)

    def on_preview_resolved(self, preview: SetupResults) -> None:
        """Handle the fully-resolved preview (CLI commands populated).

        Called after ``MANIFEST_LOADED`` — cards are already visible
        from the earlier ``on_preview_ready`` call.  This method
        updates the CLI command display text on each existing card.

        Args:
            preview: The fully-resolved setup results with CLI commands.
        """
        if self._preview is None:
            return

        for action in preview.actions:
            if action.cli_command:
                card = self._card_list.get_card(action)
                if card is not None:
                    card.update_command(action)

    def on_action_checked(self, row: int, result: SetupActionResult) -> None:
        """Update the data model and action card with the dry-run result."""
        if result.skipped and result.skip_reason == SkipReason.UPDATE_AVAILABLE:
            label = skip_reason_label(result.skip_reason)
            self._upgradable_rows.add(row)
        elif result.skipped:
            label = skip_reason_label(result.skip_reason)
        else:
            label = 'Needed'

        if 0 <= row < len(self._action_statuses):
            self._action_statuses[row] = label

        # Find the card for this action
        if self._preview and 0 <= row < len(self._preview.actions):
            action = self._preview.actions[row]
            card = self._card_list.get_card(action)
            if card is not None:
                card.set_check_result(result)

        # Update phase text with progress count
        self._checked_count += 1
        total = len(self._action_statuses)
        self._status_label.setText(f'{total} action(s) \u2014 checking status ({self._checked_count}/{total})\u2026')

    def on_preview_finished(self) -> None:
        """Finalize the preview after the dry-run check completes."""
        if not self._action_statuses:
            return

        # Resolve any still-pending statuses as 'Needed', but leave
        # 'Not installed' entries untouched — they indicate a missing plugin.
        self._card_list.finalize_all_checking()

        for i, status in enumerate(self._action_statuses):
            if status == 'Checking\u2026':
                self._action_statuses[i] = 'Needed'

        # Count ALL actions (including bare commands) for enablement.
        total = len(self._action_statuses)
        needed = sum(1 for s in self._action_statuses if s == 'Needed')
        upgradable = len(self._upgradable_rows)
        unavailable = sum(1 for s in self._action_statuses if s == 'Not installed')
        satisfied = total - needed - upgradable - unavailable

        parts: list[str] = []
        if needed:
            parts.append(f'{needed} needed')
        if upgradable:
            parts.append(f'{upgradable} upgradable')
        if satisfied:
            parts.append(f'{satisfied} already satisfied')
        if unavailable:
            parts.append(f'{unavailable} unavailable (plugin not installed)')

        actionable = needed + upgradable
        if actionable == 0 and unavailable == 0:
            self._status_label.setText(f'{total} action(s) \u2014 all already satisfied.')
            self._install_btn.setEnabled(False)
        else:
            self._status_label.setText(f'{total} action(s): {", ".join(parts)}.')

        logger.info(
            'Preview complete: %d total, %d needed, %d upgradable, %d satisfied, %d unavailable',
            total,
            needed,
            upgradable,
            satisfied,
            unavailable,
        )

    def on_preview_error(self, message: str) -> None:
        """Handle a preview error."""
        logger.error('Preview failed: %s', message)
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
        if self._manifest_path is None:
            return

        self._installing = True
        self._prerelease_debounce.stop()
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        self._completed_count = 0

        self._cancellation_token = CancellationToken()

        self._status_label.setText('Installing\u2026')

        # Choose LATEST strategy when there are upgradable actions so
        # porringer actually upgrades the already-installed packages.
        strategy = SyncStrategy.LATEST if self._upgradable_rows else SyncStrategy.MINIMAL

        # Worker thread
        worker = InstallWorker(
            self._porringer,
            self._manifest_path,
            self._cancellation_token,
            InstallConfig(
                project_directory=self._project_directory,
                strategy=strategy,
                prerelease_packages=self._prerelease_overrides or None,
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
        """Handle an action starting execution — expand its card inline."""
        card = self._card_list.get_card(action)
        if card is not None:
            card.set_executing()
            self._card_list.scroll_to_card(card)

    def _on_sub_progress(self, action: SetupAction, progress: SubActionProgress) -> None:
        """Handle a sub-action progress event — route output to the card."""
        card = self._card_list.get_card(action)
        if card is None:
            return

        if progress.output is not None:
            card.append_output(progress.output, progress.stream)
        elif progress.message is not None:
            card.append_output(progress.message)

        # Follow the growing log — keep the bottom of the card in view.
        self._card_list.scroll_to_card_bottom(card)

    def _on_action_progress(self, action: SetupAction, result: SetupActionResult) -> None:
        """Handle a single action completion from the worker."""
        self._completed_count += 1

        # Update the action card inline
        card = self._card_list.get_card(action)
        if card is not None:
            card.set_result(result)

        # Update status label
        total = len(self._preview.actions) if self._preview else 0
        self._status_label.setText(f'Installing\u2026 ({self._completed_count}/{total})')

    def _on_cancel(self) -> None:
        """Handle cancel request."""
        if self._cancellation_token:
            self._cancellation_token.cancel()

    def _on_install_finished(self, results: SetupResults) -> None:
        """Handle install completion."""
        self._installing = False

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
        self._installing = False
        self._status_label.setText(f'Install failed: {message}')
        self._install_btn.setEnabled(True)
        self._close_btn.setEnabled(True)


# ---------------------------------------------------------------------------
# InstallPreviewWindow — standalone URI-based install window
# ---------------------------------------------------------------------------


class InstallPreviewWindow(QMainWindow):
    """Standalone window that previews and executes a URI-based manifest install.

    Wraps :class:`SetupPreviewWidget` and owns the download lifecycle
    (temp directory, ``PreviewWorker``).
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
        self._temp_dir_path: str | None = None
        self._runner: QThread | None = None

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

        # Shared preview widget
        self._preview_widget = SetupPreviewWidget(self._porringer, self, config=self._config)
        self._preview_widget.close_requested.connect(self.close)
        self._preview_widget.prerelease_changed.connect(self._on_prerelease_changed)
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
        self._cleanup_temp_dir()
        super().closeEvent(event)

    def _cleanup_temp_dir(self) -> None:
        """Remove the temporary download directory if it exists."""
        if self._temp_dir_path:
            _safe_rmtree(self._temp_dir_path)
            self._temp_dir_path = None

    # --- Public API ---

    def start(self) -> None:
        """Download the manifest and populate the preview.

        Call this after ``show()`` to begin the download → preview flow.
        """
        self._stop_preview()
        logger.info('Starting install preview for: %s', self._manifest_url)
        self._url_label.setText(f'<b>Manifest:</b> {self._manifest_url}')
        self._preview_widget.reset()
        self._preview_widget.start_loading()
        self._preview_widget.set_manifest_key(self._manifest_url)

        manifest_key = normalize_manifest_key(self._manifest_url)
        config = self._config
        if config is None:
            return
        overrides = set((config.prerelease_packages or {}).get(manifest_key, []))

        preview_worker = PreviewWorker(
            self._porringer,
            self._manifest_url,
            project_directory=self._project_directory,
            detect_updates=config.detect_updates,
            prerelease_packages=overrides or None,
        )

        preview_worker.manifest_parsed.connect(self._on_manifest_parsed)
        preview_worker.plugins_queried.connect(self._preview_widget.on_plugins_queried)
        preview_worker.preview_ready.connect(self._on_preview_ready)
        preview_worker.action_checked.connect(self._preview_widget.on_action_checked)
        preview_worker.finished.connect(self._preview_widget.on_preview_finished)
        preview_worker.error.connect(self._preview_widget.on_preview_error)

        self._runner = preview_worker
        self._runner.start()

    # --- Preview callbacks (intercept to capture temp dir / metadata) ---

    def _on_manifest_parsed(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle the fast MANIFEST_PARSED event — show cards immediately."""
        self._temp_dir_path = temp_dir_path

        # Update window title from metadata
        if preview.metadata and preview.metadata.name:
            self.setWindowTitle(f'Install Preview — {preview.metadata.name}')

        self._preview_widget.on_preview_ready(preview, manifest_path, temp_dir_path)

    def _on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle the fully-resolved MANIFEST_LOADED event.

        At this point CLI commands are populated on each action.  We
        forward to the preview widget so it can refresh any command
        display text, but cards are already visible from the earlier
        ``_on_manifest_parsed`` handler.
        """
        self._temp_dir_path = temp_dir_path

        # Update window title from metadata (in case it changed)
        if preview.metadata and preview.metadata.name:
            self.setWindowTitle(f'Install Preview — {preview.metadata.name}')

        self._preview_widget.on_preview_resolved(preview)

    def _on_prerelease_changed(self) -> None:
        """Re-run the preview with the updated pre-release setting."""
        self.start()

    def _stop_preview(self) -> None:
        """Wait for any running preview worker to finish before starting a new one."""
        if self._runner is not None and self._runner.isRunning():
            self._runner.quit()
            self._runner.wait()
            self._runner = None


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
