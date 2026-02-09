"""Install preview window for URI-based manifest installs.

Displays a dry-run preview of porringer setup actions and lets the user
confirm execution.  Execution runs on a background ``QThread`` with a
cancellable ``QProgressDialog``.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from porringer.schema import (
    BatchSetupResults,
    CancellationToken,
    DownloadParameters,
    ProgressEventKind,
    SetupAction,
    SetupActionResult,
    SetupActionType,
    SetupParameters,
    SetupResults,
)
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.theme import (
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
from synodic_client.application.threading import ThreadRunner

if TYPE_CHECKING:
    from porringer.api import API

logger = logging.getLogger(__name__)

ACTION_TYPE_LABELS = {
    SetupActionType.PACKAGE: 'Package',
    SetupActionType.PROJECT_SYNC: 'Project Sync',
    SetupActionType.RUN_COMMAND: 'Run Command',
}


def format_cli_command(action: SetupAction) -> str:
    """Return a copyable CLI command string for *action*."""
    if parts := (action.cli_command or action.command):
        return ' '.join(parts)
    if action.action_type == SetupActionType.PACKAGE and action.package:
        return f'{action.installer or "pip"} install {action.package}'
    return action.description


class InstallWorker(QObject):
    """Background worker that executes setup actions via porringer.

    Uses the ``execute_stream`` async generator to consume progress events
    and emits per-action progress signals for GUI updates.
    """

    finished = Signal(object)  # SetupResults
    progress = Signal(object, object)  # (SetupAction, SetupActionResult | None)
    error = Signal(str)

    def __init__(
        self,
        porringer: API,
        preview: SetupResults,
        cancellation_token: CancellationToken,
        *,
        project_directory: Path | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            preview: The preview results containing actions and manifest_path.
            cancellation_token: Token for cooperative cancellation.
            project_directory: Working directory for project sync actions.
        """
        super().__init__()
        self._porringer = porringer
        self._preview = preview
        self._cancellation_token = cancellation_token
        self._project_directory = project_directory

    def run(self) -> None:
        """Execute the setup actions on this thread's event loop."""
        try:
            results = asyncio.run(self._execute())
            self.finished.emit(results)
        except asyncio.CancelledError:
            self.finished.emit(SetupResults(actions=self._preview.actions))
        except Exception as exc:
            logger.exception('Install execution failed')
            self.error.emit(str(exc))

    async def _execute(self) -> SetupResults:
        """Stream execution events and collect results."""
        previews = BatchSetupResults(manifest_results=[self._preview], failed_paths=[])
        params = SetupParameters(project_directory=self._project_directory)
        collected: list[SetupActionResult] = []

        async for event in self._porringer.sync.execute_stream(previews, params):
            if self._cancellation_token.is_cancelled:
                raise asyncio.CancelledError

            if event.kind == ProgressEventKind.ACTION_COMPLETED and event.result:
                collected.append(event.result)
                self.progress.emit(event.action, event.result)

        return SetupResults(
            actions=self._preview.actions,
            results=collected,
            manifest_path=self._preview.manifest_path,
            metadata=self._preview.metadata,
        )


