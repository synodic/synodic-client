"""Centralised state model for the self-update lifecycle.

All update-related display state lives here.  The
:class:`UpdateController` is the sole writer; views
(:class:`UpdateBanner`, :class:`SettingsWindow`) observe changes via
Qt signals and never mutate the model directly.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QObject, Signal


class UpdatePhase(Enum):
    """High-level phases of the self-update lifecycle."""

    IDLE = auto()
    CHECKING = auto()
    DOWNLOADING = auto()
    READY = auto()
    ERROR = auto()


class UpdateModel(QObject):
    """Observable state for the self-update lifecycle.

    Signals
    -------
    phase_changed(UpdatePhase)
        Emitted when the lifecycle phase transitions.
    progress_changed(int)
        Emitted when download progress (0--100) updates.
    status_text_changed(str, str)
        Emitted when the settings status label text or style changes.
    check_button_enabled_changed(bool)
        Emitted when the *Check for Updates* button state changes.
    restart_visible_changed(bool)
        Emitted when the *Restart & Update* button visibility changes.
    last_checked_changed(str)
        Emitted when the *last updated* timestamp changes.
    """

    phase_changed = Signal(object)
    progress_changed = Signal(int)
    status_text_changed = Signal(str, str)
    check_button_enabled_changed = Signal(bool)
    restart_visible_changed = Signal(bool)
    last_checked_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the update model."""
        super().__init__(parent)
        self._phase = UpdatePhase.IDLE
        self._version: str = ''
        self._error_message: str = ''

    # --- Read-only properties ---

    @property
    def phase(self) -> UpdatePhase:
        """Current lifecycle phase."""
        return self._phase

    @property
    def version(self) -> str:
        """Version string associated with the current phase."""
        return self._version

    @property
    def error_message(self) -> str:
        """Error description when :attr:`phase` is ``ERROR``."""
        return self._error_message

    # --- Lifecycle transitions (controller writes) ---

    def _transition(self, phase: UpdatePhase) -> None:
        """Common transition logic — clears stale error state and emits."""
        if phase != UpdatePhase.ERROR:
            self._error_message = ''
        self._phase = phase
        self.phase_changed.emit(self._phase)

    def set_checking(self) -> None:
        """Enter the *CHECKING* phase."""
        self._transition(UpdatePhase.CHECKING)

    def set_downloading(self, version: str) -> None:
        """Enter the *DOWNLOADING* phase for *version*."""
        self._version = version
        self._transition(UpdatePhase.DOWNLOADING)

    def set_ready(self, version: str) -> None:
        """Enter the *READY* phase for *version*."""
        self._version = version
        self._transition(UpdatePhase.READY)

    def set_error(self, message: str) -> None:
        """Enter the *ERROR* phase with *message*."""
        self._error_message = message
        self._transition(UpdatePhase.ERROR)

    def set_idle(self) -> None:
        """Return to the *IDLE* phase."""
        self._transition(UpdatePhase.IDLE)

    def set_progress(self, percentage: int) -> None:
        """Update download progress (0--100)."""
        self.progress_changed.emit(percentage)

    # --- Settings-panel properties (controller writes) ---

    def set_status(self, text: str, style: str) -> None:
        """Update the inline status text and style."""
        self.status_text_changed.emit(text, style)

    def set_check_button_enabled(self, enabled: bool) -> None:
        """Enable or disable the *Check for Updates* button."""
        self.check_button_enabled_changed.emit(enabled)

    def set_restart_visible(self, visible: bool) -> None:
        """Show or hide the *Restart & Update* button."""
        self.restart_visible_changed.emit(visible)

    def set_last_checked(self, timestamp: str) -> None:
        """Update the *last updated* ISO 8601 timestamp."""
        self.last_checked_changed.emit(timestamp)
