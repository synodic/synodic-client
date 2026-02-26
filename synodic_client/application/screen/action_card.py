"""Action card widgets for the install preview screen.

Replaces the previous ``QTableWidget`` + ``ExecutionLogPanel`` layout
with compact, self-contained cards — one per setup action.  Each card
shows essential information (package name, type, version, status) and
expands inline to display execution output during install.

:class:`ActionCard` is the per-action widget.
:class:`ActionCardList` is the scrollable container that holds them.
"""

from __future__ import annotations

import html as html_mod
import logging

from porringer.backend.command.core.action_builder import PHASE_ORDER
from porringer.schema import SetupAction, SetupActionResult, SkipReason
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen import ACTION_KIND_LABELS, skip_reason_label
from synodic_client.application.theme import (
    ACTION_CARD_COMMAND_STYLE,
    ACTION_CARD_DESC_STYLE,
    ACTION_CARD_EXECUTING_STYLE,
    ACTION_CARD_LOG_STYLE,
    ACTION_CARD_PACKAGE_STYLE,
    ACTION_CARD_SKELETON_BAR_STYLE,
    ACTION_CARD_SKELETON_STYLE,
    ACTION_CARD_SPACING,
    ACTION_CARD_SPINNER_PEN,
    ACTION_CARD_SPINNER_SIZE,
    ACTION_CARD_STATUS_DONE,
    ACTION_CARD_STATUS_FAILED,
    ACTION_CARD_STATUS_NEEDED,
    ACTION_CARD_STATUS_RUNNING,
    ACTION_CARD_STATUS_SATISFIED,
    ACTION_CARD_STATUS_SKIPPED,
    ACTION_CARD_STATUS_UNAVAILABLE,
    ACTION_CARD_STATUS_UPDATE,
    ACTION_CARD_STYLE,
    ACTION_CARD_TYPE_BADGE_STYLE,
    ACTION_CARD_VERSION_STYLE,
    COPY_BTN_SIZE,
    COPY_BTN_STYLE,
    COPY_FEEDBACK_MS,
    COPY_ICON,
    LOG_COLOR_ERROR,
    LOG_COLOR_PHASE,
    LOG_COLOR_STDERR,
    LOG_COLOR_STDOUT,
    LOG_COLOR_SUCCESS,
    MONOSPACE_FAMILY,
    MONOSPACE_SIZE,
)

logger = logging.getLogger(__name__)

#: Amber foreground for "Update available" version transitions.
_UPDATE_AVAILABLE_COLOR = QColor('#d7ba7d')

#: Timer interval for per-card inline spinner (ms).
_SPINNER_INTERVAL = 50

#: Arc span for per-card spinner (degrees × 16 for Qt drawArc).
_SPINNER_ARC = 90


#: Sort priority derived from porringer's execution phase order so the
#: display order always matches the order actions actually execute.
_KIND_ORDER: dict[PluginKind | None, int] = {kind: i for i, kind in enumerate(PHASE_ORDER)}


def action_key(action: SetupAction) -> tuple[object, ...]:
    """Return a stable identity key for *action*.

    Uses content-based fields (kind, installer, package name, command)
    so the same logical action from different ``execute_stream`` runs
    resolves to the same key.
    """
    pkg_name = str(action.package.name) if action.package else None
    pt_name = str(action.plugin_target.name) if action.plugin_target else None
    cmd = tuple(action.command) if action.command else None
    return (action.kind, action.installer, pkg_name, pt_name, cmd)


def action_sort_key(action: SetupAction) -> int:
    """Return a sort key that groups cards by execution phase.

    The ordering is derived from :data:`porringer.backend.command.core.
    action_builder.PHASE_ORDER` so that displayed cards appear in the
    same sequence as they execute.  Within a phase group the original
    order from porringer is preserved (Python sort is stable), which
    respects dependency ordering (e.g. a tool must be installed before
    its plugins).
    """
    return _KIND_ORDER.get(action.kind, len(PHASE_ORDER))


def _format_command(action: SetupAction) -> str:
    """Return a short CLI command string for display."""
    if parts := (action.cli_command or action.command):
        return ' '.join(parts)
    if action.kind == PluginKind.PACKAGE and action.package:
        return f'{action.installer or "pip"} install {action.package}'
    return ''


