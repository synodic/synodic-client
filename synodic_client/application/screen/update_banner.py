"""In-app update banner for the self-update lifecycle.

Replaces Windows tray balloon notifications and modal dialogs with a
persistent, non-intrusive banner displayed at the top of the main
window.  The banner transitions through three visual states:

* **downloading** — update detected, auto-downloading in the background.
* **ready** — download complete; user can restart at their convenience.
* **error** — check or download failed with a retry option.

The banner slides in/out using a ``QPropertyAnimation`` on
``maximumHeight`` for a polished feel.
"""

from __future__ import annotations

import logging
from enum import Enum, auto

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.theme import (
    UPDATE_BANNER_ANIMATION_MS,
    UPDATE_BANNER_BTN_STYLE,
    UPDATE_BANNER_DISMISS_STYLE,
    UPDATE_BANNER_ERROR_DISMISS_MS,
    UPDATE_BANNER_ERROR_STYLE,
    UPDATE_BANNER_MESSAGE_STYLE,
    UPDATE_BANNER_PROGRESS_STYLE,
    UPDATE_BANNER_READY_STYLE,
    UPDATE_BANNER_STYLE,
    UPDATE_BANNER_VERSION_STYLE,
)

logger = logging.getLogger(__name__)


class UpdateBannerState(Enum):
    """Visual states for the update banner."""

    HIDDEN = auto()
    DOWNLOADING = auto()
    READY = auto()
    ERROR = auto()


# Height of the banner content (progress variant is slightly taller).
_BANNER_HEIGHT = 38
_BANNER_HEIGHT_WITH_PROGRESS = 44


