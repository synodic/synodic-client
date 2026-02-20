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
    SkipReason,
    SubActionProgress,
    SyncStrategy,
)
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
from synodic_client.config import GlobalConfiguration, save_config

#: Amber foreground for "Update available" status cells.
_UPDATE_AVAILABLE_COLOR = QColor('#d7ba7d')

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

    def __init__(  # noqa: PLR0913
        self,
        porringer: API,
        manifest_path: Path,
        cancellation_token: CancellationToken,
        *,
        project_directory: Path | None = None,
        strategy: SyncStrategy = SyncStrategy.MINIMAL,
        prerelease_packages: set[str] | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            manifest_path: Path to the manifest file to execute.
            cancellation_token: Token for cooperative cancellation.
            project_directory: Working directory for project sync actions.
            strategy: Sync strategy — ``LATEST`` when upgrades are pending.
            prerelease_packages: Package names whose ``include_prereleases``
                flag should be forced to ``True``, overriding the manifest
                default.
        """
        super().__init__()
        self._porringer = porringer
        self._manifest_path = manifest_path
        self._cancellation_token = cancellation_token
        self._project_directory = project_directory
        self._strategy = strategy
        self._prerelease_packages = prerelease_packages

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
            strategy=self._strategy,
            prerelease_packages=self._prerelease_packages,
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

    #: Emitted when per-item pre-release overrides change (debounced).
    prerelease_changed = Signal()

    def __init__(
        self,
        porringer: API,
        parent: QWidget | None = None,
        *,
        show_close: bool = True,
        config: GlobalConfiguration | None = None,
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
        self._action_statuses: list[str] = []
        self._upgradable_rows: set[int] = set()
        self._action_to_table_row: dict[int, int] = {}
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
        self._init_metadata_card()
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

    def _init_actions_table(self) -> QTableWidget:
        """Create and configure the actions table widget."""
        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(
            ['Type', 'Plugin', 'Package', 'Version', 'Description', 'Status', 'Pre-release'],
        )
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, table, self._copy_table_selection)
        copy_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
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
        self._action_statuses = []
        self._upgradable_rows = set()
        self._action_to_table_row = {}
        self._plugin_installed = {}
        self._prerelease_overrides = set()
        self._installing = False
        self._prerelease_debounce.stop()

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

        pkgs = self._config.prerelease_packages or {}
        if self._prerelease_overrides:
            pkgs[self._manifest_key] = sorted(self._prerelease_overrides)
        else:
            pkgs.pop(self._manifest_key, None)

        self._config.prerelease_packages = pkgs if pkgs else None
        save_config(self._config)
        logger.info('Pre-release overrides for %s: %s', self._manifest_key, self._prerelease_overrides)

        if not self._installing:
            self.prerelease_changed.emit()

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
        if result.skipped and result.skip_reason == SkipReason.UPDATE_AVAILABLE:
            label = skip_reason_label(result.skip_reason)
            color = _UPDATE_AVAILABLE_COLOR
            self._upgradable_rows.add(row)
        elif result.skipped:
            label = skip_reason_label(result.skip_reason)
            color = self.palette().placeholderText().color()
        else:
            label = 'Needed'
            color = self.palette().text().color()

        if 0 <= row < len(self._action_statuses):
            self._action_statuses[row] = label

        # Command actions are not shown in the table.
        table_row = self._action_to_table_row.get(row)
        if table_row is None:
            return

        # --- Version column (col 3) ---
        version_item = self._table.item(table_row, 3)
        if version_item is not None:
            if result.installed_version and result.available_version:
                version_item.setText(f'{result.installed_version} \u2192 {result.available_version}')
                version_item.setForeground(_UPDATE_AVAILABLE_COLOR)
            elif result.installed_version:
                version_item.setText(result.installed_version)
                version_item.setForeground(self.palette().text())

        # --- Status column (col 5) ---
        item = self._table.item(table_row, 5)
        if item is None:
            return

        item.setText(label)
        item.setForeground(color)

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
                    item = self._table.item(table_row, 5)
                    if item is not None:
                        item.setText('Needed')
                        item.setForeground(self.palette().text())

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
            self._status_label.setText(f'{total} action(s) — all already satisfied.')
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

            # Version column — populated later by on_action_checked
            version_item = QTableWidgetItem('')
            version_item.setForeground(self.palette().placeholderText())
            self._table.setItem(table_row, 3, version_item)

            self._table.setItem(table_row, 4, QTableWidgetItem(action.package_description or action.description))

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
            self._table.setItem(table_row, 5, status_item)

            # Per-row pre-release checkbox (only for actions with a package)
            if action.package is not None:
                cb = QCheckBox()
                pkg_name = str(action.package.name)
                is_user_override = pkg_name.lower() in self._prerelease_overrides
                if action.include_prereleases and not is_user_override:
                    # Manifest already enables pre-releases — show checked and locked
                    cb.setChecked(True)
                    cb.setEnabled(False)
                    cb.setToolTip('Enabled by manifest')
                else:
                    # User-togglable: either an explicit override or default off
                    cb.setChecked(is_user_override)
                    cb.setToolTip('Include pre-release versions for this package')
                    cb.toggled.connect(lambda checked, name=pkg_name: self._on_prerelease_row_toggled(name, checked))

                # Centre the checkbox in the cell
                wrapper = QWidget()
                layout = QHBoxLayout(wrapper)
                layout.addWidget(cb)
                layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.setContentsMargins(0, 0, 0, 0)
                self._table.setCellWidget(table_row, 6, wrapper)

        # Populate the always-visible post-install commands section
        self._post_install_section.populate(actions)

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

        # Show the execution log card below the actions card
        self._log_panel.clear()
        self._log_card.show()
        self._status_label.setText('Installing…')

        # Choose LATEST strategy when there are upgradable actions so
        # porringer actually upgrades the already-installed packages.
        strategy = SyncStrategy.LATEST if self._upgradable_rows else SyncStrategy.MINIMAL

        # Worker thread
        worker = InstallWorker(
            self._porringer,
            self._manifest_path,
            self._cancellation_token,
            project_directory=self._project_directory,
            strategy=strategy,
            prerelease_packages=self._prerelease_overrides or None,
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
        """Update the status and version cells for a table row from an action result."""
        item = self._table.item(row, 5)
        if item is None:
            return

        if result.skipped:
            item.setText(skip_reason_label(result.skip_reason))
            item.setForeground(self.palette().placeholderText())
        elif result.success:
            item.setText('Done')
            item.setForeground(self.palette().text())

            # When an upgrade completes, update the Version column to show
            # the new version instead of the stale transition arrow.
            version_item = self._table.item(row, 3)
            if version_item is not None and result.available_version:
                version_item.setText(result.available_version)
                version_item.setForeground(self.palette().text())
        else:
            item.setText(f'Failed: {result.message}' if result.message else 'Failed')
            item.setForeground(self.palette().text())

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
        self._status_label.setText(f'Done — {summary}')
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
        config: GlobalConfiguration | None = None,
    ) -> None:
        """Initialize the install preview window.

        Args:
            porringer: The porringer API instance.
            manifest_url: The URL of the manifest to install.
            parent: Optional parent widget.
            config: Resolved global configuration for per-manifest pre-release
                state and update detection flags.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._manifest_url = manifest_url
        self._config = config or GlobalConfiguration()
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
        overrides = set((self._config.prerelease_packages or {}).get(manifest_key, []))

        preview_worker = PreviewWorker(
            self._porringer,
            self._manifest_url,
            project_directory=self._project_directory,
            detect_updates=self._config.detect_updates,
            prerelease_packages=overrides or None,
        )

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
    2. Run ``execute_stream`` with ``dry_run=True`` to list actions and check status.
    """

    preview_ready = Signal(object, str, str)  # (SetupResults, manifest_path, temp_dir_path)
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
            detect_updates=self._detect_updates,
            prerelease_packages=self._prerelease_packages,
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
