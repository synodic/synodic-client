"""Screen class for the Synodic Client application."""

from __future__ import annotations

import logging
from pathlib import Path

from porringer.api import API
from porringer.schema import ListPluginsParameters
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen.install import PreviewWorker, SetupPreviewWidget
from synodic_client.application.theme import COMPACT_MARGINS, MAIN_WINDOW_MIN_SIZE
from synodic_client.application.threading import ThreadRunner

logger = logging.getLogger(__name__)


class PluginsView(QWidget):
    """Widget displaying cached plugin manifests."""

    def __init__(self, porringer: API, parent: QWidget | None = None) -> None:
        """Initialize the plugins view.

        Args:
            porringer: The porringer API instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*COMPACT_MARGINS)

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(['Name', 'Version'])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table)

    def refresh(self) -> None:
        """Refresh the plugin data from porringer."""
        self._table.setRowCount(0)

        params = ListPluginsParameters()
        plugins = self._porringer.plugin.list(params)

        self._table.setRowCount(len(plugins))
        for row, plugin in enumerate(plugins):
            name_item = QTableWidgetItem(plugin.name)
            version_item = QTableWidgetItem(str(plugin.tool_version) if plugin.tool_version else 'Not found')
            version_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, version_item)


class ProjectsView(QWidget):
    """Widget for managing project directories and previewing their manifests.

    Combines a cached-directory selector (editable ``QComboBox`` with
    Browse) and a :class:`SetupPreviewWidget` for dry-run preview and
    install execution.
    """

    def __init__(self, porringer: API, parent: QWidget | None = None) -> None:
        """Initialize the projects view.

        Args:
            porringer: The porringer API instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._runner: ThreadRunner | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*COMPACT_MARGINS)

        # --- Project directory selector ---
        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 8)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setToolTip('Select a cached project directory or enter a new path')
        self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(40)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        selector_row.addWidget(self._combo, 1)

        self._browse_btn = QPushButton('Browse…')
        self._browse_btn.clicked.connect(self._on_browse)
        selector_row.addWidget(self._browse_btn)

        self._remove_btn = QPushButton('Remove')
        self._remove_btn.setToolTip('Remove the selected directory from the cache')
        self._remove_btn.clicked.connect(self._on_remove)
        self._remove_btn.setEnabled(False)
        selector_row.addWidget(self._remove_btn)

        layout.addLayout(selector_row)

        # --- Shared preview widget ---
        self._preview = SetupPreviewWidget(self._porringer, self, show_close=False)
        self._preview.install_finished.connect(self._on_install_finished)
        layout.addWidget(self._preview)

    # --- Public API ---

    def refresh(self) -> None:
        """Refresh the cached directories combo box from porringer cache."""
        self._combo.blockSignals(True)
        current_text = self._combo.currentText()
        self._combo.clear()

        directories = self._porringer.cache.list_directories()
        for directory in directories:
            display = str(directory.path)
            tooltip = directory.name or ''
            exists = Path(directory.path).is_dir()

            idx = self._combo.count()
            self._combo.addItem(display)
            self._combo.setItemData(idx, tooltip, Qt.ItemDataRole.ToolTipRole)
            self._combo.setItemData(idx, str(directory.path), Qt.ItemDataRole.UserRole)

            if not exists:
                # Grey out entries whose directory no longer exists on disk
                item = self._combo.model().item(idx)  # type: ignore[union-attr]
                if isinstance(item, QStandardItem):
                    item.setForeground(self.palette().placeholderText())
                    item.setToolTip(f'{tooltip} \u2014 directory not found' if tooltip else 'Directory not found')

        # Restore previous selection if it still exists
        idx = self._combo.findText(current_text)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        elif self._combo.count() > 0:
            self._combo.setCurrentIndex(0)

        self._combo.blockSignals(False)
        self._update_remove_btn()

        # Trigger preview for the current selection
        if self._combo.currentText():
            self._load_preview()

    # --- Event handlers ---

    def _on_selection_changed(self, _index: int) -> None:
        """Handle combo box selection changes."""
        self._update_remove_btn()
        if self._combo.currentText():
            self._load_preview()

    def _on_browse(self) -> None:
        """Open a directory picker and set the combo text."""
        chosen = QFileDialog.getExistingDirectory(
            self,
            'Select Project Directory',
            self._combo.currentText() or '',
            QFileDialog.Option.ShowDirsOnly,
        )
        if chosen:
            self._combo.setEditText(chosen)
            self._load_preview()

    def _on_remove(self) -> None:
        """Remove the currently selected directory from the cache."""
        idx = self._combo.currentIndex()
        if idx < 0:
            return

        path_str = self._combo.itemData(idx, Qt.ItemDataRole.UserRole)
        if path_str:
            self._porringer.cache.remove_directory(Path(path_str))

        self.refresh()

    def _on_install_finished(self, _results: object) -> None:
        """Register a new path in the cache after successful install."""
        current_text = self._combo.currentText().strip()
        if not current_text:
            return

        # Only register if the path isn't already in the combo's cached items
        idx = self._combo.findText(current_text)
        item_data = self._combo.itemData(idx, Qt.ItemDataRole.UserRole) if idx >= 0 else None
        if item_data is None:
            try:
                self._porringer.cache.add_directory(Path(current_text))
                logger.info('Registered new project directory: %s', current_text)
                self.refresh()
            except ValueError:
                logger.debug('Directory already cached or invalid: %s', current_text)

    # --- Preview loading ---

    def _load_preview(self) -> None:
        """Run a dry-run preview for the currently selected path."""
        path_text = self._combo.currentText().strip()
        if not path_text:
            return

        project_path = Path(path_text)
        manifest_path = project_path / 'porringer.json'

        self._preview.reset()

        if not project_path.is_dir():
            self._preview.show_not_found(f'Directory not found: {project_path}')
            return

        self._preview.set_project_directory(project_path)

        preview_worker = PreviewWorker(
            self._porringer,
            str(manifest_path),
            project_directory=project_path,
        )
        preview_worker.preview_ready.connect(self._preview.on_preview_ready)
        preview_worker.action_checked.connect(self._preview.on_action_checked)
        preview_worker.finished.connect(self._preview.on_preview_finished)
        preview_worker.error.connect(self._on_preview_error)

        self._runner = ThreadRunner(preview_worker)
        self._runner.start()

    def _on_preview_error(self, message: str) -> None:
        """Handle preview errors inline instead of showing a modal dialog."""
        logger.warning('Preview error: %s', message)
        self._preview.show_not_found(message)

    def _update_remove_btn(self) -> None:
        """Enable the Remove button only for cached (non-freeform) entries."""
        idx = self._combo.currentIndex()
        has_data = idx >= 0 and self._combo.itemData(idx, Qt.ItemDataRole.UserRole) is not None
        self._remove_btn.setEnabled(has_data)


