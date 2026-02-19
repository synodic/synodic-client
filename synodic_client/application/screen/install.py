"""Install preview widgets and workers.

Provides a reusable :class:`SetupPreviewWidget` for displaying dry-run
previews and executing porringer setup actions, along with the standalone
:class:`InstallPreviewWindow` used for URI-based manifest installs.

Execution runs on a background ``QThread`` with a real-time
:class:`~synodic_client.application.screen.log_panel.ExecutionLogPanel`.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
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
    SubActionProgress,
)
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen import ACTION_KIND_LABELS, skip_reason_label
from synodic_client.application.screen.card import CardFrame
from synodic_client.application.screen.log_panel import ExecutionLogPanel
from synodic_client.application.screen.spinner import SpinnerWidget
from synodic_client.application.theme import (
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
    MONOSPACE_FAMILY,
    MONOSPACE_SIZE,
    MUTED_STYLE,
    NO_MARGINS,
)

logger = logging.getLogger(__name__)


def format_cli_command(action: SetupAction) -> str:
    """Return a copyable CLI command string for *action*."""
    if parts := (action.cli_command or action.command):
        return ' '.join(parts)
    if action.kind == PluginKind.PACKAGE and action.package:
        return f'{action.installer or "pip"} install {action.package}'
    return action.description


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
        *,
        project_directory: Path | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            manifest_path: Path to the manifest file to execute.
            cancellation_token: Token for cooperative cancellation.
            project_directory: Working directory for project sync actions.
        """
        super().__init__()
        self._porringer = porringer
        self._manifest_path = manifest_path
        self._cancellation_token = cancellation_token
        self._project_directory = project_directory

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
            project_directory=self._project_directory,
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
    projects).  It owns the actions table, command list, metadata display,
    status label, and install execution pipeline.

    The caller is responsible for providing a manifest path and project
    directory.  Preview data is fed in via
    :meth:`on_preview_ready` / :meth:`on_action_checked` /
    :meth:`on_preview_finished` / :meth:`on_preview_error` signal slots.
    """

    #: Emitted when the user clicks Close (or after a fatal preview error).
    close_requested = Signal()

    #: Emitted after a successful install completes.
    install_finished = Signal(object)  # SetupResults

    def __init__(self, porringer: API, parent: QWidget | None = None, *, show_close: bool = True) -> None:
        """Initialize the preview widget.

        Args:
            porringer: The porringer API instance.
            parent: Optional parent widget.
            show_close: Whether to show the Close button.  Set ``False``
                when embedding inside a persistent view (e.g. a tab).
        """
        super().__init__(parent)
        self._porringer = porringer
        self._show_close = show_close
        self._preview: SetupResults | None = None
        self._manifest_path: Path | None = None
        self._project_directory: Path | None = None
        self._runner: QThread | None = None
        self._cancellation_token: CancellationToken | None = None
        self._completed_count = 0
        self._action_statuses: list[str] = []
        self._action_to_table_row: dict[int, int] = {}
        self._plugin_installed: dict[str, bool] = {}

        self._init_ui()

    # --- UI construction ---

    _SPINNER_PAGE = 0
    _CONTENT_PAGE = 1

    def _init_ui(self) -> None:
        """Build the card-based grid layout.

        The spinner and the actions card share a :class:`QStackedWidget`
        so that switching between loading and content states never
        changes the grid geometry — eliminating layout shifts.
        """
        grid = QGridLayout(self)
        grid.setContentsMargins(*NO_MARGINS)
        grid.setVerticalSpacing(CARD_SPACING)
        grid.setHorizontalSpacing(CARD_SPACING)

        row = 0

        # Row 0 — Metadata card (hidden until preview metadata arrives)
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

        grid.addWidget(self._metadata_card, row, 0, 1, 2)
        row += 1

        # Row 1 — Status label
        self._status_label = QLabel()
        grid.addWidget(self._status_label, row, 0, 1, 2)
        row += 1

        # Row 2 — Content stack: spinner (page 0) / actions card (page 1)
        #
        # Both pages live in the same grid cell with the same stretch,
        # so toggling the current page causes *no* layout shift.
        self._content_stack = QStackedWidget()

        self._spinner = SpinnerWidget('Loading\u2026')
        self._spinner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_stack.addWidget(self._spinner)  # page 0

        self._actions_card = CardFrame()
        self._table = self._init_actions_table()
        self._actions_card.content_layout.addWidget(self._table)
        self._post_install_section = PostInstallSection()
        self._actions_card.content_layout.addWidget(self._post_install_section)
        self._content_stack.addWidget(self._actions_card)  # page 1

        self._content_stack.setCurrentIndex(self._CONTENT_PAGE)

        grid.addWidget(self._content_stack, row, 0, 1, 2)
        grid.setRowStretch(row, 2)
        row += 1

        # Row 3 — Execution log card (hidden until install starts)
        self._log_card = CardFrame('Execution Log', collapsible=True)
        self._log_panel = ExecutionLogPanel()
        self._log_card.content_layout.addWidget(self._log_panel)
        self._log_card.hide()
        grid.addWidget(self._log_card, row, 0, 1, 2)
        grid.setRowStretch(row, 1)
        row += 1

        # Row 4 — Button bar
        button_bar = self._init_button_bar()
        grid.addLayout(button_bar, row, 0, 1, 2)

    def _init_actions_table(self) -> QTableWidget:
        """Create and configure the actions table widget."""
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(['Type', 'Plugin', 'Package', 'Description', 'Status'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        QShortcut(QKeySequence.StandardKey.Copy, table, self._copy_table_selection)
        return table

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
        self._runner = None
        self._cancellation_token = None
        self._completed_count = 0
        self._action_statuses = []
        self._action_to_table_row = {}
        self._plugin_installed = {}

        self._table.setRowCount(0)
        self._post_install_section.hide()
        self._log_panel.clear()
        self._log_card.hide()
        self._name_label.hide()
        self._description_label.hide()
        self._meta_label.hide()
        self._metadata_card.hide()
        self._status_label.setText('')
        self._status_label.setStyleSheet('')
        self._spinner._timer.stop()
        self._content_stack.setCurrentIndex(self._CONTENT_PAGE)
        self._install_btn.setEnabled(False)

    def start_loading(self) -> None:
        """Show the centered loading spinner.

        Switches the content stack to the spinner page and starts the
        animation.  The grid geometry stays constant because the spinner
        and the actions card share the same :class:`QStackedWidget` cell.
        """
        self._content_stack.setCurrentIndex(self._SPINNER_PAGE)
        self._spinner._canvas._angle = 0
        self._spinner._timer.start()

    def show_not_found(self, message: str) -> None:
        """Display a muted 'not found' message in the status label.

        Used by callers that want to report a missing directory or manifest
        without popping a modal dialog.

        Args:
            message: The human-readable error or not-found description.
        """
        self._status_label.setText(message)
        self._status_label.setStyleSheet(MUTED_STYLE)

    # --- Preview callbacks (connect to PreviewWorker signals) ---

    def on_plugins_queried(self, mapping: dict[str, bool]) -> None:
        """Store plugin presence data for annotating the preview table.

        Called before :meth:`on_preview_ready` so that
        :meth:`_populate_table` can flag actions whose installer plugin
        is not installed.

        Args:
            mapping: Plugin name → installed status.
        """
        self._plugin_installed = mapping

    def on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle a successful preview.

        Args:
            preview: The setup preview results.
            manifest_path: Path to the manifest file.
            temp_dir_path: Path to the temp directory (kept alive for execution).
        """
        logger.info('Preview ready: %d action(s) from %s', len(preview.actions), manifest_path)
        self._preview = preview
        self._manifest_path = Path(manifest_path)
        self._status_label.setStyleSheet('')
        self._spinner._timer.stop()
        self._content_stack.setCurrentIndex(self._CONTENT_PAGE)

        self._show_metadata(preview)

        if not preview.actions:
            self._status_label.setText('No actions to perform — the manifest is empty.')
            return

        self._action_statuses = ['Checking…'] * len(preview.actions)
        self._status_label.setText(f'{len(preview.actions)} action(s) — checking status…')
        self._populate_table(preview.actions)
        self._install_btn.setEnabled(True)

    def on_action_checked(self, row: int, result: SetupActionResult) -> None:
        """Update the data model and table row with the dry-run result."""
        label = skip_reason_label(result.skip_reason) if result.skipped else 'Needed'

        if 0 <= row < len(self._action_statuses):
            self._action_statuses[row] = label

        # Command actions are not shown in the table.
        table_row = self._action_to_table_row.get(row)
        if table_row is None:
            return

        item = self._table.item(table_row, 4)
        if item is None:
            return

        item.setText(label)
        if result.skipped:
            item.setForeground(self.palette().placeholderText())
        else:
            item.setForeground(self.palette().text())

    def on_preview_finished(self) -> None:
        """Finalize the preview after the dry-run check completes."""
        if not self._action_statuses:
            return

        # Resolve any still-pending statuses as 'Needed', but leave
        # 'Not installed' entries untouched — they indicate a missing plugin.
        for i, status in enumerate(self._action_statuses):
            if status == 'Checking…':
                self._action_statuses[i] = 'Needed'
                table_row = self._action_to_table_row.get(i)
                if table_row is not None:
                    item = self._table.item(table_row, 4)
                    if item is not None:
                        item.setText('Needed')
                        item.setForeground(self.palette().text())

        # Count ALL actions (including bare commands) for enablement.
        total = len(self._action_statuses)
        needed = sum(1 for s in self._action_statuses if s == 'Needed')
        unavailable = sum(1 for s in self._action_statuses if s == 'Not installed')
        satisfied = total - needed - unavailable

        parts: list[str] = []
        if needed:
            parts.append(f'{needed} needed')
        if satisfied:
            parts.append(f'{satisfied} already satisfied')
        if unavailable:
            parts.append(f'{unavailable} unavailable (plugin not installed)')

        if needed == 0 and unavailable == 0:
            self._status_label.setText(f'{total} action(s) — all already satisfied.')
            self._install_btn.setEnabled(False)
        else:
            self._status_label.setText(f'{total} action(s): {", ".join(parts)}.')

        logger.info(
            'Preview complete: %d total, %d needed, %d satisfied, %d unavailable',
            total,
            needed,
            satisfied,
            unavailable,
        )

    def on_preview_error(self, message: str) -> None:
        """Handle a preview error."""
        logger.error('Preview failed: %s', message)
        self._spinner._timer.stop()
        self._content_stack.setCurrentIndex(self._CONTENT_PAGE)
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

    # --- Table ---

    def _copy_table_selection(self) -> None:
        """Copy selected table rows to the clipboard as tab-separated text."""
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not rows:
            return
        cols = self._table.columnCount()
        lines = [
            '\t'.join((item.text() if (item := self._table.item(r, c)) else '') for c in range(cols)) for r in rows
        ]
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText('\n'.join(lines))

    def _populate_table(self, actions: list[SetupAction]) -> None:
        """Fill the actions table and post-install section from *actions*.

        Command actions (``kind is None``) are excluded from the table
        because they cannot be dry-run checked — they always appear as
        *Needed* which is misleading.  They are shown in the dedicated
        :class:`PostInstallSection` instead.

        Actions whose installer plugin is not installed are immediately
        flagged as *Not installed* so the user knows the plugin must be
        set up before the action can succeed.
        """
        self._action_to_table_row = {}
        table_actions = [(i, a) for i, a in enumerate(actions) if a.kind is not None]
        self._table.setRowCount(len(table_actions))
        for table_row, (action_idx, action) in enumerate(table_actions):
            self._action_to_table_row[action_idx] = table_row
            self._table.setItem(table_row, 0, QTableWidgetItem(ACTION_KIND_LABELS.get(action.kind, 'Action')))
            self._table.setItem(table_row, 1, QTableWidgetItem(action.installer or ''))
            self._table.setItem(table_row, 2, QTableWidgetItem(str(action.package) if action.package else ''))
            self._table.setItem(table_row, 3, QTableWidgetItem(action.package_description or action.description))

            # Check whether the installer plugin is present on the system.
            installer_missing = (
                action.installer is not None
                and action.installer in self._plugin_installed
                and not self._plugin_installed[action.installer]
            )

            if installer_missing:
                status_item = QTableWidgetItem('Not installed')
                self._action_statuses[action_idx] = 'Not installed'
            else:
                status_item = QTableWidgetItem('Checking…')

            status_item.setForeground(self.palette().placeholderText())
            self._table.setItem(table_row, 4, status_item)

        # Populate the always-visible post-install commands section
        self._post_install_section.populate(actions)

    # --- Install execution ---

    def _on_install(self) -> None:
        """Handle the Install button click."""
        if self._manifest_path is None:
            return

        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(False)
        self._completed_count = 0

        self._cancellation_token = CancellationToken()

        # Show the execution log card below the actions card
        self._log_panel.clear()
        self._log_card.show()
        self._status_label.setText('Installing…')

        # Worker thread
        worker = InstallWorker(
            self._porringer,
            self._manifest_path,
            self._cancellation_token,
            project_directory=self._project_directory,
        )
        worker.action_started.connect(self._on_action_started)
        worker.sub_progress.connect(self._on_sub_progress)
        worker.progress.connect(self._on_action_progress)
        worker.finished.connect(self._on_install_finished)
        worker.error.connect(self._on_install_error)

        self._runner = worker
        self._runner.start()

    def _on_action_started(self, action: SetupAction) -> None:
        """Handle an action starting execution — create a log section."""
        self._log_panel.add_section(action)

    def _on_sub_progress(self, action: SetupAction, progress: SubActionProgress) -> None:
        """Handle a sub-action progress event — route to the log panel."""
        self._log_panel.on_sub_progress(action, progress)

    def _on_action_progress(self, action: SetupAction, result: SetupActionResult) -> None:
        """Handle a single action completion from the worker."""
        self._completed_count += 1

        # Update the execution log panel
        self._log_panel.on_action_completed(action, result)

        # Map the action back to its table row (commands have no table row)
        if self._preview:
            for idx, a in enumerate(self._preview.actions):
                if a is action:
                    table_row = self._action_to_table_row.get(idx)
                    if table_row is not None:
                        self._update_table_status(table_row, result)
                    break

        # Update status label
        total = len(self._preview.actions) if self._preview else 0
        self._status_label.setText(f'Installing… ({self._completed_count}/{total})')

    def _update_table_status(self, row: int, result: SetupActionResult) -> None:
        """Update the status cell for a table row from an action result."""
        item = self._table.item(row, 4)
        if item is None:
            return

        if result.skipped:
            item.setText(skip_reason_label(result.skip_reason))
            item.setForeground(self.palette().placeholderText())
        elif result.success:
            item.setText('Done')
            item.setForeground(self.palette().text())
        else:
            item.setText(f'Failed: {result.message}' if result.message else 'Failed')
            item.setForeground(self.palette().text())

    def _on_cancel(self) -> None:
        """Handle cancel request."""
        if self._cancellation_token:
            self._cancellation_token.cancel()

    def _on_install_finished(self, results: SetupResults) -> None:
        """Handle install completion."""
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
        self._status_label.setText(f'Done — {summary}')
        self._install_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        self.install_finished.emit(results)

    def _on_install_error(self, message: str) -> None:
        """Handle install error."""
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

    def __init__(self, porringer: API, manifest_url: str, parent: QWidget | None = None) -> None:
        """Initialize the install preview window.

        Args:
            porringer: The porringer API instance.
            manifest_url: The URL of the manifest to install.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._manifest_url = manifest_url
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
        self._preview_widget = SetupPreviewWidget(self._porringer, self)
        self._preview_widget.close_requested.connect(self.close)
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
        logger.info('Starting install preview for: %s', self._manifest_url)
        self._url_label.setText(f'<b>Manifest:</b> {self._manifest_url}')
        self._preview_widget.start_loading()

        preview_worker = PreviewWorker(self._porringer, self._manifest_url, project_directory=self._project_directory)

        preview_worker.plugins_queried.connect(self._preview_widget.on_plugins_queried)
        preview_worker.preview_ready.connect(self._on_preview_ready)
        preview_worker.action_checked.connect(self._preview_widget.on_action_checked)
        preview_worker.finished.connect(self._preview_widget.on_preview_finished)
        preview_worker.error.connect(self._preview_widget.on_preview_error)

        self._runner = preview_worker
        self._runner.start()

    # --- Preview callback (intercepts to capture temp dir) ---

    def _on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Capture the temp dir path and forward to the preview widget."""
        self._temp_dir_path = temp_dir_path

        # Update window title from metadata
        if preview.metadata and preview.metadata.name:
            self.setWindowTitle(f'Install Preview — {preview.metadata.name}')

        self._preview_widget.on_preview_ready(preview, manifest_path, temp_dir_path)


