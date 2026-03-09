"""Animated loading spinner widgets.

Provides :class:`SpinnerCanvas` — a lightweight, palette-aware spinning
arc that can be sized and styled for any context — and
:class:`LoadingIndicator` — a centred spinner-plus-label widget suited
for embedding in layouts as a loading placeholder.

:class:`SpinnerCanvas` is used directly in plugin rows and action cards
where only a small inline indicator is needed.  :class:`LoadingIndicator`
wraps a canvas with an optional label and is designed to be placed into
a ``QStackedWidget`` page or swapped with content by the consumer.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from synodic_client.application.theme import LOADING_LABEL_STYLE

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


class LoadingIndicator(QWidget):
    """Centred spinner arc with an optional text label.

    Designed to be placed into a layout — for example as a page in a
    ``QStackedWidget`` or shown/hidden alongside content.  The widget
    expands to fill available space and centres its contents.

    The consumer is responsible for swapping visibility or stack pages;
    this component manages only its own animation and display state.

    Typical usage::

        indicator = LoadingIndicator('Loading…')
        stack.addWidget(indicator)

        # begin loading
        indicator.start()
        stack.setCurrentWidget(indicator)

        # finish loading
        indicator.stop()
        stack.setCurrentWidget(content)
    """

    def __init__(self, text: str = '', parent: QWidget | None = None) -> None:
        """Create a loading indicator.

        Args:
            text: Optional label shown beside the spinner arc.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.hide()

        self._canvas = SpinnerCanvas(parent=self)
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL)
        self._timer.timeout.connect(self._canvas.tick)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        row.addWidget(self._canvas)
        self._label = QLabel(text)
        self._label.setStyleSheet(LOADING_LABEL_STYLE)
        if text:
            row.addWidget(self._label)
        row.addStretch()

        outer.addLayout(row)
        outer.addStretch()

    # -- Public API --------------------------------------------------------

    @property
    def running(self) -> bool:
        """Return ``True`` if the animation is currently active."""
        return self._timer.isActive()

    def set_text(self, text: str) -> None:
        """Update the label text."""
        self._label.setText(text)
        self._label.setVisible(bool(text))

    def start(self) -> None:
        """Reset the arc angle, start the animation, and show the widget."""
        self._canvas._angle = 0
        self._timer.start()
        self.show()

    def stop(self) -> None:
        """Stop the animation and hide the widget."""
        self._timer.stop()
        self.hide()
