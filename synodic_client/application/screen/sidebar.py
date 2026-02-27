"""Manifest sidebar — a vertical panel for selecting cached project directories.

:class:`ManifestItem` renders a single directory as a row with an inline
close button visible on hover.  :class:`ManifestSidebar` manages a
scrollable column of items plus an *Add* button, emitting signals for
selection, removal, and addition.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen.install import PreviewPhase
from synodic_client.application.theme import (
    SIDEBAR_ADD_STYLE,
    SIDEBAR_CLOSE_STYLE,
    SIDEBAR_HEADER_STYLE,
    SIDEBAR_ITEM_DIMMED_STYLE,
    SIDEBAR_ITEM_HEIGHT,
    SIDEBAR_ITEM_SELECTED_STYLE,
    SIDEBAR_ITEM_STYLE,
    SIDEBAR_LABEL_DIMMED_STYLE,
    SIDEBAR_LABEL_STYLE,
    SIDEBAR_PHASE_DONE_STYLE,
    SIDEBAR_PHASE_ERROR_STYLE,
    SIDEBAR_PHASE_INSTALLING_STYLE,
    SIDEBAR_PHASE_LOADING_STYLE,
    SIDEBAR_PHASE_READY_STYLE,
    SIDEBAR_SPACING,
    SIDEBAR_STYLE,
    SIDEBAR_WIDTH,
)

logger = logging.getLogger(__name__)

_PHASE_LABELS: dict[PreviewPhase, tuple[str, str]] = {
    PreviewPhase.LOADING: ('Loading…', SIDEBAR_PHASE_LOADING_STYLE),
    PreviewPhase.PREVIEWING: ('Checking…', SIDEBAR_PHASE_LOADING_STYLE),
    PreviewPhase.READY: ('Ready', SIDEBAR_PHASE_READY_STYLE),
    PreviewPhase.INSTALLING: ('Installing…', SIDEBAR_PHASE_INSTALLING_STYLE),
    PreviewPhase.DONE: ('Done', SIDEBAR_PHASE_DONE_STYLE),
    PreviewPhase.ERROR: ('Error', SIDEBAR_PHASE_ERROR_STYLE),
}


class ManifestItem(QFrame):
    """A sidebar row representing a single cached project directory.

    Emits :attr:`clicked` when the item body is pressed and
    :attr:`remove_requested` when the close button is pressed.
    """

    clicked = Signal(Path)
    """Emitted with the directory path when the item is clicked."""

    remove_requested = Signal(Path)
    """Emitted with the directory path when the × button is clicked."""

    def __init__(
        self,
        path: Path,
        name: str = '',
        *,
        valid: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the item.

        Args:
            path: Absolute path to the project directory.
            name: Optional human-readable name (falls back to last path component).
            valid: When ``False`` the item renders dimmed.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName('sidebarItem')
        self._path = path
        self._name = name
        self._valid = valid
        self._selected = False

        self.setFixedHeight(SIDEBAR_ITEM_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        display = name or path.name or str(path)
        self._label = QLabel(display)
        self._label.setStyleSheet(SIDEBAR_LABEL_STYLE if valid else SIDEBAR_LABEL_DIMMED_STYLE)
        self._label.setToolTip(str(path))
        layout.addWidget(self._label, stretch=1)

        # Phase indicator (updated externally)
        self._phase_label = QLabel()
        self._phase_label.hide()
        layout.addWidget(self._phase_label)

        self._close_btn = QPushButton('\u00d7')  # ×
        self._close_btn.setFixedSize(18, 18)
        self._close_btn.setStyleSheet(SIDEBAR_CLOSE_STYLE)
        self._close_btn.setToolTip('Remove from cache')
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self._on_close)
        layout.addWidget(self._close_btn)

        self.setToolTip(str(path))

    # --- Properties -------------------------------------------------------

    @property
    def path(self) -> Path:
        """Return the project directory path."""
        return self._path

    @property
    def selected(self) -> bool:
        """Return whether this item is currently selected."""
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        """Set the selected state and update styling."""
        self._selected = value
        self._apply_style()

    # --- Public API -------------------------------------------------------

    def set_phase(self, phase: PreviewPhase) -> None:
        """Update the phase indicator label."""
        info = _PHASE_LABELS.get(phase)
        if info is not None:
            text, style = info
            self._phase_label.setText(text)
            self._phase_label.setStyleSheet(style)
            self._phase_label.show()
        else:
            self._phase_label.hide()

    # --- Styling -----------------------------------------------------------

    def _apply_style(self) -> None:
        """Apply the appropriate stylesheet based on state."""
        if self._selected:
            self.setStyleSheet(SIDEBAR_ITEM_SELECTED_STYLE)
        elif not self._valid:
            self.setStyleSheet(SIDEBAR_ITEM_DIMMED_STYLE)
        else:
            self.setStyleSheet(SIDEBAR_ITEM_STYLE)

    # --- Events ------------------------------------------------------------

    def mousePressEvent(self, _event: object) -> None:
        """Emit :attr:`clicked` on mouse press."""
        self.clicked.emit(self._path)

    def _on_close(self) -> None:
        """Emit :attr:`remove_requested` when the × button is clicked."""
        self.remove_requested.emit(self._path)


class ManifestSidebar(QWidget):
    """Vertical sidebar for managing cached project directories.

    Displays a scrollable column of :class:`ManifestItem` widgets with
    a trailing *Add* button.  Emits signals for user interactions.
    """

    selection_changed = Signal(Path)
    """Emitted with the directory path when an item is clicked."""

    remove_requested = Signal(Path)
    """Emitted with the directory path when an item's close button is clicked."""

    add_requested = Signal()
    """Emitted when the Add (+) button is clicked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the sidebar."""
        super().__init__(parent)
        self._items: list[ManifestItem] = []
        self._selected_path: Path | None = None

        self.setFixedWidth(SIDEBAR_WIDTH)

        frame = QFrame(self)
        frame.setObjectName('sidebar')
        frame.setStyleSheet(SIDEBAR_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(frame)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 8, 8, 8)
        frame_layout.setSpacing(SIDEBAR_SPACING)

        # Header
        header = QLabel('PROJECTS')
        header.setStyleSheet(SIDEBAR_HEADER_STYLE)
        frame_layout.addWidget(header)

        # Scroll area for the items
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._container = QWidget()
        self._column = QVBoxLayout(self._container)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(SIDEBAR_SPACING)
        self._column.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._column.addStretch()

        self._scroll.setWidget(self._container)
        frame_layout.addWidget(self._scroll, stretch=1)

        # Add (+) button at the bottom
        self._add_btn = QPushButton('+  Add Project')
        self._add_btn.setStyleSheet(SIDEBAR_ADD_STYLE)
        self._add_btn.setToolTip('Add a manifest')
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(self.add_requested.emit)
        frame_layout.addWidget(self._add_btn)

    # --- Public API --------------------------------------------------------

    @property
    def selected_path(self) -> Path | None:
        """Return the currently selected directory path."""
        return self._selected_path

    def set_directories(
        self,
        directories: list[tuple[Path, str, bool]],
    ) -> None:
        """Rebuild all items from a list of ``(path, name, valid)`` tuples.

        Any previous selection is **not** restored — callers should call
        :meth:`select` afterwards if desired.
        """
        # Remove existing items
        for item in self._items:
            self._column.removeWidget(item)
            item.deleteLater()
        self._items.clear()
        self._selected_path = None

        # Insert new items before the trailing stretch
        for insert_idx, (path, name, valid) in enumerate(directories):
            item = ManifestItem(path, name, valid=valid, parent=self._container)
            item.clicked.connect(self._on_item_clicked)
            item.remove_requested.connect(self._on_item_remove)
            self._column.insertWidget(insert_idx, item)
            self._items.append(item)

    def select(self, path: Path | None) -> None:
        """Programmatically select an item by path.

        If *path* is ``None`` or not found, the first item (if any) is
        selected instead.
        """
        # Build a fast lookup: exact path → item, resolved path → item
        exact: dict[Path, ManifestItem] = {i.path: i for i in self._items}

        target: Path | None = None
        if path is not None:
            if path in exact:
                target = path
            else:
                resolved = path.resolve()
                for item in self._items:
                    if item.path.resolve() == resolved:
                        target = item.path
                        break

        if target is None and self._items:
            target = self._items[0].path

        self._selected_path = target
        for item in self._items:
            item.selected = item.path == target

        if target is not None:
            self.selection_changed.emit(target)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the add button and all items."""
        self._add_btn.setEnabled(enabled)
        for item in self._items:
            item.setEnabled(enabled)

    def get_item(self, path: Path) -> ManifestItem | None:
        """Return the :class:`ManifestItem` for *path*, or ``None``."""
        for item in self._items:
            if item.path == path:
                return item
        return None

    # --- Internal slots ----------------------------------------------------

    def _on_item_clicked(self, path: Path) -> None:
        """Handle an item click — update selection and emit signal."""
        self._selected_path = path
        for item in self._items:
            item.selected = item.path == path
        self.selection_changed.emit(path)

    def _on_item_remove(self, path: Path) -> None:
        """Forward the remove request signal."""
        self.remove_requested.emit(path)
