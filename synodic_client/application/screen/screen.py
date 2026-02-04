"""Screen class for the Synodic Client application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from porringer.schema import ListPluginsParameters
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from porringer.api import API


class ManifestView(QWidget):
    """Widget displaying cached plugin manifests."""

    def __init__(self, porringer: API, parent: QWidget | None = None) -> None:
        """Initialize the manifest view.

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
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(['Name', 'Version', 'Status'])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)

        # Make columns stretch to fill available space
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table)

    def refresh(self) -> None:
        """Refresh the manifest data from porringer."""
        self._table.setRowCount(0)

        params = ListPluginsParameters()
        plugins = self._porringer.plugin.list(params)

        self._table.setRowCount(len(plugins))
        for row, plugin in enumerate(plugins):
            name_item = QTableWidgetItem(plugin.name)
            version_item = QTableWidgetItem(str(plugin.version))
            status_item = QTableWidgetItem('Installed' if plugin.installed else 'Not Installed')

            # Center align version and status
            version_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, version_item)
            self._table.setItem(row, 2, status_item)


class MainWindow(QMainWindow):
    """Main window for the application."""

    _manifest_view: ManifestView | None = None

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
        if self._manifest_view is None and self._porringer is not None:
            self._manifest_view = ManifestView(self._porringer, self)
            self.setCentralWidget(self._manifest_view)
            self._manifest_view.refresh()
        elif self._manifest_view is not None:
            self._manifest_view.refresh()

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