class MainWindow(QMainWindow):
    """Main window for the application."""

    _tabs: QTabWidget | None = None
    _plugins_view: PluginsView | None = None
    _projects_view: ProjectsView | None = None

    def __init__(self, porringer: API | None = None) -> None:
        """Initialize the main window.

        Args:
            porringer: Optional porringer API instance for manifest display.
        """
        super().__init__()
        self._porringer = porringer
        self.setWindowTitle('Synodic Client')
        self.setMinimumSize(*MAIN_WINDOW_MIN_SIZE)

    @property
    def porringer(self) -> API | None:
        """Return the porringer API instance, if available."""
        return self._porringer

    def show(self) -> None:
        """Show the window, initializing UI lazily on first show."""
        if self._tabs is None and self._porringer is not None:
            self._tabs = QTabWidget(self)

            self._projects_view = ProjectsView(self._porringer, self)
            self._tabs.addTab(self._projects_view, 'Projects')

            self._plugins_view = PluginsView(self._porringer, self)
            self._tabs.addTab(self._plugins_view, 'Plugins')

            self.setCentralWidget(self._tabs)

        # Refresh both views
        if self._plugins_view is not None:
            self._plugins_view.refresh()
        if self._projects_view is not None:
            self._projects_view.refresh()

        super().show()


class Screen:
    """Screen class for the Synodic Client application."""

    _window: MainWindow | None = None

    def __init__(self, porringer: API | None = None) -> None:
        """Initialize the screen.

        Args:
            porringer: Optional porringer API instance.
        """
        self._porringer = porringer

    @property
    def window(self) -> MainWindow:
        """Lazily create the main window on first access.

        Returns:
            The MainWindow instance.
        """
        if self._window is None:
            self._window = MainWindow(self._porringer)
        return self._window
