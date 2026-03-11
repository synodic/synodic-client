"""Collapsible execution log panel for install operations.

Provides :class:`ExecutionLogPanel`, a container of
:class:`ActionLogSection` widgets — one per setup action.  Each section
has a collapsible header (default: open) with a status badge and a
monospace output area that receives colour-coded stdout/stderr lines.

Scrolling is handled by the parent :class:`QScrollArea` in
:class:`~synodic_client.application.screen.install.SetupPreviewWidget`.
"""

from __future__ import annotations

import html
import logging

from porringer.schema import SetupAction, SetupActionResult, SubActionProgress
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen import ACTION_KIND_LABELS, skip_reason_label
from synodic_client.application.screen.card import CHEVRON_DOWN, CHEVRON_RIGHT, ClickableHeader
from synodic_client.application.theme import (
    LOG_CHEVRON_STYLE,
    LOG_COLOR_ERROR,
    LOG_COLOR_PHASE,
    LOG_COLOR_STDERR,
    LOG_COLOR_STDOUT,
    LOG_COLOR_SUCCESS,
    LOG_OUTPUT_STYLE,
    LOG_SECTION_HEADER_STYLE,
    LOG_SECTION_TITLE_STYLE,
    LOG_STATUS_FAILED,
    LOG_STATUS_RUNNING,
    LOG_STATUS_SKIPPED,
    LOG_STATUS_SUCCESS,
    MONOSPACE_FAMILY,
    MONOSPACE_SIZE,
    NO_MARGINS,
)

logger = logging.getLogger(__name__)


class ActionLogSection(QWidget):
    """A single collapsible action log section.

    Shows a clickable header with chevron + action description + status badge,
    and a monospace ``QTextEdit`` body that displays colour-coded output lines.
    """

    def __init__(self, action: SetupAction, index: int, parent: QWidget | None = None) -> None:
        """Initialise the section.

        Args:
            action: The setup action this section represents.
            index: 1-based display index.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._action = action
        self._expanded = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(0)

        # --- Header ---
        self._header = ClickableHeader('sectionHeader', LOG_SECTION_HEADER_STYLE, parent=self)
        self._header.clicked.connect(self._toggle)

        header_layout = self._header.header_layout

        self._chevron = QLabel(CHEVRON_DOWN)
        self._chevron.setStyleSheet(LOG_CHEVRON_STYLE)
        self._chevron.setFixedWidth(14)
        header_layout.addWidget(self._chevron)

        kind_label = ACTION_KIND_LABELS.get(action.kind, 'Action')
        desc = action.package_description or action.description
        title = QLabel(f'{index}. [{kind_label}] {desc}')
        title.setStyleSheet(LOG_SECTION_TITLE_STYLE)
        header_layout.addWidget(title, stretch=1)

        self._status_label = QLabel('Running…')
        self._status_label.setStyleSheet(LOG_STATUS_RUNNING)
        header_layout.addWidget(self._status_label)

        layout.addWidget(self._header)

        # --- Output body ---
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont(MONOSPACE_FAMILY, MONOSPACE_SIZE))
        self._output.setStyleSheet(LOG_OUTPUT_STYLE)
        self._output.setMinimumHeight(60)
        self._output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._output.setFixedHeight(60)
        self._output.document().contentsChanged.connect(self._update_output_height)
        layout.addWidget(self._output)

    # --- Public API ---

    def append_output(self, text: str, stream: str | None = None) -> None:
        """Append a line of output with stream-appropriate colouring.

        Args:
            text: The output line text.
            stream: ``'stdout'``, ``'stderr'``, or ``None`` for phase messages.
        """
        colour = LOG_COLOR_STDOUT
        if stream == 'stderr':
            colour = LOG_COLOR_STDERR
        elif stream is None:
            colour = LOG_COLOR_PHASE

        escaped = html.escape(text)
        self._output.append(f'<span style="color: {colour};">{escaped}</span>')

        # Auto-scroll to bottom
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._output.setTextCursor(cursor)

    def set_result(self, result: SetupActionResult) -> None:
        """Update the section header with the final action result.

        Args:
            result: The action result.
        """
        if result.skipped:
            label = skip_reason_label(result.skip_reason)
            self._status_label.setText(label)
            self._status_label.setStyleSheet(LOG_STATUS_SKIPPED)
            self.append_output(f'⏭ Skipped: {label}', None)
        elif result.success:
            self._status_label.setText('Done')
            self._status_label.setStyleSheet(LOG_STATUS_SUCCESS)
            msg = result.message or 'Completed successfully'
            self._output.append(f'<span style="color: {LOG_COLOR_SUCCESS};">✓ {html.escape(msg)}</span>')
        else:
            self._status_label.setText('Failed')
            self._status_label.setStyleSheet(LOG_STATUS_FAILED)
            msg = result.message or 'Unknown error'
            self._output.append(f'<span style="color: {LOG_COLOR_ERROR};">✗ {html.escape(msg)}</span>')

    # --- Collapse / expand ---

    def _toggle(self) -> None:
        """Toggle the output body visibility."""
        self._expanded = not self._expanded
        self._output.setVisible(self._expanded)
        self._chevron.setText(CHEVRON_DOWN if self._expanded else CHEVRON_RIGHT)

    def _update_output_height(self) -> None:
        """Resize the output QTextEdit to fit its content."""
        doc_height = int(self._output.document().size().height())
        frame = self._output.frameWidth() * 2
        self._output.setFixedHeight(max(60, doc_height + frame))


class ExecutionLogPanel(QWidget):
    """Container of :class:`ActionLogSection` widgets.

    Used as the execution view during install operations.  Sections are
    added dynamically as ``ACTION_STARTED`` events arrive.  Scrolling
    is handled by the parent scroll area.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the log panel."""
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._layout.addStretch()

        # Map action content-key → section widget for quick lookup
        self._sections: dict[SetupAction, ActionLogSection] = {}
        self._section_count = 0

    # --- Public API ---

    def add_section(self, action: SetupAction) -> ActionLogSection:
        """Add a new collapsible section for an action.

        Args:
            action: The setup action starting execution.

        Returns:
            The created section widget.
        """
        self._section_count += 1
        section = ActionLogSection(action, self._section_count, self)
        # Insert before the stretch
        self._layout.insertWidget(self._layout.count() - 1, section)
        self._sections[action] = section

        return section

    def get_section(self, action: SetupAction) -> ActionLogSection | None:
        """Look up the section widget for a given action.

        Args:
            action: The setup action to look up.

        Returns:
            The section widget, or ``None`` if not found.
        """
        return self._sections.get(action)

    def on_sub_progress(self, action: SetupAction, progress: SubActionProgress) -> None:
        """Handle a sub-action progress event.

        Routes output lines and phase messages to the correct section.

        Args:
            action: The parent action.
            progress: The sub-action progress update.
        """
        section = self.get_section(action)
        if section is None:
            return

        if progress.output is not None:
            section.append_output(progress.output, progress.stream)
        elif progress.message is not None:
            section.append_output(progress.message)

    def on_action_completed(self, action: SetupAction, result: SetupActionResult) -> None:
        """Handle an action completion event.

        Args:
            action: The completed action.
            result: The action result.
        """
        section = self.get_section(action)
        if section is not None:
            section.set_result(result)

    def clear(self) -> None:
        """Remove all sections."""
        for section in self._sections.values():
            self._layout.removeWidget(section)
            section.deleteLater()
        self._sections.clear()
        self._section_count = 0