class UpdateBanner(QFrame):
    """Non-intrusive in-app banner for the self-update lifecycle.

    Signals:
        restart_requested: User clicked "Restart Now".
        retry_requested: User clicked "Retry" on an error banner.
        dismissed: User clicked the dismiss (×) button.
    """

    restart_requested = Signal()
    retry_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName('updateBanner')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._state = UpdateBannerState.HIDDEN
        self._target_version: str = ''

        # --- Layout ---
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # Row: icon · message · [progress_label] · [action_btn] · dismiss
        self._row = QHBoxLayout()
        self._row.setContentsMargins(12, 6, 12, 4)
        self._row.setSpacing(8)
        self._outer.addLayout(self._row)

        self._icon_label = QLabel('\U0001f504')  # 🔄
        self._icon_label.setFixedWidth(18)
        self._row.addWidget(self._icon_label)

        self._message = QLabel()
        self._message.setStyleSheet(UPDATE_BANNER_MESSAGE_STYLE)
        self._row.addWidget(self._message)

        self._row.addStretch()

        self._action_btn = QPushButton()
        self._action_btn.setStyleSheet(UPDATE_BANNER_BTN_STYLE)
        self._action_btn.clicked.connect(self._on_action)
        self._action_btn.hide()
        self._row.addWidget(self._action_btn)

        self._dismiss_btn = QPushButton('\u00d7')  # ×
        self._dismiss_btn.setStyleSheet(UPDATE_BANNER_DISMISS_STYLE)
        self._dismiss_btn.setFixedWidth(24)
        self._dismiss_btn.clicked.connect(self._on_dismiss)
        self._row.addWidget(self._dismiss_btn)

        # Thin progress bar (only visible during download)
        self._progress = QProgressBar()
        self._progress.setStyleSheet(UPDATE_BANNER_PROGRESS_STYLE)
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setFixedHeight(3)
        self._progress.hide()
        self._outer.addWidget(self._progress)

        # Start fully collapsed
        self.setMaximumHeight(0)
        self.setVisible(False)

        # Animation for slide-in / slide-out
        self._anim = QPropertyAnimation(self, b'maximumHeight')
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(UPDATE_BANNER_ANIMATION_MS)

    # --- Public API ---

    @property
    def state(self) -> UpdateBannerState:
        """Current visual state of the banner."""
        return self._state

    def show_downloading(self, version: str) -> None:
        """Transition to the *downloading* state.

        Args:
            version: The version string being downloaded (e.g. ``"0.0.1.dev35"``).
        """
        self._configure(
            state=UpdateBannerState.DOWNLOADING,
            version=version,
            style=UPDATE_BANNER_STYLE,
            icon='\u2b07',
            text=f'Downloading update <b>{version}</b>\u2026',
            text_style=UPDATE_BANNER_MESSAGE_STYLE,
            show_progress=True,
        )

    def show_downloading_progress(self, percentage: int) -> None:
        """Update the progress bar during download.

        Args:
            percentage: Download progress 0–100.
        """
        if self._state != UpdateBannerState.DOWNLOADING:
            return
        if self._progress.maximum() == 0:
            # Switch from indeterminate to determinate on first real value
            self._progress.setRange(0, 100)
        self._progress.setValue(percentage)

    def show_ready(self, version: str) -> None:
        """Transition to the *ready* state.

        Args:
            version: The version that is ready to install.
        """
        self._configure(
            state=UpdateBannerState.READY,
            version=version,
            style=UPDATE_BANNER_READY_STYLE,
            icon='\u2705',
            text=f'Update <b>{version}</b> is ready \u2014 restart to finish installing',
            text_style=UPDATE_BANNER_VERSION_STYLE,
            action_label='Restart Now',
        )

    def show_error(self, message: str) -> None:
        """Transition to the *error* state.

        Args:
            message: Human-readable error description.
        """
        self._configure(
            state=UpdateBannerState.ERROR,
            style=UPDATE_BANNER_ERROR_STYLE,
            icon='\u26a0',
            text=message,
            text_style=UPDATE_BANNER_MESSAGE_STYLE,
            action_label='Retry',
        )
        QTimer.singleShot(UPDATE_BANNER_ERROR_DISMISS_MS, self._auto_dismiss_error)

    def hide_banner(self) -> None:
        """Slide the banner out and reset to hidden."""
        if self._state == UpdateBannerState.HIDDEN:
            return
        self._state = UpdateBannerState.HIDDEN
        self._slide_out()

    # --- Internal ---

    def _configure(
        self,
        *,
        state: UpdateBannerState,
        style: str,
        icon: str,
        text: str,
        text_style: str,
        version: str = '',
        action_label: str = '',
        show_progress: bool = False,
    ) -> None:
        """Apply common visual configuration and slide the banner in.

        Args:
            state: The new banner state.
            style: QSS for the banner frame.
            icon: Single character displayed as the leading icon.
            text: Message (may contain HTML).
            text_style: QSS for the message label.
            version: Version string to store (optional).
            action_label: Text for the action button; hidden when empty.
            show_progress: Whether to show the progress bar.
        """
        self._state = state
        self._target_version = version

        self.setStyleSheet(style)
        self._icon_label.setText(icon)
        self._message.setText(text)
        self._message.setStyleSheet(text_style)

        if action_label:
            self._action_btn.setText(action_label)
            self._action_btn.show()
        else:
            self._action_btn.hide()

        if show_progress:
            self._progress.setRange(0, 0)  # indeterminate
            self._progress.show()
        else:
            self._progress.hide()

        target_height = _BANNER_HEIGHT_WITH_PROGRESS if show_progress else _BANNER_HEIGHT
        self._slide_in(target_height)

    def _slide_in(self, target_height: int) -> None:
        """Animate the banner from collapsed to *target_height*."""
        self.setVisible(True)
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(target_height)
        self._anim.start()

    def _slide_out(self) -> None:
        """Animate the banner down to zero height, then hide."""
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(0)
        # Use a one-shot connection to avoid accumulating slots.
        self._anim.finished.connect(
            self._on_slide_out_done,
            type=Qt.ConnectionType.SingleShotConnection,
        )
        self._anim.start()

    def _on_slide_out_done(self) -> None:
        """Hide the widget once the slide-out animation completes."""
        if self._state == UpdateBannerState.HIDDEN:
            self.setVisible(False)

    def _on_action(self) -> None:
        """Handle the primary action button click."""
        if self._state == UpdateBannerState.READY:
            self.restart_requested.emit()
        elif self._state == UpdateBannerState.ERROR:
            self.hide_banner()
            self.retry_requested.emit()

    def _on_dismiss(self) -> None:
        """Handle the dismiss (×) button click."""
        self.hide_banner()
        self.dismissed.emit()

    def _auto_dismiss_error(self) -> None:
        """Auto-dismiss the error banner if it's still showing."""
        if self._state == UpdateBannerState.ERROR:
            self.hide_banner()