class CommandListWidget(QScrollArea):
    """Scrollable list of per-action CLI commands with copy buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the command list widget."""
        super().__init__(parent)
        self.setWidgetResizable(True)

    def populate(self, actions: list[SetupAction]) -> None:
        """Build per-action command fields with descriptive labels above each."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(*NO_MARGINS)

        mono = QFont(MONOSPACE_FAMILY, MONOSPACE_SIZE)
        for i, action in enumerate(actions, 1):
            label_text = ACTION_TYPE_LABELS.get(action.action_type, 'Action')
            desc = action.package_description or action.description
            header = QLabel(f'{i}. [{label_text}] {desc}')
            header.setStyleSheet(COMMAND_HEADER_STYLE)
            layout.addWidget(header)

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
            layout.addWidget(row_widget)

        layout.addStretch()
        self.setWidget(container)


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


class InstallPreviewWindow(QMainWindow):
    """Standalone window that previews and executes a URI-based manifest install."""

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
        self._preview: SetupResults | None = None
        self._manifest_path: Path | None = None
        self._temp_dir_path: str | None = None
        self._runner: ThreadRunner | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._cancellation_token: CancellationToken | None = None
        self._completed_count = 0

        # Data model: per-action status separate from widget state
        self._action_statuses: list[str] = []

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

        # Header
        self._url_label = QLabel()
        self._url_label.setWordWrap(True)
        layout.addWidget(self._url_label)

        # Metadata labels (populated after preview completes)
        self._name_label = QLabel()
        self._name_label.setStyleSheet(HEADER_STYLE)
        self._name_label.hide()
        layout.addWidget(self._name_label)

        self._description_label = QLabel()
        self._description_label.setWordWrap(True)
        self._description_label.hide()
        layout.addWidget(self._description_label)

        self._meta_label = QLabel()
        self._meta_label.setStyleSheet(MUTED_STYLE)
        self._meta_label.hide()
        layout.addWidget(self._meta_label)

        # Project directory input
        layout.addLayout(self._init_project_dir_row())

        # Status label (shown during download/preview)
        self._status_label = QLabel()
        layout.addWidget(self._status_label)

        # --- View stack (table / command list) ---
        self._view_stack = QStackedWidget()

        # Page 0: Actions table
        self._table = self._init_actions_table()
        self._view_stack.addWidget(self._table)

        # Page 1: Scrollable command cards
        self._command_list = CommandListWidget()
        self._view_stack.addWidget(self._command_list)

        layout.addWidget(self._view_stack)

        # Button bar
        layout.addLayout(self._init_button_bar())

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

    def _init_button_bar(self) -> QHBoxLayout:
        """Create the bottom button bar."""
        self._toggle_btn = QPushButton('Show Commands')
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.clicked.connect(self._toggle_view)

        button_bar = QHBoxLayout()
        button_bar.addWidget(self._toggle_btn)
        button_bar.addStretch()

        self._install_btn = QPushButton('Install')
        self._install_btn.setEnabled(False)
        self._install_btn.clicked.connect(self._on_install)
        button_bar.addWidget(self._install_btn)

        self._close_btn = QPushButton('Close')
        self._close_btn.clicked.connect(self.close)
        button_bar.addWidget(self._close_btn)

        return button_bar

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
        self._status_label.setText('Loading manifest…')
        self._install_btn.setEnabled(False)

        # Run download + preview on a background thread to keep UI responsive
        preview_worker = PreviewWorker(self._porringer, self._manifest_url, project_directory=self._project_directory)

        preview_worker.preview_ready.connect(self._on_preview_ready)
        preview_worker.action_checked.connect(self._on_action_checked)
        preview_worker.finished.connect(self._on_preview_complete)
        preview_worker.error.connect(self._on_preview_error)

        self._runner = ThreadRunner(preview_worker)
        self._runner.start()

    # --- Preview callbacks ---

    def _on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle a successful preview.

        Args:
            preview: The setup preview results.
            manifest_path: Path to the downloaded manifest file.
            temp_dir_path: Path to the temp directory (kept alive for execution).
        """
        logger.info('Preview ready: %d action(s) from %s', len(preview.actions), manifest_path)
        self._preview = preview
        self._manifest_path = Path(manifest_path)
        # Keep the temp directory alive until the window closes
        self._temp_dir_path = temp_dir_path

        self._show_metadata(preview)

        if not preview.actions:
            self._status_label.setText('No actions to perform — the manifest is empty.')
            return

        self._action_statuses = ['Checking…'] * len(preview.actions)
        self._status_label.setText(f'{len(preview.actions)} action(s) — checking status…')
        self._populate_table(preview.actions)
        self._install_btn.setEnabled(True)

    def _on_preview_error(self, message: str) -> None:
        """Handle a preview error."""
        logger.error('Preview failed: %s', message)
        self._status_label.setText('')
        QMessageBox.critical(self, 'Preview Failed', message)
        logger.info('Closing window due to preview error')
        self.close()

    def _show_metadata(self, preview: SetupResults) -> None:
        """Display manifest metadata labels if available."""
        metadata = preview.metadata
        if not metadata:
            return

        if metadata.name:
            self._name_label.setText(metadata.name)
            self._name_label.show()
            self.setWindowTitle(f'Install Preview — {metadata.name}')
        if metadata.description:
            self._description_label.setText(metadata.description)
            self._description_label.show()

        meta_parts: list[str] = []
        if metadata.author:
            meta_parts.append(f'Author: {metadata.author}')
        if metadata.url:
            meta_parts.append(f'URL: {metadata.url}')
        if meta_parts:
            self._meta_label.setText('  |  '.join(meta_parts))
            self._meta_label.show()

    # --- Dry-run callbacks ---

    def _on_action_checked(self, row: int, result: SetupActionResult) -> None:
        """Update the data model and table row with the dry-run result."""
        label = (result.skip_reason or 'Satisfied') if result.skipped else 'Needed'

        # Update the data model
        if 0 <= row < len(self._action_statuses):
            self._action_statuses[row] = label

        # Update the table display
        item = self._table.item(row, 4)
        if item is None:
            return

        item.setText(label)
        if result.skipped:
            item.setForeground(self.palette().mid())
        else:
            item.setForeground(self.palette().text())

    def _on_preview_complete(self) -> None:
        """Finalize the preview after the dry-run check completes."""
        if self._preview is None or not self._preview.actions:
            return

        # Resolve any still-pending statuses as 'Needed'
        for i, status in enumerate(self._action_statuses):
            if status == 'Checking…':
                self._action_statuses[i] = 'Needed'
                item = self._table.item(i, 4)
                if item is not None:
                    item.setText('Needed')
                    item.setForeground(self.palette().text())

        total = len(self._action_statuses)
        needed = sum(1 for s in self._action_statuses if s == 'Needed')
        satisfied = total - needed

        if needed == 0:
            self._status_label.setText(f'{total} action(s) — all already satisfied.')
            self._install_btn.setEnabled(False)
        else:
            self._status_label.setText(f'{total} action(s): {needed} needed, {satisfied} already satisfied.')

        logger.info(
            'Preview complete: %d total, %d needed, %d satisfied (window visible=%s)',
            total,
            needed,
            satisfied,
            self.isVisible(),
        )

    # --- View toggle ---

    def _toggle_view(self) -> None:
        """Switch between overview table and command list."""
        if self._view_stack.currentIndex() == 0:
            self._view_stack.setCurrentIndex(1)
            self._toggle_btn.setText('Show Overview')
        else:
            self._view_stack.setCurrentIndex(0)
            self._toggle_btn.setText('Show Commands')

    # --- Table / command list ---

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
        """Fill the actions table from a list of SetupAction objects."""
        self._table.setRowCount(len(actions))
        for row, action in enumerate(actions):
            self._table.setItem(row, 0, QTableWidgetItem(ACTION_TYPE_LABELS.get(action.action_type, '?')))
            self._table.setItem(row, 1, QTableWidgetItem(action.installer or ''))
            self._table.setItem(row, 2, QTableWidgetItem(str(action.package) if action.package else ''))
            self._table.setItem(row, 3, QTableWidgetItem(action.package_description or action.description))

            status_item = QTableWidgetItem('Checking…')
            status_item.setForeground(self.palette().placeholderText())
            self._table.setItem(row, 4, status_item)

        self._command_list.populate(actions)
        self._toggle_btn.setEnabled(True)

    # --- Install execution ---

    def _on_install(self) -> None:
        """Handle the Install button click."""
        if self._preview is None or self._manifest_path is None:
            return

        self._install_btn.setEnabled(False)
        self._completed_count = 0

        total = len(self._preview.actions)
        self._cancellation_token = CancellationToken()

        # Progress dialog
        self._progress_dialog = QProgressDialog(
            'Starting install…',
            'Cancel',
            0,
            total,
            self,
        )
        self._progress_dialog.setWindowTitle('Installing')
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.canceled.connect(self._on_cancel)
        self._progress_dialog.show()

        # Worker thread
        worker = InstallWorker(
            self._porringer,
            self._preview,
            self._cancellation_token,
            project_directory=self._project_directory,
        )
        worker.progress.connect(self._on_action_progress)
        worker.finished.connect(self._on_install_finished)
        worker.error.connect(self._on_install_error)

        self._runner = ThreadRunner(worker)
        self._runner.start()

    def _on_action_progress(self, action: SetupAction, result: SetupActionResult) -> None:
        """Handle a single action completion from the worker."""
        self._completed_count += 1
        label = action.description
        if result.skipped:
            label += f' (skipped: {result.skip_reason})'
        elif not result.success:
            label += f' (FAILED: {result.message})'

        if self._progress_dialog:
            self._progress_dialog.setValue(self._completed_count)
            self._progress_dialog.setLabelText(label)

    def _on_cancel(self) -> None:
        """Handle cancel button on the progress dialog."""
        if self._cancellation_token:
            self._cancellation_token.cancel()

    def _on_install_finished(self, results: SetupResults) -> None:
        """Handle install completion."""
        self._cleanup_progress()

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
        if failed:
            QMessageBox.warning(self, 'Install Complete', summary)
        else:
            QMessageBox.information(self, 'Install Complete', summary)

        self._status_label.setText(f'Done — {summary}')
        self._install_btn.setEnabled(False)

    def _on_install_error(self, message: str) -> None:
        """Handle install error."""
        self._cleanup_progress()
        QMessageBox.critical(self, 'Install Failed', message)
        self._install_btn.setEnabled(True)

    def _cleanup_progress(self) -> None:
        """Close the progress dialog."""
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None