# ---------------------------------------------------------------------------
# _CardSpinner — tiny per-card inline spinner
# ---------------------------------------------------------------------------


class _CardSpinner(QWidget):
    """Tiny spinning arc used inside an :class:`ActionCard` while checking.

    The spinner replaces the status text label during the dry-run check
    phase and is hidden once the result arrives.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(ACTION_CARD_SPINNER_SIZE, ACTION_CARD_SPINNER_SIZE)

    def paintEvent(self, _event: object) -> None:
        """Draw the muted track and animated highlight arc."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        m = ACTION_CARD_SPINNER_PEN // 2 + 1
        rect = QRect(m, m, self.width() - 2 * m, self.height() - 2 * m)

        # Track circle
        track_pen = QPen(self.palette().mid(), ACTION_CARD_SPINNER_PEN)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(rect)

        # Highlight arc
        hl_pen = QPen(self.palette().highlight(), ACTION_CARD_SPINNER_PEN)
        hl_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(hl_pen)
        painter.drawArc(rect, self._angle * 16, _SPINNER_ARC * 16)

        painter.end()

    def tick(self) -> None:
        """Advance the arc and repaint."""
        self._angle = (self._angle - 10) % 360
        self.update()


# ---------------------------------------------------------------------------
# ActionCard — a single action row
# ---------------------------------------------------------------------------


