"""Install preview window for URI-based manifest installs.

Displays a dry-run preview of porringer setup actions and lets the user
confirm execution.  Execution runs on a background ``QThread`` with a
cancellable ``QProgressDialog``.

.. note:: QThread worker pattern

   Workers moved to a ``QThread`` via ``moveToThread()`` **must** be stored
   as instance attributes (``self._worker``), never as local variables.
   A local reference will be garbage-collected before the thread starts,
   silently preventing execution.
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
    CancellationToken,
    DownloadParameters,
    SetupAction,
    SetupActionType,
    SetupParameters,
    SetupResults,
    ThreadSafeProgressAdapter,
)
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from porringer.api import API

logger = logging.getLogger(__name__)

ACTION_TYPE_LABELS = {
    SetupActionType.CHECK_PLUGIN: 'Check Plugin',
    SetupActionType.INSTALL_PACKAGE: 'Install Package',
    SetupActionType.RUN_COMMAND: 'Run Command',
}


class InstallWorker(QObject):
    """Background worker that executes setup actions via porringer."""

    finished = Signal(object)  # SetupResults
    error = Signal(str)

    def __init__(
        self,
        porringer: API,
        actions: list[SetupAction],
        manifest_path: Path,
        adapter: ThreadSafeProgressAdapter,
        cancellation_token: CancellationToken,
    ) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            actions: Previewed actions to execute.
            manifest_path: Path to the downloaded manifest.
            adapter: Thread-safe progress adapter for GUI updates.
            cancellation_token: Token for cooperative cancellation.
        """
        super().__init__()
        self._porringer = porringer
        self._actions = actions
        self._manifest_path = manifest_path
        self._adapter = adapter
        self._cancellation_token = cancellation_token

    def run(self) -> None:
        """Execute the setup actions on this thread's event loop."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(
                    self._porringer.update.execute_single_async(
                        self._actions,
                        self._manifest_path,
                        SetupParameters(),
                        progress_callback=self._adapter.callback,
                        cancellation_token=self._cancellation_token,
                    )
                )
                self.finished.emit(results)
            finally:
                loop.close()
        except asyncio.CancelledError:
            # Cancellation is expected — emit an empty result
            self.finished.emit(SetupResults(actions=self._actions))
        except Exception as exc:
            logger.exception('Install execution failed')
            self.error.emit(str(exc))


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
        self._thread: QThread | None = None
        self._worker: InstallWorker | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._cancellation_token: CancellationToken | None = None
        self._progress_timer: QTimer | None = None
        self._completed_count = 0

        self.setWindowTitle('Install Preview')
        self.setMinimumSize(650, 400)

        self._init_ui()

    def _init_ui(self) -> None:
        """Build the UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)

        # Header
        self._url_label = QLabel()
        self._url_label.setWordWrap(True)
        layout.addWidget(self._url_label)

        # Status label (shown during download/preview)
        self._status_label = QLabel()
        layout.addWidget(self._status_label)

        # Actions table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(['Type', 'Plugin', 'Package', 'Description'])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        # Button bar
        button_bar = QHBoxLayout()
        button_bar.addStretch()

        self._install_btn = QPushButton('Install')
        self._install_btn.setEnabled(False)
        self._install_btn.clicked.connect(self._on_install)
        button_bar.addWidget(self._install_btn)

        self._close_btn = QPushButton('Close')
        self._close_btn.clicked.connect(self.close)
        button_bar.addWidget(self._close_btn)

        layout.addLayout(button_bar)

    # --- Lifecycle ---

    def closeEvent(self, event: Any) -> None:
        """Clean up the temp directory when the window is closed."""
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
        self._url_label.setText(f'<b>Manifest:</b> {self._manifest_url}')
        self._status_label.setText('Loading manifest…')
        self._install_btn.setEnabled(False)

        # Run download + preview on a background thread to keep UI responsive
        self._thread = QThread()
        self._preview_worker = PreviewWorker(self._porringer, self._manifest_url)
        self._preview_worker.moveToThread(self._thread)

        self._thread.started.connect(self._preview_worker.run)
        self._preview_worker.finished.connect(self._on_preview_ready)
        self._preview_worker.error.connect(self._on_preview_error)
        self._preview_worker.finished.connect(self._thread.quit)
        self._preview_worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._preview_worker.deleteLater)

        self._thread.start()

    # --- Preview callbacks ---

    def _on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Handle a successful preview.

        Args:
            preview: The setup preview results.
            manifest_path: Path to the downloaded manifest file.
            temp_dir_path: Path to the temp directory (kept alive for execution).
        """
        self._preview = preview
        self._manifest_path = Path(manifest_path)
        # Keep the temp directory alive until the window closes
        self._temp_dir_path = temp_dir_path

        if not preview.actions:
            self._status_label.setText('No actions to perform — the manifest is empty.')
            return

        self._status_label.setText(f'{len(preview.actions)} action(s) will be performed:')
        self._populate_table(preview.actions)
        self._install_btn.setEnabled(True)

    def _on_preview_error(self, message: str) -> None:
        """Handle a preview error."""
        self._status_label.setText('')
        QMessageBox.critical(self, 'Preview Failed', message)
        self.close()

    # --- Table ---

    def _populate_table(self, actions: list[SetupAction]) -> None:
        """Fill the actions table from a list of SetupAction objects."""
        self._table.setRowCount(len(actions))
        for row, action in enumerate(actions):
            self._table.setItem(row, 0, QTableWidgetItem(ACTION_TYPE_LABELS.get(action.action_type, '?')))
            self._table.setItem(row, 1, QTableWidgetItem(action.plugin or ''))
            self._table.setItem(row, 2, QTableWidgetItem(action.package or ''))
            self._table.setItem(row, 3, QTableWidgetItem(action.description))

    # --- Install execution ---

    def _on_install(self) -> None:
        """Handle the Install button click."""
        if self._preview is None or self._manifest_path is None:
            return

        self._install_btn.setEnabled(False)
        self._completed_count = 0

        total = len(self._preview.actions)
        self._cancellation_token = CancellationToken()
        adapter = ThreadSafeProgressAdapter()

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

        # Poll the adapter periodically from the GUI thread
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(100)
        self._progress_timer.timeout.connect(lambda: self._drain_progress(adapter))
        self._progress_timer.start()

        # Worker thread
        self._thread = QThread()
        self._worker = InstallWorker(
            self._porringer,
            self._preview.actions,
            self._manifest_path,
            adapter,
            self._cancellation_token,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_install_finished)
        self._worker.error.connect(self._on_install_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._worker.deleteLater)

        self._thread.start()

    def _drain_progress(self, adapter: ThreadSafeProgressAdapter) -> None:
        """Process queued progress updates from the adapter."""
        for action, result in adapter.drain():
            self._completed_count += 1
            label = action.description
            if result and result.skipped:
                label += f' (skipped: {result.skip_reason})'
            elif result and not result.success:
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
        """Stop the progress timer and close the dialog."""
        if self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer = None
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None


class PreviewWorker(QObject):
    """Background worker that downloads a manifest and runs a preview."""

    finished = Signal(object, str, str)  # (SetupResults, manifest_path, temp_dir_path)
    error = Signal(str)

    def __init__(self, porringer: API, url: str) -> None:
        """Initialize the preview worker."""
        super().__init__()
        self._porringer = porringer
        self._url = url

    def run(self) -> None:
        """Download the manifest (if remote) and preview setup actions."""
        temp_dir = None
        try:
            local_path = resolve_local_path(self._url)

            if local_path is not None:
                # Local file — skip the download entirely
                if not local_path.exists():
                    self.error.emit(f'Manifest not found:\n{local_path}')
                    return
                preview = self._porringer.update.preview_single(local_path)
                self.finished.emit(preview, str(local_path), '')
            else:
                # Remote URL — download to a temp directory
                temp_dir = tempfile.mkdtemp(prefix='synodic_install_')
                dest = Path(temp_dir) / 'porringer.json'

                params = DownloadParameters(url=self._url, destination=dest, timeout=3)
                result = self._porringer.update.download(params)

                if not result.success:
                    _safe_rmtree(temp_dir)
                    self.error.emit(f'Failed to download manifest:\n{result.message}')
                    return

                preview = self._porringer.update.preview_single(dest)
                self.finished.emit(preview, str(dest), temp_dir)

        except Exception as exc:
            if temp_dir:
                _safe_rmtree(temp_dir)
            logger.exception('Preview failed')
            self.error.emit(str(exc))


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