class PreviewWorker(QThread):
    """Background worker that downloads a manifest and performs a dry-run.

    Combines two stages into a single background pipeline:

    1. Download the manifest (if remote).
    2. Run ``execute_stream`` with ``dry_run=True`` to list actions and check status.
    """

    preview_ready = Signal(object, str, str)  # (SetupResults, manifest_path, temp_dir_path)
    action_checked = Signal(int, object)  # (row_index, SetupActionResult)
    plugins_queried = Signal(object)  # dict[str, bool] — plugin name → installed
    finished = Signal()
    error = Signal(str)

    def __init__(self, porringer: API, url: str, *, project_directory: Path | None = None) -> None:
        """Initialize the preview worker."""
        super().__init__()
        self._porringer = porringer
        self._url = url
        self._project_directory = project_directory

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
        """Stream dry-run events, emitting preview_ready and action_checked signals."""
        # Query plugin presence before the dry-run so the widget can
        # annotate actions whose installer is not available.
        plugins = self._porringer.plugin.list()
        plugin_installed = {p.name: p.installed for p in plugins}
        self.plugins_queried.emit(plugin_installed)

        params = SetupParameters(
            paths=[manifest_path],
            dry_run=True,
            project_directory=self._project_directory,
        )
        action_index: dict[int, int] = {}

        async for event in self._porringer.sync.execute_stream(params):
            if event.kind == ProgressEventKind.MANIFEST_LOADED and event.manifest:
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
