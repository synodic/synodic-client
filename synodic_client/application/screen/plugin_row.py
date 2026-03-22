"""Plugin row widgets for the tools view.

Contains the compact widget rows used in :class:`ToolsView` to display
installed plugins and packages: kind headers, provider headers, individual
package rows, project child rows, and filter chips.
"""

from __future__ import annotations

from enum import Enum

from porringer.schema import PluginInfo
from porringer.schema.plugin import PluginCapability, PluginKind
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from synodic_client.application.screen import _format_relative_time, plugin_kind_group_label
from synodic_client.application.screen.schema import PluginRowData, ProjectInstance
from synodic_client.application.screen.spinner import SpinnerCanvas
from synodic_client.application.theme import (
    FILTER_CHIP_STYLE,
    PLUGIN_CHECK_STYLE,
    PLUGIN_KIND_HEADER_STYLE,
    PLUGIN_PROVIDER_NAME_STYLE,
    PLUGIN_PROVIDER_RUNTIME_TAG_DEFAULT_STYLE,
    PLUGIN_PROVIDER_RUNTIME_TAG_STYLE,
    PLUGIN_PROVIDER_STATUS_INSTALLED_STYLE,
    PLUGIN_PROVIDER_STATUS_MISSING_STYLE,
    PLUGIN_PROVIDER_STYLE,
    PLUGIN_PROVIDER_VERSION_STYLE,
    PLUGIN_ROW_ERROR_STYLE,
    PLUGIN_ROW_GLOBAL_STYLE,
    PLUGIN_ROW_HOST_STYLE,
    PLUGIN_ROW_NAME_STYLE,
    PLUGIN_ROW_PROJECT_STYLE,
    PLUGIN_ROW_PROJECT_TAG_STYLE,
    PLUGIN_ROW_PROJECT_TAG_TRANSITIVE_STYLE,
    PLUGIN_ROW_REMOVE_STYLE,
    PLUGIN_ROW_STATUS_MIN_WIDTH,
    PLUGIN_ROW_STATUS_PENDING_STYLE,
    PLUGIN_ROW_STATUS_STYLE,
    PLUGIN_ROW_STYLE,
    PLUGIN_ROW_TIMESTAMP_MIN_WIDTH,
    PLUGIN_ROW_TIMESTAMP_STYLE,
    PLUGIN_ROW_TOGGLE_STYLE,
    PLUGIN_ROW_UPDATE_STYLE,
    PLUGIN_ROW_UPDATE_WIDTH,
    PLUGIN_ROW_VERSION_MIN_WIDTH,
    PLUGIN_ROW_VERSION_STYLE,
    PLUGIN_TOGGLE_STYLE,
    PLUGIN_UPDATE_STYLE,
    PROJECT_CHILD_NAME_STYLE,
    PROJECT_CHILD_NAV_STYLE,
    PROJECT_CHILD_PROJECT_STYLE,
    PROJECT_CHILD_ROW_STYLE,
    PROJECT_CHILD_TRANSITIVE_STYLE,
    PROJECT_CHILD_VERSION_STYLE,
)


class RowPhase(Enum):
    """Mutually exclusive visual state for a :class:`PluginRow`."""

    IDLE = 'idle'
    CHECKING = 'checking'
    PENDING = 'pending'
    UPDATING = 'updating'


# Row-spinner dimensions
_ROW_SPINNER_SIZE = 12
_ROW_SPINNER_PEN = 2


