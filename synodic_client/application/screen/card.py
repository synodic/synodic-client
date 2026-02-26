"""Reusable card frame and clickable header widgets.

:class:`CardFrame` provides a styled, optionally collapsible container
for grouping related UI elements.  :class:`ClickableHeader` extracts the
ad-hoc clickable-header pattern used in log panels and plugin sections
into a proper widget with a ``clicked`` signal.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from synodic_client.application.theme import (
    CARD_FRAME_STYLE,
    CARD_HEADER_STYLE,
    LOG_CHEVRON_STYLE,
    NO_MARGINS,
)

# Unicode chevrons
CHEVRON_DOWN = '\u25bc'
CHEVRON_RIGHT = '\u25b6'


class ClickableHeader(QWidget):
    """A clickable header widget with an optional chevron for collapse/expand.

    Emits :attr:`clicked` on mouse press and sets a pointing-hand cursor.
    Callers supply *object_name* and *stylesheet* to control appearance.
    """

    clicked = Signal()

    def __init__(
        self,
        object_name: str,
        stylesheet: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the header.

        Args:
            object_name: ``QObject`` name (for CSS selectors).
            stylesheet: Stylesheet applied to this widget.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setStyleSheet(stylesheet)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

    # --- Layout access ---------------------------------------------------

    @property
    def header_layout(self) -> QHBoxLayout:
        """Return the header's horizontal layout for adding child widgets."""
        return self._layout

    # --- Event handling ---------------------------------------------------

    def mousePressEvent(self, _event: object) -> None:
        """Emit :attr:`clicked` on any mouse press."""
        self.clicked.emit()


class CardFrame(QFrame):
    """A rounded-border card container with an optional title and collapse.

    When *collapsible* is ``True`` the title becomes a
    :class:`ClickableHeader` and clicking it toggles the content area.
    Use :meth:`content_layout` to add child widgets.
    """

    def __init__(
        self,
        title: str = '',
        *,
        collapsible: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the card.

        Args:
            title: Optional heading text shown at the top of the card.
            collapsible: When ``True``, the title row toggles content
                visibility on click.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName('card')
        self.setStyleSheet(CARD_FRAME_STYLE)
        self._expanded = True
        self._collapsible = collapsible

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*NO_MARGINS)
        outer.setSpacing(4)

        # --- Optional title / header -----------------------------------------
        self._chevron: QLabel | None = None
        if title:
            if collapsible:
                header = ClickableHeader('cardHeader', '', parent=self)
                header.clicked.connect(self._toggle)

                self._chevron = QLabel(CHEVRON_DOWN)
                self._chevron.setStyleSheet(LOG_CHEVRON_STYLE)
                self._chevron.setFixedWidth(14)
                header.header_layout.addWidget(self._chevron)

                label = QLabel(title)
                label.setStyleSheet(CARD_HEADER_STYLE)
                header.header_layout.addWidget(label)
                header.header_layout.addStretch()
                outer.addWidget(header)
            else:
                label = QLabel(title)
                label.setStyleSheet(CARD_HEADER_STYLE)
                outer.addWidget(label)

        # --- Content area -----------------------------------------------------
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(*NO_MARGINS)
        self._content_layout.setSpacing(4)
        outer.addWidget(self._content)

    # --- Public API -----------------------------------------------------------

    @property
    def content_layout(self) -> QVBoxLayout:
        """Return the inner layout for adding child widgets to the card."""
        return self._content_layout

    # --- Collapse / expand ----------------------------------------------------

    def _toggle(self) -> None:
        """Toggle the content area visibility."""
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        if self._chevron is not None:
            self._chevron.setText(CHEVRON_DOWN if self._expanded else CHEVRON_RIGHT)
