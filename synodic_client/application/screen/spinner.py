"""Animated loading spinner widget.

Provides :class:`SpinnerWidget` — a palette-aware spinning arc with an
optional text label.  Call ``start()`` to show and ``stop()`` to hide.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

_SIZE = 24
_PEN = 3
_INTERVAL = 50
_ARC = 90
_FULL_CIRCLE = 360


class _Canvas(QWidget):
    """Fixed-size widget that paints the spinning arc."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(_SIZE, _SIZE)

    def paintEvent(self, _event: object) -> None:
        """Draw a muted track circle and the animated highlight arc."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        m = _PEN // 2 + 1
        rect = QRect(m, m, _SIZE - 2 * m, _SIZE - 2 * m)

        for colour, span in ((self.palette().mid(), _FULL_CIRCLE), (self.palette().highlight(), _ARC)):
            pen = QPen(colour, _PEN)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            if span == _FULL_CIRCLE:
                painter.drawEllipse(rect)
            else:
                painter.drawArc(rect, self._angle * 16, span * 16)

        painter.end()

    def tick(self) -> None:
        """Advance the arc and repaint."""
        self._angle = (self._angle - 10) % 360
        self.update()


class SpinnerWidget(QWidget):
    """Animated spinner circle with optional text label.

    The widget centres itself in whatever space the parent layout
    provides — callers just need ``layout.addWidget(spinner)`` (with an
    optional stretch factor for vertical centering in empty areas).
    """

    def __init__(self, text: str = '', parent: QWidget | None = None) -> None:
        """Initialize the spinner.

        Args:
            text: Optional label shown beside the spinner arc.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.hide()

        self._canvas = _Canvas(self)
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL)
        self._timer.timeout.connect(self._canvas.tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        row.addWidget(self._canvas)
        self._label = QLabel(text)
        if text:
            row.addWidget(self._label)
        row.addStretch()

        outer.addLayout(row)
        outer.addStretch()

    def start(self) -> None:
        """Show the widget and start the animation."""
        self.show()
        self._canvas._angle = 0
        self._timer.start()

    def stop(self) -> None:
        """Stop the animation and hide the widget."""
        self._timer.stop()
        self.hide()