class _RowSpinner(SpinnerCanvas):
    """Tiny spinning arc shown inline while checking for updates.

    Wraps :class:`SpinnerCanvas` with row-specific defaults and adds
    convenience ``start()`` / ``stop()`` helpers that toggle a timer.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=_ROW_SPINNER_SIZE, pen_width=_ROW_SPINNER_PEN, parent=parent)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.tick)
        self.hide()

    def start(self) -> None:
        """Show the spinner and start the animation."""
        self._angle = 0
        self.show()
        self._timer.start()

    def stop(self) -> None:
        """Stop the animation and hide."""
        self._timer.stop()
        self.hide()


# ---------------------------------------------------------------------------
# Plugin kind header — uppercase section divider
# ---------------------------------------------------------------------------


class PluginKindHeader(QLabel):
    """Uppercase, muted section divider for a plugin-kind group.

    Displays a label like ``TOOLS`` or ``PACKAGES`` with a subtle bottom
    border, matching VS Code's sidebar heading style.
    """

    def __init__(self, kind: PluginKind, parent: QWidget | None = None) -> None:
        """Initialize the kind header with an uppercase label."""
        super().__init__(plugin_kind_group_label(kind).upper(), parent)
        self.setObjectName('pluginKindHeader')
        self.setStyleSheet(PLUGIN_KIND_HEADER_STYLE)


# ---------------------------------------------------------------------------
# Plugin provider header — thin row for the managing plugin
# ---------------------------------------------------------------------------


class PluginProviderHeader(QFrame):
    """Thin sub-header row identifying the plugin that provides a set of tools.

    Shows the plugin name, version, installed status, and — for updatable
    kinds — ``Auto`` and ``Update`` buttons.  The ``Update`` button is
    only visible when *has_updates* is ``True``.
    """

    auto_update_toggled = Signal(str, bool)
    """Emitted with ``(plugin_name, enabled)`` when the auto-update toggle changes."""

    check_requested = Signal(str)
    """Emitted with the plugin name when the manual check-for-updates button is clicked."""

    update_requested = Signal(str)
    """Emitted with the plugin name when the per-plugin *Update* button is clicked."""

    def __init__(
        self,
        plugin: PluginInfo,
        auto_update: bool = True,
        *,
        capabilities: frozenset[PluginCapability] = frozenset(),
        show_controls: bool = False,
        has_updates: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the provider header with plugin info and optional controls."""
        super().__init__(parent)
        self.setObjectName('pluginProvider')
        self.setStyleSheet(PLUGIN_PROVIDER_STYLE)
        self._plugin_name = plugin.name
        self._runtime_tag = ''
        self._signal_key = plugin.name
        self._update_btn: QPushButton | None = None
        self._check_btn: QPushButton | None = None
        self._checking_spinner: _RowSpinner | None = None

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        # Plugin name
        name_label = QLabel(plugin.name)
        name_label.setStyleSheet(PLUGIN_PROVIDER_NAME_STYLE)
        self._layout.addWidget(name_label)

        # Version
        version_text = (
            str(plugin.tool_version)
            if plugin.tool_version is not None
            else 'Installed'
            if plugin.installed
            else 'Not installed'
        )
        version_label = QLabel(version_text)
        version_label.setStyleSheet(PLUGIN_PROVIDER_VERSION_STYLE)
        self._layout.addWidget(version_label)

        # Installed indicator
        status_label = QLabel('\u25cf' if plugin.installed else '\u25cb')
        status_label.setStyleSheet(
            PLUGIN_PROVIDER_STATUS_INSTALLED_STYLE if plugin.installed else PLUGIN_PROVIDER_STATUS_MISSING_STYLE
        )
        base_tip = 'Installed' if plugin.installed else 'Not installed'
        if capabilities:
            cap_names = ', '.join(c.name.replace('_', ' ').title() for c in sorted(capabilities, key=lambda c: c.name))
            status_label.setToolTip(f'{base_tip} \u00b7 {cap_names}')
        else:
            status_label.setToolTip(base_tip)
        self._layout.addWidget(status_label)

        self._layout.addStretch()

        # Transient inline error label (hidden by default)
        self._status_label = QLabel()
        self._status_label.setStyleSheet(PLUGIN_ROW_ERROR_STYLE)
        self._status_label.hide()
        self._layout.addWidget(self._status_label)

        # Auto / Update controls (only for updatable kinds)
        if show_controls:
            self._build_controls(self._layout, plugin, auto_update, has_updates)

    def set_runtime(self, tag: str, label: str = '') -> None:
        """Set runtime identity and optionally insert a runtime tag pill.

        Must be called before the widget is added to a visible layout.
        """
        self._runtime_tag = tag
        self._signal_key = f'{self._plugin_name}:{tag}' if tag else self._plugin_name
        if label:
            is_default = '(default)' in label
            pill = QLabel(label)
            pill.setStyleSheet(
                PLUGIN_PROVIDER_RUNTIME_TAG_DEFAULT_STYLE if is_default else PLUGIN_PROVIDER_RUNTIME_TAG_STYLE
            )
            # Insert after the name label (index 1)
            self._layout.insertWidget(1, pill)

    def _build_controls(
        self,
        layout: QHBoxLayout,
        plugin: PluginInfo,
        auto_update: bool,
        has_updates: bool,
    ) -> None:
        """Build auto-update toggle, check, and Update control buttons."""
        toggle_btn = QPushButton('\u21ba')
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(auto_update)
        toggle_btn.setStyleSheet(PLUGIN_TOGGLE_STYLE)
        toggle_btn.setToolTip('Enable automatic updates for this plugin')
        toggle_btn.clicked.connect(
            lambda checked: self.auto_update_toggled.emit(self._signal_key, checked),
        )
        layout.addWidget(toggle_btn)

        check_btn = QPushButton('\u27f3')
        check_btn.setStyleSheet(PLUGIN_CHECK_STYLE)
        check_btn.setToolTip('Check for updates now')
        check_btn.clicked.connect(
            lambda: self.check_requested.emit(self._signal_key),
        )
        self._check_btn = check_btn
        layout.addWidget(check_btn)

        self._checking_spinner = _RowSpinner(self)
        layout.addWidget(self._checking_spinner)

        update_btn = QPushButton('Update')
        update_btn.setStyleSheet(PLUGIN_UPDATE_STYLE)
        update_btn.setToolTip(f'Upgrade packages via {plugin.name} now')
        update_btn.clicked.connect(
            lambda: self.update_requested.emit(self._signal_key),
        )
        update_btn.setVisible(has_updates)
        self._update_btn = update_btn
        layout.addWidget(update_btn)

        if not plugin.installed:
            toggle_btn.setEnabled(False)
            toggle_btn.setChecked(False)
            toggle_btn.setToolTip('Not installed \u2014 cannot auto-update')
            check_btn.setEnabled(False)
            check_btn.setToolTip('Not installed \u2014 cannot check for updates')
            update_btn.setEnabled(False)
            update_btn.setToolTip('Not installed \u2014 cannot update')

    def set_updating(self, updating: bool) -> None:
        """Toggle between *Updating…* (with spinner) and *Update* states."""
        if updating:
            if self._checking_spinner is not None:
                self._checking_spinner.start()
            if self._update_btn is not None:
                self._update_btn.hide()
        else:
            if self._checking_spinner is not None:
                self._checking_spinner.stop()
            if self._update_btn is not None:
                self._update_btn.setText('Update')
                self._update_btn.setEnabled(True)

    def set_checking(self, checking: bool) -> None:
        """Show or hide the inline checking spinner."""
        if self._checking_spinner is None:
            return
        if checking:
            self._checking_spinner.start()
            if self._check_btn is not None:
                self._check_btn.hide()
            if self._update_btn is not None:
                self._update_btn.hide()
        else:
            self._checking_spinner.stop()
            if self._check_btn is not None:
                self._check_btn.show()

    def set_error(self, message: str) -> None:
        """Show a transient inline error that auto-hides after ~5 seconds."""
        self._status_label.setText(message)
        self._status_label.show()
        QTimer.singleShot(5000, self._status_label.hide)

    def clear_error(self) -> None:
        """Immediately hide the inline error label."""
        self._status_label.hide()


