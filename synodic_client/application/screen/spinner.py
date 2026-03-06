"""Animated loading spinner widgets.

Provides :class:`SpinnerCanvas` — a lightweight, palette-aware spinning
arc that can be sized and styled for any context — and
:class:`SpinnerWidget` — a self-positioning overlay variant with an
optional text label.

:class:`SpinnerCanvas` is used directly in plugin rows and action cards
where only a small inline indicator is needed.  :class:`SpinnerWidget`
wraps a canvas and centres itself over its parent for modal-style use.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

_DEFAULT_SIZE = 24
_DEFAULT_PEN = 3
_INTERVAL = 50
_ARC = 90
_FULL_CIRCLE = 360


class SpinnerCanvas(QWidget):
    """Fixed-size widget that paints a spinning arc.

    Fully parameterised so that different call-sites can share the
    identical paint logic with varying dimensions.

    Args:
        size: Diameter of the spinner in pixels.
        pen_width: Stroke width for the arc.
        interval: Timer tick interval in milliseconds.
        parent: Optional parent widget.
    """

    def __init__(
        self,
        size: int = _DEFAULT_SIZE,
        pen_width: int = _DEFAULT_PEN,
        interval: int = _INTERVAL,
        parent: QWidget | None = None,
    ) -> None:
        """Create a spinner canvas.

        Args:
            size: Diameter of the spinner in pixels.
            pen_width: Stroke width for the arc.
            interval: Timer tick interval in milliseconds.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._angle = 0
        self._size = size
        self._pen_width = pen_width
        self._interval = interval
        self.setFixedSize(size, size)

    def paintEvent(self, _event: object) -> None:
        """Draw a muted track circle and the animated highlight arc."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        m = self._pen_width // 2 + 1
        rect = QRect(m, m, self._size - 2 * m, self._size - 2 * m)

        for colour, span in ((self.palette().mid(), _FULL_CIRCLE), (self.palette().highlight(), _ARC)):
            pen = QPen(colour, self._pen_width)
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

    When a *parent* is provided the widget configures itself as a
    floating overlay that fills the parent's geometry automatically.
    No ``resizeEvent`` override, ``setSizePolicy``, ``raise_()``, or
    ``lower()`` call is needed by the consumer — just ``start()`` and
    ``stop()``.
    """

    def __init__(self, text: str = '', parent: QWidget | None = None) -> None:
        """Initialize the spinner.

        Args:
            text: Optional label shown beside the spinner arc.
            parent: Optional parent widget.  When set, the spinner
                becomes a floating overlay that tracks the parent size.
        """
        super().__init__(parent)
        self.hide()

        self._canvas = SpinnerCanvas(parent=self)
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

        # Auto-overlay: track parent geometry via event filter
        if parent is not None:
            self.setAutoFillBackground(True)
            self.setStyleSheet('background: palette(window);')
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())

    # -- Event filter (overlay geometry tracking) --------------------------

    def eventFilter(self, obj: object, event: QEvent) -> bool:
        """Resize to match the parent whenever it resizes."""
        parent = self.parent()
        if event.type() == QEvent.Type.Resize and obj is parent and isinstance(parent, QWidget):
            self.setGeometry(parent.rect())
        return False

    # -- Public API --------------------------------------------------------

    def start(self) -> None:
        """Show the overlay and start the animation."""
        self.raise_()
        self.show()
        self._canvas._angle = 0
        self._timer.start()

    def stop(self) -> None:
        """Stop the animation, hide, and move below siblings."""
        self._timer.stop()
        self.hide()
        self.lower()
