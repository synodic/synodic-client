"""Screen class for the Synodic Client application."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from porringer.schema import ListPluginsParameters
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from porringer.api import API


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
        layout.setContentsMargins(8, 8, 8, 8)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(['Name', 'Version', 'Status'])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table)

    def refresh(self) -> None:
        """Refresh the plugin data from porringer."""
        self._table.setRowCount(0)

        params = ListPluginsParameters()
        plugins = self._porringer.plugin.list(params)

        self._table.setRowCount(len(plugins))
        for row, plugin in enumerate(plugins):
            name_item = QTableWidgetItem(plugin.name)
            version_item = QTableWidgetItem(str(plugin.version))
            status_item = QTableWidgetItem('Installed' if plugin.installed else 'Not Installed')

            version_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, version_item)
            self._table.setItem(row, 2, status_item)


class DirectoriesView(QWidget):
    """Widget for managing cached manifest directories."""

    def __init__(self, porringer: API, parent: QWidget | None = None) -> None:
        """Initialize the directories view.

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
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar with add/remove buttons
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 8)

        self._add_btn = QPushButton('Add Directory')
        self._add_btn.clicked.connect(self._on_add_directory)
        toolbar.addWidget(self._add_btn)

        self._remove_btn = QPushButton('Remove')
        self._remove_btn.clicked.connect(self._on_remove_directory)
        self._remove_btn.setEnabled(False)
        toolbar.addWidget(self._remove_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Directories table
        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(['Path', 'Name'])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table)

    def refresh(self) -> None:
        """Refresh the directories list from porringer cache."""
        self._table.setRowCount(0)

        directories = self._porringer.cache.list_directories()

        self._table.setRowCount(len(directories))
        for row, directory in enumerate(directories):
            path_item = QTableWidgetItem(str(directory.path))
            name_item = QTableWidgetItem(directory.name or '')

            # Store the path in the item data for removal
            path_item.setData(Qt.ItemDataRole.UserRole, directory.path)

            self._table.setItem(row, 0, path_item)
            self._table.setItem(row, 1, name_item)

        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        """Update button states based on selection."""
        self._remove_btn.setEnabled(len(self._table.selectedItems()) > 0)

    def _on_add_directory(self) -> None:
        """Handle add directory button click."""
        directory = QFileDialog.getExistingDirectory(
            self,
            'Select Manifest Directory',
            '',
            QFileDialog.Option.ShowDirsOnly,
        )

        if not directory:
            return

        try:
            path = Path(directory)
            self._porringer.cache.add_directory(path)
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(
                self,
                'Add Directory Failed',
                str(e),
            )

    def _on_remove_directory(self) -> None:
        """Handle remove directory button click."""
        selected_rows = set(item.row() for item in self._table.selectedItems())

        for row in selected_rows:
            path_item = self._table.item(row, 0)
            if path_item:
                path = path_item.data(Qt.ItemDataRole.UserRole)
                if path:
                    self._porringer.cache.remove_directory(path)

        self.refresh()


class MainWindow(QMainWindow):
    """Main window for the application."""

    _tabs: QTabWidget | None = None
    _plugins_view: PluginsView | None = None
    _directories_view: DirectoriesView | None = None

    def __init__(self, porringer: API | None = None) -> None:
        """Initialize the main window.

        Args:
            porringer: Optional porringer API instance for manifest display.
        """
        super().__init__()
        self._porringer = porringer
        self.setWindowTitle('Synodic Client')
        self.setMinimumSize(600, 400)

    def show(self) -> None:
        """Show the window, initializing UI lazily on first show."""
        if self._tabs is None and self._porringer is not None:
            self._tabs = QTabWidget(self)

            self._plugins_view = PluginsView(self._porringer, self)
            self._tabs.addTab(self._plugins_view, 'Plugins')

            self._directories_view = DirectoriesView(self._porringer, self)
            self._tabs.addTab(self._directories_view, 'Directories')

            self.setCentralWidget(self._tabs)

        # Refresh both views
        if self._plugins_view is not None:
            self._plugins_view.refresh()
        if self._directories_view is not None:
            self._directories_view.refresh()

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