class PreviewWorker(QObject):
    """Background worker that downloads a manifest, previews actions, and checks status.

    Combines three stages into a single background pipeline:

    1. Download the manifest (if remote).
    2. Run ``preview_single`` to list intended actions.
    3. Perform a ``dry_run`` to determine which actions are already satisfied.
    """

    preview_ready = Signal(object, str, str)  # (SetupResults, manifest_path, temp_dir_path)
    action_checked = Signal(int, object)  # (row_index, SetupActionResult)
    finished = Signal()
    error = Signal(str)

    def __init__(self, porringer: API, url: str, *, project_directory: Path | None = None) -> None:
        """Initialize the preview worker."""
        super().__init__()
        self._porringer = porringer
        self._url = url
        self._project_directory = project_directory

    def run(self) -> None:
        """Download the manifest, preview actions, and check status via dry-run."""
        logger.info('PreviewWorker starting for: %s', self._url)
        temp_dir = None
        try:
            local_path = resolve_local_path(self._url)

            if local_path is not None:
                # Local file — skip the download entirely
                if not local_path.exists():
                    self.error.emit(f'Manifest not found:\n{local_path}')
                    return
                preview = self._porringer.sync.preview_single(local_path)
                self.preview_ready.emit(preview, str(local_path), '')
            else:
                # Remote URL — download to a temp directory
                temp_dir = tempfile.mkdtemp(prefix='synodic_install_')
                dest = Path(temp_dir) / 'porringer.json'

                params = DownloadParameters(url=self._url, destination=dest, timeout=3)
                result = self._porringer.sync.download(params)

                if not result.success:
                    _safe_rmtree(temp_dir)
                    self.error.emit(f'Failed to download manifest:\n{result.message}')
                    return

                preview = self._porringer.sync.preview_single(dest)
                self.preview_ready.emit(preview, str(dest), temp_dir)

            # Dry-run to check which actions are already satisfied
            if preview.actions:
                self._run_dry_check(preview)

            self.finished.emit()

        except Exception as exc:
            if temp_dir:
                _safe_rmtree(temp_dir)
            logger.exception('Preview failed')
            self.error.emit(str(exc))

    def _run_dry_check(self, preview: SetupResults) -> None:
        """Perform a dry-run and emit per-action status signals."""
        try:
            asyncio.run(self._check(preview))
        except Exception as exc:
            logger.warning('Dry-run check failed: %s', exc)

    async def _check(self, preview: SetupResults) -> None:
        """Stream dry-run events and emit per-action results."""
        previews = BatchSetupResults(manifest_results=[preview], failed_paths=[])
        params = SetupParameters(dry_run=True, project_directory=self._project_directory)
        action_indices: dict[int, int] = {id(a): i for i, a in enumerate(preview.actions)}

        async for event in self._porringer.sync.execute_stream(previews, params):
            if event.kind == ProgressEventKind.ACTION_COMPLETED and event.result and event.action:
                row = action_indices.get(id(event.action))
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