# ---------------------------------------------------------------------------
# Plugin row — compact package / tool entry
# ---------------------------------------------------------------------------


class PluginRow(QFrame):
    """Compact row showing an individual package or tool managed by a plugin.

    Displays the package name, the project it belongs to, and its version.
    The row highlights on hover using VS Code dark-theme colours.

    When *show_toggle* is ``True`` an inline **Auto** button lets the user
    toggle per-package auto-update.  If *is_global* is ``True`` and no
    *project* is given, a muted ``(global)`` annotation is shown.

    When *host_tool* is non-empty a muted ``→ <host>`` label appears
    after the name indicating the package is injected into that host.

    When *has_update* is ``True`` a small inline **Update** button appears
    so the user can upgrade this specific package on demand.
    """

    auto_update_toggled = Signal(str, str, bool)
    """Emitted with ``(plugin_name, package_name, enabled)`` on toggle."""

    update_requested = Signal(str, str)
    """Emitted with ``(plugin_name, package_name)`` when update is clicked."""

    remove_requested = Signal(str, str)
    """Emitted with ``(plugin_name, package_name)`` when remove is clicked."""

    navigate_to_project = Signal(str)
    """Emitted with a project path when a manifest-managed package tooltip link is clicked."""

    def __init__(
        self,
        data: PluginRowData,
        *,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize a plugin row from bundled display data."""
        super().__init__(parent)
        self.setObjectName('pluginRow')
        self.setStyleSheet(PLUGIN_ROW_STYLE)
        self._plugin_name = data.plugin_name
        self._package_name = data.name
        self._runtime_tag = data.runtime_tag
        self._signal_key = f'{data.plugin_name}:{data.runtime_tag}' if data.runtime_tag else data.plugin_name
        self._update_btn: QPushButton | None = None
        self._remove_btn: QPushButton | None = None
        self._row_spinner: _RowSpinner | None = None
        self._host_label: QLabel | None = None
        self._project_paths: list[str] = list(data.project_paths)
        self._project_labels: list[str] = [p.project_label for p in data.project_instances]
        self._update_status_label: QLabel | None = None
        self._timestamp_label: QLabel | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._build_name_section(layout, data)
        layout.addStretch()
        self._build_controls(layout, data)

    # --- PluginRow construction helpers ---

    def _build_name_section(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the name, host-tool arrow, project tags, and global label."""
        name_label = QLabel(data.name)
        name_label.setStyleSheet(PLUGIN_ROW_NAME_STYLE)
        layout.addWidget(name_label)

        if data.host_tool:
            self._host_label = QLabel(f'\u2192 {data.host_tool}')
            self._host_label.setStyleSheet(PLUGIN_ROW_HOST_STYLE)
            layout.addWidget(self._host_label)

        # Inline project-name tags (replaces ProjectChildRow)
        if data.project_instances:
            for proj in data.project_instances:
                tag = QLabel(proj.project_label)
                style = PLUGIN_ROW_PROJECT_TAG_TRANSITIVE_STYLE if proj.is_transitive else PLUGIN_ROW_PROJECT_TAG_STYLE
                tag.setStyleSheet(style)
                tag.setToolTip(f'{proj.project_path}' + (' (transitive)' if proj.is_transitive else ''))
                layout.addWidget(tag)
        elif data.project:
            project_label = QLabel(data.project)
            project_label.setStyleSheet(PLUGIN_ROW_PROJECT_STYLE)
            layout.addWidget(project_label)
        elif data.is_global:
            global_label = QLabel('(global)')
            global_label.setStyleSheet(PLUGIN_ROW_GLOBAL_STYLE)
            layout.addWidget(global_label)

    def _build_controls(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add toggle, update, status, version, timestamp, and remove controls.

        Controls are always created in the same order with fixed widths
        so that columns align vertically across all rows.  Hidden
        controls reserve space via ``retainSizeWhenHidden``.
        """
        if data.show_toggle:
            self._build_toggle(layout, data)

        # Inline spinner — always created so checking, pending, and
        # updating flows can use it regardless of whether the toggle is shown.
        self._row_spinner = _RowSpinner(self)
        layout.addWidget(self._row_spinner)

        # Update button — always created for alignment, hidden when no update
        self._build_update_button(layout, data)

        # Inline auto-update status (e.g. "Up to date", "v1.2 available")
        self._update_status_label = QLabel()
        self._update_status_label.setStyleSheet(PLUGIN_ROW_STATUS_STYLE)
        self._update_status_label.setMinimumWidth(PLUGIN_ROW_STATUS_MIN_WIDTH)
        self._update_status_label.hide()
        layout.addWidget(self._update_status_label)
        self._retain_size(layout)

        # Version — always created so column width is reserved
        version_label = QLabel(data.version)
        version_label.setStyleSheet(PLUGIN_ROW_VERSION_STYLE)
        version_label.setMinimumWidth(PLUGIN_ROW_VERSION_MIN_WIDTH)
        version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(version_label)

        # Timestamp — always created so column width is reserved
        self._timestamp_label = QLabel(_format_relative_time(data.last_updated) if data.last_updated else '')
        self._timestamp_label.setStyleSheet(PLUGIN_ROW_TIMESTAMP_STYLE)
        self._timestamp_label.setMinimumWidth(PLUGIN_ROW_TIMESTAMP_MIN_WIDTH)
        if data.last_updated:
            self._timestamp_label.setToolTip(f'Last updated: {data.last_updated}')
        layout.addWidget(self._timestamp_label)

        # Transient inline error label (hidden by default)
        self._error_label = QLabel()
        self._error_label.setStyleSheet(PLUGIN_ROW_ERROR_STYLE)
        self._error_label.hide()
        layout.addWidget(self._error_label)

        self._build_remove_button(layout, data)

    def _build_toggle(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the auto-update toggle button."""
        toggle_btn = QPushButton('\u21ba')
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(data.auto_update)
        toggle_btn.setStyleSheet(PLUGIN_ROW_TOGGLE_STYLE)
        toggle_btn.setToolTip('Auto-update this package')
        toggle_btn.clicked.connect(
            lambda checked: self.auto_update_toggled.emit(
                self._signal_key,
                self._package_name,
                checked,
            ),
        )
        layout.addWidget(toggle_btn)

    def _build_update_button(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the per-package update button (always created, visibility toggled)."""
        update_btn = QPushButton('Update')
        update_btn.setStyleSheet(PLUGIN_ROW_UPDATE_STYLE)
        update_btn.setFixedWidth(PLUGIN_ROW_UPDATE_WIDTH)
        update_btn.setToolTip(f'Update {data.name}')
        update_btn.clicked.connect(
            lambda: self.update_requested.emit(self._signal_key, self._package_name),
        )
        update_btn.setVisible(data.has_update)
        self._update_btn = update_btn
        layout.addWidget(update_btn)
        self._retain_size(layout)

    @staticmethod
    def _retain_size(layout: QHBoxLayout) -> None:
        """Mark the most recently added widget as size-retaining when hidden."""
        item = layout.itemAt(layout.count() - 1)
        if item is not None:
            widget = item.widget()
            if widget is not None:
                policy = widget.sizePolicy()
                policy.setRetainSizeWhenHidden(True)
                widget.setSizePolicy(policy)

    def _build_remove_button(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the remove button — enabled only for global packages."""
        remove_btn = QPushButton('\u00d7')
        remove_btn.setFixedSize(18, 18)
        remove_btn.setStyleSheet(PLUGIN_ROW_REMOVE_STYLE)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if data.is_global:
            remove_btn.setToolTip(f'Remove {data.name}')
            remove_btn.clicked.connect(
                lambda: self.remove_requested.emit(self._signal_key, self._package_name),
            )
        else:
            remove_btn.setEnabled(False)
            tooltip = f"Managed by project '{data.project}'" if data.project else 'Managed by a project manifest'
            remove_btn.setToolTip(tooltip)
            remove_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._remove_btn = remove_btn
        layout.addWidget(remove_btn)

    def set_phase(self, phase: RowPhase) -> None:
        """Transition the row to a mutually exclusive visual *phase*.

        * ``IDLE`` — spinner stopped, status hidden, button restored.
        * ``CHECKING`` — spinner running, button hidden.
        * ``PENDING`` — spinner stopped, *Pending* text shown, button hidden.
        * ``UPDATING`` — spinner running, status hidden, button hidden.
        """
        self._apply_phase_reset()

        if phase == RowPhase.IDLE:
            self._apply_phase_idle()
        elif phase == RowPhase.PENDING:
            self._apply_phase_pending()
        else:
            # CHECKING and UPDATING both start spinner and hide update btn
            self._apply_phase_spinner()

    def _apply_phase_reset(self) -> None:
        """Stop spinner and hide status — common entry for every transition."""
        if self._row_spinner is not None:
            self._row_spinner.stop()
        if self._update_status_label is not None:
            self._update_status_label.hide()

    def _apply_phase_idle(self) -> None:
        """Restore the update button to its default label and state."""
        if self._update_btn is not None:
            self._update_btn.setText('Update')
            self._update_btn.setEnabled(True)

    def _apply_phase_pending(self) -> None:
        """Show *Pending* text and hide the update button."""
        if self._update_status_label is not None:
            self._update_status_label.setText('Pending')
            self._update_status_label.setStyleSheet(PLUGIN_ROW_STATUS_PENDING_STYLE)
            self._update_status_label.show()
        if self._update_btn is not None:
            self._update_btn.hide()

    def _apply_phase_spinner(self) -> None:
        """Start the spinner and hide the update button."""
        if self._row_spinner is not None:
            self._row_spinner.start()
        if self._update_btn is not None:
            self._update_btn.hide()

    # Convenience aliases for backward-compatible call sites
    def set_updating(self, updating: bool) -> None:
        """Toggle between updating and idle states."""
        self.set_phase(RowPhase.UPDATING if updating else RowPhase.IDLE)

    def set_checking(self, checking: bool) -> None:
        """Toggle between checking and idle states."""
        self.set_phase(RowPhase.CHECKING if checking else RowPhase.IDLE)

    def set_pending(self, pending: bool) -> None:
        """Toggle between pending and idle states."""
        self.set_phase(RowPhase.PENDING if pending else RowPhase.IDLE)

    def set_removing(self, removing: bool) -> None:
        """Toggle the remove button between *Removing…* and *×* states."""
        if self._remove_btn is None:
            return
        if removing:
            self._remove_btn.setText('Removing\u2026')
            self._remove_btn.setEnabled(False)
        else:
            self._remove_btn.setText('\u00d7')
            self._remove_btn.setEnabled(True)

    def set_update_status(self, text: str, style: str = '') -> None:
        """Show inline auto-update check status (e.g. 'Up to date')."""
        if self._update_status_label is None:
            return
        self._update_status_label.setText(text)
        if style:
            self._update_status_label.setStyleSheet(style)
        self._update_status_label.setVisible(bool(text))

    def update_timestamp(self) -> None:
        """Refresh the relative time display on the timestamp label."""
        if self._timestamp_label is not None:
            tip = self._timestamp_label.toolTip()
            # Extract ISO timestamp from tooltip
            prefix = 'Last updated: '
            if tip.startswith(prefix):
                iso = tip[len(prefix) :]
                self._timestamp_label.setText(_format_relative_time(iso))

    def set_error(self, message: str) -> None:
        """Show a transient inline error that auto-hides after ~5 seconds."""
        self._error_label.setText(message)
        self._error_label.show()
        QTimer.singleShot(5000, self._error_label.hide)

    def clear_error(self) -> None:
        """Immediately hide the inline error label."""
        self._error_label.hide()


# ---------------------------------------------------------------------------
# Project child row — indented sub-row for project-scoped packages
# ---------------------------------------------------------------------------


class ProjectChildRow(QFrame):
    """Indented sub-row showing a project-scoped instance of a package.

    Displays the project label, version, and an optional ``(transitive)``
    annotation for packages not declared in the project manifest.
    A small navigate button switches to the Projects tab.

    These rows appear directly below the parent :class:`PluginRow` and
    are read-only — no update, remove, or auto-update controls.
    """

    navigate_to_project = Signal(str)
    """Emitted with a project path when the navigate button is clicked."""

    def __init__(
        self,
        project: ProjectInstance,
        *,
        package_name: str = '',
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the project child row.

        Args:
            project: The project instance data to display.
            package_name: Package name (displayed dimmed).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName('projectChildRow')
        self.setStyleSheet(PROJECT_CHILD_ROW_STYLE)
        self._project_path = project.project_path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Package name (dimmed)
        if package_name:
            name_label = QLabel(package_name)
            name_label.setStyleSheet(PROJECT_CHILD_NAME_STYLE)
            layout.addWidget(name_label)

        # Project label
        project_label = QLabel(project.project_label)
        project_label.setStyleSheet(PROJECT_CHILD_PROJECT_STYLE)
        layout.addWidget(project_label)

        # Transitive annotation
        if project.is_transitive:
            transitive_label = QLabel('(transitive)')
            transitive_label.setStyleSheet(PROJECT_CHILD_TRANSITIVE_STYLE)
            layout.addWidget(transitive_label)

        layout.addStretch()

        # Version
        if project.version:
            version_label = QLabel(project.version)
            version_label.setStyleSheet(PROJECT_CHILD_VERSION_STYLE)
            layout.addWidget(version_label)

        # Navigate button
        nav_btn = QPushButton('\u2192')
        nav_btn.setFixedSize(18, 18)
        nav_btn.setStyleSheet(PROJECT_CHILD_NAV_STYLE)
        nav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        nav_btn.setToolTip(f'Open project: {project.project_label}')
        nav_btn.clicked.connect(lambda: self.navigate_to_project.emit(self._project_path))
        layout.addWidget(nav_btn)


# ---------------------------------------------------------------------------
# Filter chip — toggleable pill for plugin filtering
# ---------------------------------------------------------------------------


class FilterChip(QPushButton):
    """Small toggleable pill button representing a single plugin filter.

    All chips start *checked* (active).  The user deselects chips to
    hide packages from that plugin — subtractive filtering.
    """

    toggled_with_name = Signal(str, bool)
    """Emitted with ``(plugin_name, checked)`` when the chip is toggled."""

    def __init__(self, plugin_name: str, parent: QWidget | None = None) -> None:
        """Initialize a filter chip for the given plugin name."""
        super().__init__(plugin_name, parent)
        self._plugin_name = plugin_name
        self.setCheckable(True)
        self.setChecked(True)
        self.setStyleSheet(FILTER_CHIP_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(lambda checked: self.toggled_with_name.emit(self._plugin_name, checked))