class ActionCard(QFrame):
    """Compact card displaying a single setup action.

    The card has three visual states:

    * **preview** — shows package name, type badge, description, CLI
      command, version, and dry-run status.  The inline log is hidden.
    * **executing** — highlighted border, status shows "Running\u2026",
      inline log body is visible and receives real-time output.
    * **completed** — status updated to Done / Failed / Skipped, log body
      remains visible (collapsed by default after completion).

    A **skeleton** variant shows muted placeholder bars and is used
    while the manifest is still loading.

    Each card has a tiny inline spinner that replaces the status text
    while the dry-run check is in progress.
    """

    prerelease_toggled = Signal(str, bool)
    """Emitted with ``(package_name, checked)`` when the user toggles the
    per-row pre-release checkbox."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        skeleton: bool = False,
    ) -> None:
        """Initialise the card.

        Args:
            parent: Optional parent widget.
            skeleton: When ``True`` the card shows placeholder bars with
                no real content.
        """
        super().__init__(parent)
        self.setObjectName('actionCard')
        self._action: SetupAction | None = None
        self._is_skeleton = skeleton
        self._log_expanded = False
        self._checking = False
        self._check_available_version: str | None = None

        if skeleton:
            self._init_skeleton_ui()
        else:
            self._init_real_ui()

    # ------------------------------------------------------------------
    # Skeleton UI
    # ------------------------------------------------------------------

    def _init_skeleton_ui(self) -> None:
        """Build the placeholder skeleton layout."""
        self.setStyleSheet(ACTION_CARD_SKELETON_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)

        # Placeholder bars
        bar1 = QFrame()
        bar1.setObjectName('skeletonBar')
        bar1.setStyleSheet(ACTION_CARD_SKELETON_BAR_STYLE)
        bar1.setFixedSize(50, 14)
        row.addWidget(bar1)

        bar2 = QFrame()
        bar2.setObjectName('skeletonBar')
        bar2.setStyleSheet(ACTION_CARD_SKELETON_BAR_STYLE)
        bar2.setFixedSize(120, 14)
        row.addWidget(bar2)

        row.addStretch()

        bar3 = QFrame()
        bar3.setObjectName('skeletonBar')
        bar3.setStyleSheet(ACTION_CARD_SKELETON_BAR_STYLE)
        bar3.setFixedSize(70, 14)
        row.addWidget(bar3)

        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        bar4 = QFrame()
        bar4.setObjectName('skeletonBar')
        bar4.setStyleSheet(ACTION_CARD_SKELETON_BAR_STYLE)
        bar4.setFixedSize(200, 12)
        row2.addWidget(bar4)
        row2.addStretch()
        layout.addLayout(row2)

    # ------------------------------------------------------------------
    # Real UI
    # ------------------------------------------------------------------

    def _init_real_ui(self) -> None:
        """Build the action card layout."""
        self.setStyleSheet(ACTION_CARD_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(2)

        outer.addLayout(self._build_top_row())
        outer.addWidget(self._build_description_row())
        outer.addWidget(self._build_command_row())
        outer.addWidget(self._build_log_output())

    def _build_top_row(self) -> QHBoxLayout:
        """Build the top row: type badge | package name ... version | status/spinner | prerelease."""
        top = QHBoxLayout()
        top.setSpacing(8)

        self._type_badge = QLabel()
        self._type_badge.setStyleSheet(ACTION_CARD_TYPE_BADGE_STYLE)
        top.addWidget(self._type_badge)

        self._package_label = QLabel()
        self._package_label.setStyleSheet(ACTION_CARD_PACKAGE_STYLE)
        self._package_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
        )
        top.addWidget(self._package_label)

        top.addStretch()

        self._version_label = QLabel()
        self._version_label.setStyleSheet(ACTION_CARD_VERSION_STYLE)
        top.addWidget(self._version_label)

        # Inline spinner (replaces status text while checking)
        self._spinner_canvas = _CardSpinner(self)
        self._spinner_canvas.hide()
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(_SPINNER_INTERVAL)
        self._spinner_timer.timeout.connect(self._spinner_canvas.tick)
        top.addWidget(self._spinner_canvas)

        self._status_label = QLabel()
        top.addWidget(self._status_label)

        self._prerelease_cb = QCheckBox('Pre-release')
        self._prerelease_cb.hide()
        top.addWidget(self._prerelease_cb)

        return top

    def _build_description_row(self) -> QLabel:
        """Build the description label."""
        self._desc_label = QLabel()
        self._desc_label.setStyleSheet(ACTION_CARD_DESC_STYLE)
        self._desc_label.setWordWrap(True)
        self._desc_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
        )
        return self._desc_label

    def _build_command_row(self) -> QWidget:
        """Build the CLI command row with copy button."""
        self._command_row = QWidget()
        cmd_layout = QHBoxLayout(self._command_row)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(4)

        self._command_label = QLabel()
        self._command_label.setStyleSheet(ACTION_CARD_COMMAND_STYLE)
        self._command_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
        )
        cmd_layout.addWidget(self._command_label)

        self._copy_btn = QToolButton()
        self._copy_btn.setText(COPY_ICON)
        self._copy_btn.setToolTip('Copy to clipboard')
        self._copy_btn.setFixedSize(*COPY_BTN_SIZE)
        self._copy_btn.setStyleSheet(COPY_BTN_STYLE)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.clicked.connect(self._copy_command)
        cmd_layout.addWidget(self._copy_btn)

        cmd_layout.addStretch()

        self._command_row.hide()
        return self._command_row

    def _build_log_output(self) -> QTextEdit:
        """Build the inline log body (hidden by default)."""
        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setFont(QFont(MONOSPACE_FAMILY, MONOSPACE_SIZE))
        self._log_output.setStyleSheet(ACTION_CARD_LOG_STYLE)
        self._log_output.setMinimumHeight(40)
        self._log_output.setMaximumHeight(250)
        self._log_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._log_output.hide()
        return self._log_output

    # ------------------------------------------------------------------
    # Mouse events (toggle log)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: object) -> None:
        """Toggle the inline log body on click."""
        if self._is_skeleton or not hasattr(self, '_log_output'):
            return
        # Don't toggle the log when clicking interactive child widgets
        if hasattr(self, '_copy_btn') and self._copy_btn.underMouse():
            return
        if hasattr(self, '_package_label') and self._package_label.underMouse():
            return
        if hasattr(self, '_desc_label') and self._desc_label.underMouse():
            return
        self._toggle_log()

    def _toggle_log(self) -> None:
        """Expand or collapse the inline log body."""
        self._log_expanded = not self._log_expanded
        self._log_output.setVisible(self._log_expanded)

    def _copy_command(self) -> None:
        """Copy the command label text to the clipboard with brief feedback."""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._command_label.text())
        self._copy_btn.setText('\u2713')
        self._copy_btn.setToolTip('Copied!')

        def _restore() -> None:
            try:
                self._copy_btn.setText(COPY_ICON)
                self._copy_btn.setToolTip('Copy to clipboard')
            except RuntimeError:
                pass

        QTimer.singleShot(COPY_FEEDBACK_MS, _restore)

    # ------------------------------------------------------------------
    # Public API — populate from action data
    # ------------------------------------------------------------------

    @property
    def action(self) -> SetupAction | None:
        """Return the action bound to this card, or ``None``."""
        return self._action

    def populate(
        self,
        action: SetupAction,
        *,
        plugin_installed: dict[str, bool] | None = None,
        prerelease_overrides: set[str] | None = None,
    ) -> None:
        """Fill the card with data from a :class:`SetupAction`.

        Args:
            action: The setup action to display.
            plugin_installed: Plugin name → installed mapping.
            prerelease_overrides: Package names with user-enabled pre-release.
        """
        if self._is_skeleton:
            return

        self._action = action
        plugin_installed = plugin_installed or {}
        prerelease_overrides = prerelease_overrides or set()

        kind_label = ACTION_KIND_LABELS.get(action.kind, 'Action')
        self._type_badge.setText(kind_label)
        if action.installer:
            self._type_badge.setToolTip(f'Plugin: {action.installer}')

        package_text = str(action.package) if action.package else action.description
        self._package_label.setText(package_text)

        desc = action.package_description or action.description
        if desc and desc != package_text:
            self._desc_label.setText(desc)
            self._desc_label.show()
        else:
            self._desc_label.hide()

        # CLI command (always visible when present)
        cmd_text = _format_command(action)
        if cmd_text:
            self._command_label.setText(cmd_text)
            self._command_row.show()
        else:
            self._command_row.hide()

        # Version — populated later by set_check_result()

        self._version_label.setText('')

        # Status — check plugin presence first
        installer_missing = (
            action.installer is not None
            and action.installer in plugin_installed
            and not plugin_installed[action.installer]
        )

        if installer_missing:
            self._status_label.setText('Not installed')
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_UNAVAILABLE)
            self._status_label.show()
        else:
            # Show spinner instead of status text while checking
            self._status_label.hide()
            self._checking = True
            self._spinner_canvas.show()
            self._spinner_timer.start()

        # Pre-release checkbox
        if action.package is not None:
            pkg_name = str(action.package.name)
            is_user_override = pkg_name.lower() in prerelease_overrides
            if action.include_prereleases and not is_user_override:
                self._prerelease_cb.setChecked(True)
                self._prerelease_cb.setEnabled(False)
                self._prerelease_cb.setToolTip('Enabled by manifest')
            else:
                self._prerelease_cb.setChecked(is_user_override)
                self._prerelease_cb.setToolTip('Include pre-release versions')
                self._prerelease_cb.toggled.connect(
                    lambda checked, name=pkg_name: self.prerelease_toggled.emit(name, checked),
                )
            self._prerelease_cb.show()
        else:
            self._prerelease_cb.hide()

    def update_command(self, action: SetupAction) -> None:
        """Update the CLI command label after the resolved preview arrives.

        Called from the two-phase display flow once ``MANIFEST_LOADED``
        provides actions with their ``cli_command`` populated.

        Args:
            action: The setup action with resolved CLI command.
        """
        if self._is_skeleton:
            return
        cmd_text = _format_command(action)
        if cmd_text:
            self._command_label.setText(cmd_text)
            self._command_row.show()
        else:
            self._command_row.hide()

    def initial_status(self) -> str:
        """Return the initial status text set during :meth:`populate`."""
        if self._is_skeleton or not hasattr(self, '_status_label'):
            return ''
        if self._checking:
            return 'Checking\u2026'
        return self._status_label.text()

    def _stop_spinner(self) -> None:
        """Stop the inline checking spinner and show the status label."""
        if not hasattr(self, '_spinner_timer'):
            return
        self._checking = False
        self._spinner_timer.stop()
        self._spinner_canvas.hide()
        self._status_label.show()

    # ------------------------------------------------------------------
    # Public API — dry-run check result
    # ------------------------------------------------------------------

    def set_check_result(self, result: SetupActionResult) -> None:
        """Update the card with a dry-run check result.

        Args:
            result: The action check result from the preview worker.
        """
        if self._is_skeleton:
            return

        self._stop_spinner()

        if result.skipped and result.skip_reason == SkipReason.UPDATE_AVAILABLE:
            label = skip_reason_label(result.skip_reason)
            self._status_label.setText(label)
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_UPDATE)
        elif result.skipped:
            label = skip_reason_label(result.skip_reason)
            self._status_label.setText(label)
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_SATISFIED)
        else:
            label = 'Needed'
            self._status_label.setText(label)
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_NEEDED)

        # Surface diagnostic detail (e.g. SCM URL mismatch) as a tooltip
        if result.message:
            self._status_label.setToolTip(result.message)
        else:
            self._status_label.setToolTip('')

        # Version column
        self._check_available_version = result.available_version
        if result.installed_version and result.available_version:
            self._version_label.setText(f'{result.installed_version} \u2192 {result.available_version}')
            self._version_label.setStyleSheet(ACTION_CARD_VERSION_STYLE + ' color: #d7ba7d;')
        elif result.installed_version:
            self._version_label.setText(result.installed_version)

    def finalize_checking(self) -> None:
        """Resolve a still-pending 'Checking\u2026' status to 'Needed'.

        Called after the preview finishes if the dry-run never sent a
        result for this card.  'Not installed' statuses are left alone.
        """
        if self._is_skeleton or not hasattr(self, '_status_label'):
            return
        if self._checking:
            self._stop_spinner()
            self._status_label.setText('Needed')
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_NEEDED)

    # ------------------------------------------------------------------
    # Public API — execution (inline log)
    # ------------------------------------------------------------------

    def set_executing(self) -> None:
        """Transition the card into the *executing* state.

        Shows the inline log body and updates the status badge.
        """
        if self._is_skeleton:
            return
        self._stop_spinner()
        self.setStyleSheet(ACTION_CARD_EXECUTING_STYLE)
        self._status_label.setText('Running\u2026')
        self._status_label.setStyleSheet(ACTION_CARD_STATUS_RUNNING)
        self._log_expanded = True
        self._log_output.setVisible(True)

    def append_output(self, text: str, stream: str | None = None) -> None:
        """Append a line of output to the inline log.

        Args:
            text: The output line.
            stream: ``'stdout'``, ``'stderr'``, or ``None`` for phase messages.
        """
        if self._is_skeleton or not hasattr(self, '_log_output'):
            return

        colour = LOG_COLOR_STDOUT
        if stream == 'stderr':
            colour = LOG_COLOR_STDERR
        elif stream is None:
            colour = LOG_COLOR_PHASE

        escaped = html_mod.escape(text)
        self._log_output.append(f'<span style="color: {colour};">{escaped}</span>')

        cursor = self._log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log_output.setTextCursor(cursor)

    def set_result(self, result: SetupActionResult) -> None:
        """Update the card with the final execution result.

        The card returns to the default border style.  The log body stays
        visible but can be collapsed by clicking the card.

        Args:
            result: The action execution result.
        """
        if self._is_skeleton:
            return

        self.setStyleSheet(ACTION_CARD_STYLE)

        if result.skipped:
            label = skip_reason_label(result.skip_reason)
            self._status_label.setText(label)
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_SKIPPED)
            self.append_output(f'\u23ed Skipped: {label}', None)
        elif result.success:
            self._status_label.setText('Done')
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_DONE)
            msg = result.message or 'Completed successfully'
            self._log_output.append(
                f'<span style="color: {LOG_COLOR_SUCCESS};">\u2713 {html_mod.escape(msg)}</span>',
            )
            # Update version if an upgrade completed
            new_version = result.available_version or self._check_available_version
            if new_version:
                self._version_label.setText(new_version)
                self._version_label.setStyleSheet(ACTION_CARD_VERSION_STYLE)
        else:
            self._status_label.setText('Failed')
            self._status_label.setStyleSheet(ACTION_CARD_STATUS_FAILED)
            msg = result.message or 'Unknown error'
            self._log_output.append(
                f'<span style="color: {LOG_COLOR_ERROR};">\u2717 {html_mod.escape(msg)}</span>',
            )

    # ------------------------------------------------------------------
    # Public API — status text accessors (for counting)
    # ------------------------------------------------------------------

    def status_text(self) -> str:
        """Return the current status label text."""
        if self._is_skeleton or not hasattr(self, '_status_label'):
            return ''
        if self._checking:
            return 'Checking\u2026'
        return self._status_label.text()

    def is_update_available(self) -> bool:
        """Return whether the card shows an 'Update available' status."""
        return self.status_text() == 'Update available'


# ---------------------------------------------------------------------------
# ActionCardList — scrollable container
# ---------------------------------------------------------------------------


class ActionCardList(QScrollArea):
    """Scrollable container of :class:`ActionCard` widgets.

    Replaces both the ``QTableWidget`` and the ``ExecutionLogPanel`` from
    the previous install screen layout.  One scrollbar, no nesting.

    Cards are keyed by :func:`action_key` (content-based) so that
    look-ups work across different ``execute_stream`` runs where the
    ``SetupAction`` objects are different Python instances.
    """

    prerelease_toggled = Signal(str, bool)
    """Forwarded from child :class:`ActionCard` widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the card list."""
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(ACTION_CARD_SPACING)
        self._layout.addStretch()

        self.setWidget(self._container)

        self._cards: list[ActionCard] = []
        self._action_map: dict[tuple[object, ...], ActionCard] = {}

    # ------------------------------------------------------------------
    # Skeleton loading
    # ------------------------------------------------------------------

    def show_skeletons(self, count: int = 3) -> None:
        """Display *count* skeleton placeholder cards.

        Any existing cards are removed first.

        Args:
            count: Number of skeleton cards to show.
        """
        self.clear()
        for _ in range(count):
            card = ActionCard(self._container, skeleton=True)
            self._layout.insertWidget(self._layout.count() - 1, card)
            self._cards.append(card)

    # ------------------------------------------------------------------
    # Populate from preview
    # ------------------------------------------------------------------

    def populate(
        self,
        actions: list[SetupAction],
        *,
        plugin_installed: dict[str, bool] | None = None,
        prerelease_overrides: set[str] | None = None,
    ) -> None:
        """Replace skeleton cards with real action cards.

        Args:
            actions: The setup actions to display.
            plugin_installed: Plugin name → installed mapping.
            prerelease_overrides: Package names with user pre-release overrides.
        """
        self.clear()
        sorted_actions = sorted(
            (a for a in actions if a.kind is not None),
            key=action_sort_key,
        )
        for act in sorted_actions:
            card = ActionCard(self._container)
            card.populate(
                act,
                plugin_installed=plugin_installed,
                prerelease_overrides=prerelease_overrides,
            )
            card.prerelease_toggled.connect(self.prerelease_toggled.emit)
            self._layout.insertWidget(self._layout.count() - 1, card)
            self._cards.append(card)
            self._action_map[action_key(act)] = card

    # ------------------------------------------------------------------
    # Card lookup
    # ------------------------------------------------------------------

    def card_at(self, index: int) -> ActionCard | None:
        """Return the card at the given index, or ``None``."""
        if 0 <= index < len(self._cards):
            return self._cards[index]
        return None

    def card_count(self) -> int:
        """Return the number of cards (including skeletons)."""
        return len(self._cards)

    def get_card(self, action: SetupAction) -> ActionCard | None:
        """Look up the card for a given action by stable content key.

        Works across different ``execute_stream`` runs — the preview
        and install phases produce different ``SetupAction`` instances
        but the same logical action maps to the same card.

        Args:
            action: The setup action to find.

        Returns:
            The card widget, or ``None`` if not found.
        """
        return self._action_map.get(action_key(action))

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def finalize_all_checking(self) -> None:
        """Resolve all still-pending 'Checking\u2026' cards to 'Needed'."""
        for card in self._cards:
            card.finalize_checking()

    def clear(self) -> None:
        """Remove all cards."""
        for card in self._cards:
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._action_map.clear()

    # ------------------------------------------------------------------
    # Scroll helpers
    # ------------------------------------------------------------------

    def scroll_to_card(self, card: ActionCard) -> None:
        """Ensure *card* is visible in the scroll area."""
        self.ensureWidgetVisible(card)

    def scroll_to_card_bottom(self, card: ActionCard) -> None:
        """Scroll so the bottom of *card* is visible.

        Used during execution to follow the growing inline log output.
        Unlike :meth:`scroll_to_card` (which may show the top of a tall
        card), this always brings the bottom edge into view.
        """
        bottom_y = card.geometry().bottom()
        self.ensureVisible(0, bottom_y, 0, 50)
