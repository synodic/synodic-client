"""Settings window for the Synodic Client application.

Provides a single-page window with grouped sections for all application
settings including update-channel selection and a manual *Check for
Updates* button with inline status feedback.
"""

import logging
import sys
import traceback
from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen import _format_relative_time
from synodic_client.application.screen.card import CardFrame
from synodic_client.application.theme import SETTINGS_WINDOW_MIN_SIZE, UPDATE_STATUS_CHECKING_STYLE
from synodic_client.logging import log_path
from synodic_client.resolution import ResolvedConfig, update_user_config
from synodic_client.schema import GITHUB_REPO_URL
from synodic_client.startup import is_startup_registered, register_startup, remove_startup

logger = logging.getLogger(__name__)


class SettingsWindow(QMainWindow):
    """Application settings window with grouped card sections.

    All controls persist changes immediately via :func:`update_user_config`
    and emit :attr:`settings_changed` so that the tray and updater can
    react.  The signal carries the new :class:`ResolvedConfig`.
    """

    settings_changed = Signal(object)
    """Emitted with the new ``ResolvedConfig`` whenever a setting is changed and persisted."""

    check_updates_requested = Signal()
    """Emitted when the user clicks the *Check for Updates* button."""

    restart_requested = Signal()
    """Emitted when the user clicks the *Restart & Update* button."""

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """[DIAG] Log every show event with a stack trace."""
        geo = self.geometry()
        stack = ''.join(traceback.format_stack(limit=10))
        logger.debug(
            '[DIAG] SettingsWindow.showEvent: geo=(%d,%d %dx%d) visible=%s\n%s',
            geo.x(),
            geo.y(),
            geo.width(),
            geo.height(),
            self.isVisible(),
            stack,
        )
        super().showEvent(event)

    def __init__(
        self,
        config: ResolvedConfig,
        version: str = '',
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the settings window.

        Args:
            config: The current resolved configuration snapshot.
            version: The application version string to display.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._config = config
        self._version = version
        self.setWindowTitle('Synodic Settings')
        self.setMinimumSize(*SETTINGS_WINDOW_MIN_SIZE)
        self.setWindowIcon(app_icon())
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Build the scrollable settings layout."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._build_updates_section())
        layout.addWidget(self._build_startup_section())
        layout.addWidget(self._build_advanced_section())
        layout.addStretch()

        version_label = QLabel(f'Version {self._version}')
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet('color: rgba(255, 255, 255, 0.4); font-size: 11px;')
        layout.addWidget(version_label)

        scroll.setWidget(container)
        self.setCentralWidget(scroll)

    def _build_updates_section(self) -> CardFrame:
        """Construct the *Updates* settings card."""
        card = CardFrame('Updates')
        content = card.content_layout

        # Channel
        row = QHBoxLayout()
        label = QLabel('Channel')
        label.setMinimumWidth(160)
        row.addWidget(label)
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(['Stable', 'Development'])
        self._channel_combo.currentIndexChanged.connect(self._on_channel_changed)
        row.addWidget(self._channel_combo)
        row.addStretch()
        content.addLayout(row)

        # Update Source
        row = QHBoxLayout()
        label = QLabel('Update source')
        label.setMinimumWidth(160)
        row.addWidget(label)
        self._source_edit = QLineEdit()
        self._source_edit.setPlaceholderText(GITHUB_REPO_URL)
        self._source_edit.editingFinished.connect(self._on_source_changed)
        row.addWidget(self._source_edit, 1)
        browse_btn = QPushButton('Browse\u2026')
        browse_btn.clicked.connect(self._on_browse_source)
        row.addWidget(browse_btn)
        content.addLayout(row)

        self._add_update_controls(content)

        return card

    def _add_update_controls(self, content: QVBoxLayout) -> None:
        """Add interval spinners, detect-updates checkbox, and update button."""
        # Auto-update interval
        row = QHBoxLayout()
        label = QLabel('App update interval (min)')
        label.setMinimumWidth(160)
        row.addWidget(label)
        self._auto_update_spin = QSpinBox()
        self._auto_update_spin.setRange(0, 1440)
        self._auto_update_spin.setSpecialValueText('Disabled')
        self._auto_update_spin.valueChanged.connect(self._on_auto_update_interval_changed)
        row.addWidget(self._auto_update_spin)
        row.addStretch()
        content.addLayout(row)

        # Tool-update interval
        row = QHBoxLayout()
        label = QLabel('Tool update interval (min)')
        label.setMinimumWidth(160)
        row.addWidget(label)
        self._tool_update_spin = QSpinBox()
        self._tool_update_spin.setRange(0, 1440)
        self._tool_update_spin.setSpecialValueText('Disabled')
        self._tool_update_spin.valueChanged.connect(self._on_tool_update_interval_changed)
        row.addWidget(self._tool_update_spin)
        row.addStretch()
        content.addLayout(row)

        # Detect updates during previews
        self._detect_updates_check = QCheckBox('Detect updates during previews')
        self._detect_updates_check.toggled.connect(self._on_detect_updates_changed)
        content.addWidget(self._detect_updates_check)

        # Automatically apply updates
        self._auto_apply_check = QCheckBox('Automatically apply updates')
        self._auto_apply_check.toggled.connect(self._on_auto_apply_changed)
        content.addWidget(self._auto_apply_check)

        # Check for Updates
        row = QHBoxLayout()
        self._check_updates_btn = QPushButton('Check for Updates\u2026')
        self._check_updates_btn.clicked.connect(self._on_check_updates_clicked)
        row.addWidget(self._check_updates_btn)
        self._update_status_label = QLabel('')
        self._update_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self._update_status_label)

        self._restart_btn = QPushButton('Restart \u0026 Update')
        self._restart_btn.clicked.connect(self.restart_requested.emit)
        self._restart_btn.hide()
        row.addWidget(self._restart_btn)

        row.addStretch()
        content.addLayout(row)

        # Last client update timestamp
        self._last_client_update_label = QLabel('')
        self._last_client_update_label.setStyleSheet('color: #808080; font-size: 11px;')
        content.addWidget(self._last_client_update_label)

    def _build_startup_section(self) -> CardFrame:
        """Construct the *Startup* settings card."""
        card = CardFrame('Startup')
        self._auto_start_check = QCheckBox('Start with Windows')
        self._auto_start_check.toggled.connect(self._on_auto_start_changed)
        card.content_layout.addWidget(self._auto_start_check)
        return card

    def _build_advanced_section(self) -> CardFrame:
        """Construct the *Advanced* settings card."""
        card = CardFrame('Advanced')
        row = QHBoxLayout()
        open_log_btn = QPushButton('Open Log\u2026')
        open_log_btn.clicked.connect(self._open_log)
        row.addWidget(open_log_btn)
        row.addStretch()
        card.content_layout.addLayout(row)
        return card

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_from_config(self) -> None:
        """Synchronize all controls from the current configuration.

        Signals are blocked during the update to prevent feedback loops.
        """
        config = self._config

        with self._block_signals():
            # Channel: index 0 = Stable, 1 = Development
            is_dev = config.update_channel == 'dev'
            self._channel_combo.setCurrentIndex(1 if is_dev else 0)

            # Update source
            self._source_edit.setText(config.update_source or '')

            # Intervals (already resolved to concrete ints)
            self._auto_update_spin.setValue(config.auto_update_interval_minutes)
            self._tool_update_spin.setValue(config.tool_update_interval_minutes)

            # Checkboxes
            self._detect_updates_check.setChecked(config.detect_updates)
            self._auto_apply_check.setChecked(config.auto_apply)
            self._auto_start_check.setChecked(is_startup_registered())

            # Last client update timestamp
            if config.last_client_update:
                relative = _format_relative_time(config.last_client_update)
                self._last_client_update_label.setText(f'Last updated: {relative}')
                self._last_client_update_label.setToolTip(f'Last updated: {config.last_client_update}')
            else:
                self._last_client_update_label.setText('')

    def set_update_status(self, text: str, style: str = '') -> None:
        """Set the inline status text next to the *Check for Updates* button.

        Args:
            text: The status message.
            style: Optional stylesheet for the label (e.g. color).
        """
        self._update_status_label.setText(text)
        self._update_status_label.setStyleSheet(style)

    def set_checking(self) -> None:
        """Enter the *checking* state — disable button and show status."""
        self._check_updates_btn.setEnabled(False)
        self._restart_btn.hide()
        self._update_status_label.setText('Checking\u2026')
        self._update_status_label.setStyleSheet(UPDATE_STATUS_CHECKING_STYLE)

    def reset_check_updates_button(self) -> None:
        """Re-enable the *Check for Updates* button after a check completes."""
        self._check_updates_btn.setEnabled(True)

    def show_restart_button(self) -> None:
        """Show the *Restart & Update* button."""
        self._restart_btn.show()

    def show(self) -> None:
        """Sync controls from config, then show the window."""
        self.sync_from_config()
        super().show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _persist(self, **changes: object) -> None:
        """Save config changes and notify listeners.

        Args:
            **changes: Field-name / value pairs to persist.
        """
        self._config = update_user_config(**changes)
        self.settings_changed.emit(self._config)

    @contextmanager
    def _block_signals(self) -> Iterator[None]:
        """Temporarily block signals on all settings controls."""
        widgets = (
            self._channel_combo,
            self._source_edit,
            self._auto_update_spin,
            self._tool_update_spin,
            self._detect_updates_check,
            self._auto_apply_check,
            self._auto_start_check,
            self._check_updates_btn,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            yield
        finally:
            for w in widgets:
                w.blockSignals(False)

    def _on_check_updates_clicked(self) -> None:
        """Handle the *Check for Updates* button click."""
        self._check_updates_btn.setEnabled(False)
        self._update_status_label.setText('Checking\u2026')
        self.check_updates_requested.emit()

    def _on_channel_changed(self, index: int) -> None:
        self._persist(update_channel='dev' if index == 1 else 'stable')

    def _on_source_changed(self) -> None:
        text = self._source_edit.text().strip()
        self._persist(update_source=text or None)

    def _on_browse_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, 'Select Releases Directory')
        if path:
            self._source_edit.setText(path)
            self._on_source_changed()

    def _on_auto_update_interval_changed(self, value: int) -> None:
        self._persist(auto_update_interval_minutes=value)

    def _on_tool_update_interval_changed(self, value: int) -> None:
        self._persist(tool_update_interval_minutes=value)

    def _on_detect_updates_changed(self, checked: bool) -> None:
        self._persist(detect_updates=checked)

    def _on_auto_apply_changed(self, checked: bool) -> None:
        self._persist(auto_apply=checked)

    def _on_auto_start_changed(self, checked: bool) -> None:
        self._config = update_user_config(auto_start=checked)
        if checked:
            register_startup(sys.executable)
        else:
            remove_startup()
        self.settings_changed.emit(self._config)

    @staticmethod
    def _open_log() -> None:
        """Open the log file in the system's default editor."""
        path = log_path()
        if not path.exists():
            path.touch()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
