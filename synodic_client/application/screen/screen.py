"""Screen class for the Synodic Client application."""

import asyncio
import contextlib
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from porringer.api import API
from porringer.backend.builder import Builder
from porringer.core.plugin_schema.plugin_manager import PluginManager
from porringer.core.plugin_schema.project_environment import ProjectEnvironment
from porringer.schema import (
    DirectoryValidationResult,
    ManifestDirectory,
    PluginInfo,
    ProgressEventKind,
    SetupAction,
    SetupParameters,
    SkipReason,
)
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen import plugin_kind_group_label
from synodic_client.application.screen.install import PreviewPhase, SetupPreviewWidget
from synodic_client.application.screen.sidebar import ManifestSidebar
from synodic_client.application.screen.spinner import SpinnerWidget
from synodic_client.application.screen.update_banner import UpdateBanner
from synodic_client.application.theme import (
    COMPACT_MARGINS,
    MAIN_WINDOW_MIN_SIZE,
    PLUGIN_KIND_HEADER_STYLE,
    PLUGIN_PROVIDER_NAME_STYLE,
    PLUGIN_PROVIDER_STATUS_INSTALLED_STYLE,
    PLUGIN_PROVIDER_STATUS_MISSING_STYLE,
    PLUGIN_PROVIDER_STYLE,
    PLUGIN_PROVIDER_VERSION_STYLE,
    PLUGIN_ROW_ERROR_STYLE,
    PLUGIN_ROW_GLOBAL_STYLE,
    PLUGIN_ROW_HOST_STYLE,
    PLUGIN_ROW_NAME_STYLE,
    PLUGIN_ROW_PROJECT_STYLE,
    PLUGIN_ROW_REMOVE_STYLE,
    PLUGIN_ROW_STYLE,
    PLUGIN_ROW_TOGGLE_STYLE,
    PLUGIN_ROW_UPDATE_STYLE,
    PLUGIN_ROW_VERSION_STYLE,
    PLUGIN_SECTION_SPACING,
    PLUGIN_TOGGLE_STYLE,
    PLUGIN_UPDATE_STYLE,
    SETTINGS_GEAR_STYLE,
)
from synodic_client.resolution import ResolvedConfig, update_user_config

logger = logging.getLogger(__name__)

# Plugin kinds that support auto-update and per-plugin upgrade.
_UPDATABLE_KINDS = frozenset({PluginKind.TOOL, PluginKind.PACKAGE})

# Inline row-spinner constants
_ROW_SPINNER_SIZE = 12
_ROW_SPINNER_PEN = 2
_ROW_SPINNER_INTERVAL = 50
_ROW_SPINNER_ARC = 90
_FULL_CIRCLE_DEG = 360

# Preferred display ordering — Tools first, then alphabetical for the rest.
_KIND_DISPLAY_ORDER: dict[PluginKind, int] = {
    PluginKind.TOOL: 0,
    PluginKind.PACKAGE: 1,
    PluginKind.RUNTIME: 2,
    PluginKind.PROJECT: 3,
    PluginKind.SCM: 4,
}


# ---------------------------------------------------------------------------
# Data models for package gathering and display
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PackageEntry:
    """A single package returned by a gather query.

    Replaces ad-hoc tuples returned by ``_gather_packages`` and
    ``_gather_tool_plugins``.
    """

    name: str
    """Package name (e.g. ``"pdm"``, ``"ruff"``)."""

    project_label: str = ''
    """Human-readable project directory label, or empty for global packages."""

    version: str = ''
    """Installed version string, or empty if unknown."""

    host_tool: str = ''
    """Name of the host package when injected (e.g. ``"pdm"``), otherwise empty."""

    project_path: str = ''
    """Directory path string for project-scoped packages, or empty for global ones."""


@dataclass(slots=True)
class MergedPackage:
    """Accumulated view of a package after deduplication across directories.

    Used during ``_async_refresh`` to merge multiple
    :class:`PackageEntry` instances referencing the same package name
    into a single row description.
    """

    projects: list[str] = field(default_factory=list)
    """Display names of the projects referencing this package."""

    project_paths: list[str] = field(default_factory=list)
    """Filesystem paths of the project directories."""

    version: str = ''
    """Installed version string."""

    is_global: bool = False
    """``True`` when the package is not referenced by any project manifest."""

    host_tool: str = ''
    """Host-tool annotation for injected packages."""


@dataclass(slots=True)
class PluginRowData:
    """Bundled display data for constructing a :class:`PluginRow`.

    Groups the many display parameters into a single object
    to keep the constructor signature concise.
    """

    name: str
    """Package or tool name."""

    project: str = ''
    """Comma-separated project labels, or empty for global / bare rows."""

    version: str = ''
    """Installed version string."""

    plugin_name: str = ''
    """Name of the managing plugin (e.g. ``"pipx"``)."""

    auto_update: bool = False
    """Current per-package auto-update toggle state."""

    show_toggle: bool = False
    """Whether to show the inline *Auto* toggle button."""

    has_update: bool = False
    """Whether an update is available for this package."""

    is_global: bool = False
    """``True`` when the package is globally installed."""

    host_tool: str = ''
    """Host-tool name for injected packages."""

    project_paths: list[str] = field(default_factory=list)
    """Filesystem paths for project-scoped packages."""


@dataclass(slots=True)
class _RefreshData:
    """Internal data bundle returned by :meth:`ToolsView._gather_refresh_data`."""

    plugins: list[PluginInfo]
    """All discovered plugins."""

    packages_map: dict[str, list[PackageEntry]]
    """Mapping of plugin name → gathered packages."""

    manifest_packages: dict[str, set[str]]
    """Mapping of plugin name → manifest-referenced package names."""


# ---------------------------------------------------------------------------
# _RowSpinner — tiny inline spinner for plugin rows
# ---------------------------------------------------------------------------


class _RowSpinner(QWidget):
    """Tiny spinning arc shown inline while checking for updates."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(_ROW_SPINNER_SIZE, _ROW_SPINNER_SIZE)
        self._timer = QTimer(self)
        self._timer.setInterval(_ROW_SPINNER_INTERVAL)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def paintEvent(self, _event: object) -> None:
        """Draw the muted track and animated highlight arc."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = _ROW_SPINNER_PEN // 2 + 1
        rect = QRect(m, m, _ROW_SPINNER_SIZE - 2 * m, _ROW_SPINNER_SIZE - 2 * m)
        for colour, span in ((self.palette().mid(), _FULL_CIRCLE_DEG), (self.palette().highlight(), _ROW_SPINNER_ARC)):
            pen = QPen(colour, _ROW_SPINNER_PEN)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            if span == _FULL_CIRCLE_DEG:
                painter.drawEllipse(rect)
            else:
                painter.drawArc(rect, self._angle * 16, span * 16)
        painter.end()

    def _tick(self) -> None:
        self._angle = (self._angle - 10) % 360
        self.update()

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

    update_requested = Signal(str)
    """Emitted with the plugin name when the per-plugin *Update* button is clicked."""

    def __init__(
        self,
        plugin: PluginInfo,
        auto_update: bool = True,
        *,
        show_controls: bool = False,
        has_updates: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the provider header with plugin info and optional controls."""
        super().__init__(parent)
        self.setObjectName('pluginProvider')
        self.setStyleSheet(PLUGIN_PROVIDER_STYLE)
        self._plugin_name = plugin.name
        self._update_btn: QPushButton | None = None
        self._checking_spinner: _RowSpinner | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Plugin name
        name_label = QLabel(plugin.name)
        name_label.setStyleSheet(PLUGIN_PROVIDER_NAME_STYLE)
        layout.addWidget(name_label)

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
        layout.addWidget(version_label)

        # Installed indicator
        status_label = QLabel('\u25cf' if plugin.installed else '\u25cb')
        status_label.setStyleSheet(
            PLUGIN_PROVIDER_STATUS_INSTALLED_STYLE if plugin.installed else PLUGIN_PROVIDER_STATUS_MISSING_STYLE
        )
        status_label.setToolTip('Installed' if plugin.installed else 'Not installed')
        layout.addWidget(status_label)

        layout.addStretch()

        # Transient inline error label (hidden by default)
        self._status_label = QLabel()
        self._status_label.setStyleSheet(PLUGIN_ROW_ERROR_STYLE)
        self._status_label.hide()
        layout.addWidget(self._status_label)

        # Auto / Update controls (only for updatable kinds)
        if show_controls:
            toggle_btn = QPushButton('Auto')
            toggle_btn.setCheckable(True)
            toggle_btn.setChecked(auto_update)
            toggle_btn.setStyleSheet(PLUGIN_TOGGLE_STYLE)
            toggle_btn.setToolTip('Enable automatic updates for this plugin')
            toggle_btn.clicked.connect(
                lambda checked: self.auto_update_toggled.emit(self._plugin_name, checked),
            )
            layout.addWidget(toggle_btn)

            self._checking_spinner = _RowSpinner(self)
            layout.addWidget(self._checking_spinner)

            update_btn = QPushButton('Update')
            update_btn.setStyleSheet(PLUGIN_UPDATE_STYLE)
            update_btn.setToolTip(f'Upgrade packages via {plugin.name} now')
            update_btn.clicked.connect(
                lambda: self.update_requested.emit(self._plugin_name),
            )
            update_btn.setVisible(has_updates)
            self._update_btn = update_btn
            layout.addWidget(update_btn)

            if not plugin.installed:
                toggle_btn.setEnabled(False)
                toggle_btn.setChecked(False)
                toggle_btn.setToolTip('Not installed \u2014 cannot auto-update')
                update_btn.setEnabled(False)
                update_btn.setToolTip('Not installed \u2014 cannot update')

    def set_updating(self, updating: bool) -> None:
        """Toggle the button between *Updating…* and *Update* states."""
        if self._update_btn is None:
            return
        if updating:
            self._update_btn.setText('Updating\u2026')
            self._update_btn.setEnabled(False)
        else:
            self._update_btn.setText('Update')
            self._update_btn.setEnabled(True)

    def set_checking(self, checking: bool) -> None:
        """Show or hide the inline checking spinner."""
        if self._checking_spinner is None:
            return
        if checking:
            self._checking_spinner.start()
            if self._update_btn is not None:
                self._update_btn.hide()
        else:
            self._checking_spinner.stop()

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
        self._update_btn: QPushButton | None = None
        self._remove_btn: QPushButton | None = None
        self._checking_spinner: _RowSpinner | None = None
        self._host_label: QLabel | None = None
        self._project_paths: list[str] = list(data.project_paths)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._build_name_section(layout, data)
        layout.addStretch()
        self._build_controls(layout, data)

    # --- PluginRow construction helpers ---

    def _build_name_section(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the name, optional host-tool arrow, and project/global labels."""
        name_label = QLabel(data.name)
        name_label.setStyleSheet(PLUGIN_ROW_NAME_STYLE)
        layout.addWidget(name_label)

        if data.host_tool:
            self._host_label = QLabel(f'\u2192 {data.host_tool}')
            self._host_label.setStyleSheet(PLUGIN_ROW_HOST_STYLE)
            layout.addWidget(self._host_label)

        if data.project:
            project_label = QLabel(data.project)
            project_label.setStyleSheet(PLUGIN_ROW_PROJECT_STYLE)
            layout.addWidget(project_label)
        elif data.is_global:
            global_label = QLabel('(global)')
            global_label.setStyleSheet(PLUGIN_ROW_GLOBAL_STYLE)
            layout.addWidget(global_label)

    def _build_controls(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add toggle, update, version, and remove controls."""
        if data.show_toggle:
            self._build_toggle(layout, data)
        if data.has_update:
            self._build_update_button(layout, data)
        if data.version:
            version_label = QLabel(data.version)
            version_label.setStyleSheet(PLUGIN_ROW_VERSION_STYLE)
            layout.addWidget(version_label)

        # Transient inline error label (hidden by default)
        self._status_label = QLabel()
        self._status_label.setStyleSheet(PLUGIN_ROW_ERROR_STYLE)
        self._status_label.hide()
        layout.addWidget(self._status_label)

        self._build_remove_button(layout, data)

    def _build_toggle(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the auto-update toggle and inline checking spinner."""
        toggle_btn = QPushButton('Auto')
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(data.auto_update)
        toggle_btn.setStyleSheet(PLUGIN_ROW_TOGGLE_STYLE)
        toggle_btn.setToolTip('Auto-update this package')
        toggle_btn.clicked.connect(
            lambda checked: self.auto_update_toggled.emit(
                self._plugin_name,
                self._package_name,
                checked,
            ),
        )
        layout.addWidget(toggle_btn)

        self._checking_spinner = _RowSpinner(self)
        layout.addWidget(self._checking_spinner)

    def _build_update_button(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the per-package update button."""
        update_btn = QPushButton('Update')
        update_btn.setStyleSheet(PLUGIN_ROW_UPDATE_STYLE)
        update_btn.setToolTip(f'Update {data.name}')
        update_btn.clicked.connect(
            lambda: self.update_requested.emit(self._plugin_name, self._package_name),
        )
        self._update_btn = update_btn
        layout.addWidget(update_btn)

    def _build_remove_button(self, layout: QHBoxLayout, data: PluginRowData) -> None:
        """Add the remove button — enabled only for global packages."""
        remove_btn = QPushButton('\u00d7')
        remove_btn.setFixedSize(18, 18)
        remove_btn.setStyleSheet(PLUGIN_ROW_REMOVE_STYLE)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if data.is_global:
            remove_btn.setToolTip(f'Remove {data.name}')
            remove_btn.clicked.connect(
                lambda: self.remove_requested.emit(self._plugin_name, self._package_name),
            )
        else:
            remove_btn.setEnabled(False)
            tooltip = f"Managed by project '{data.project}'" if data.project else 'Managed by a project manifest'
            remove_btn.setToolTip(tooltip)
            remove_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._remove_btn = remove_btn
        layout.addWidget(remove_btn)

    def set_updating(self, updating: bool) -> None:
        """Toggle the button between *Updating…* and *Update* states."""
        if self._update_btn is None:
            return
        if updating:
            self._update_btn.setText('Updating\u2026')
            self._update_btn.setEnabled(False)
        else:
            self._update_btn.setText('Update')
            self._update_btn.setEnabled(True)

    def set_checking(self, checking: bool) -> None:
        """Show or hide the inline checking spinner."""
        if self._checking_spinner is None:
            return
        if checking:
            self._checking_spinner.start()
            if self._update_btn is not None:
                self._update_btn.hide()
        else:
            self._checking_spinner.stop()

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

    def set_error(self, message: str) -> None:
        """Show a transient inline error that auto-hides after ~5 seconds."""
        self._status_label.setText(message)
        self._status_label.show()
        QTimer.singleShot(5000, self._status_label.hide)

    def clear_error(self) -> None:
        """Immediately hide the inline error label."""
        self._status_label.hide()


class ToolsView(QWidget):
    """Central update hub showing installed tools and packages.

    Only displays ``TOOL`` and ``PACKAGE`` kind plugins that have a
    ``tool_version`` or managed packages.  Each tool has ``Auto`` /
    ``Update`` controls.  Empty plugins are hidden.
    """

    update_all_requested = Signal()
    """Emitted when the global *Update All* button is clicked."""

    plugin_update_requested = Signal(str)
    """Emitted with a plugin name when its per-plugin *Update* button is clicked."""

    package_update_requested = Signal(str, str)
    """Emitted with ``(plugin_name, package_name)`` for a per-package update."""

    package_remove_requested = Signal(str, str)
    """Emitted with ``(plugin_name, package_name)`` for a per-package removal."""

    navigate_to_project_requested = Signal(str)
    """Emitted with a project path string to navigate to the Projects tab."""

    def __init__(
        self,
        porringer: API,
        config: ResolvedConfig,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the tools view.

        Args:
            porringer: The porringer API instance.
            config: Resolved configuration (for auto-update toggles).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._config = config
        self._section_widgets: list[QWidget] = []
        self._refresh_in_progress = False
        self._check_in_progress = False
        self._updates_checked = False
        self._updates_available: dict[str, set[str]] = {}
        self._directories: list[ManifestDirectory] = []
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*COMPACT_MARGINS)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addStretch()

        check_btn = QPushButton('Check for Updates')
        check_btn.setToolTip('Scan all manifests for available package updates')
        check_btn.clicked.connect(self._on_check_for_updates)
        toolbar.addWidget(check_btn)
        self._check_btn = check_btn

        update_all_btn = QPushButton('Update All')
        update_all_btn.setToolTip('Upgrade all auto-update-enabled plugins now')
        update_all_btn.clicked.connect(self.update_all_requested.emit)
        toolbar.addWidget(update_all_btn)
        outer.addLayout(toolbar)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setSpacing(PLUGIN_SECTION_SPACING)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

        self._loading_spinner = SpinnerWidget('Loading tools\u2026', parent=self)

    # --- Public API ---

    def refresh(self) -> None:
        """Schedule an asynchronous rebuild of the tool list."""
        if self._refresh_in_progress:
            return
        asyncio.create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        """Rebuild the tool list from porringer data.

        Fetches plugins and packages in parallel, then builds the
        widget tree.  Update-availability detection is deferred to a
        background task so the widget tree renders immediately.
        """
        self._refresh_in_progress = True
        self._loading_spinner.start()
        need_deferred_check = False

        try:
            data = await self._gather_refresh_data()
            need_deferred_check = not self._updates_checked
            self._build_widget_tree(data)
        except Exception:
            logger.exception('Failed to refresh tools')
            need_deferred_check = False
        finally:
            self._loading_spinner.stop()
            self._refresh_in_progress = False

        # Fire-and-forget: detect updates in the background, then patch
        # the just-rendered widget tree with update badges.
        if need_deferred_check:
            asyncio.create_task(self._deferred_update_check(self._directories))

    # ------------------------------------------------------------------
    # _async_refresh helper methods
    # ------------------------------------------------------------------

    async def _gather_refresh_data(self) -> _RefreshData:
        """Fetch plugins, packages, and manifest requirements in parallel.

        Returns:
            A :class:`_RefreshData` bundle containing all data needed
            to build the widget tree.
        """
        plugins, directories = await self._fetch_data()
        self._directories = directories

        updatable_plugins = [p for p in plugins if p.kind in _UPDATABLE_KINDS]

        async with asyncio.TaskGroup() as tg:
            pkg_tasks = {
                plugin.name: tg.create_task(
                    self._gather_packages(plugin.name, directories),
                )
                for plugin in updatable_plugins
            }
            req_tasks = [tg.create_task(self._gather_project_requirements(d)) for d in directories]
            tool_plugins_task = tg.create_task(self._gather_tool_plugins())

        packages_map = {name: task.result() for name, task in pkg_tasks.items()}

        # Merge tool-managed sub-plugins into the environment plugin
        # that owns the host tool (e.g. cppython → pipx's pdm entry).
        tool_plugins = tool_plugins_task.result()
        for host_tool, sub_packages in tool_plugins.items():
            for env_packages in packages_map.values():
                if any(entry.name == host_tool for entry in env_packages):
                    env_packages.extend(sub_packages)
                    break

        manifest_packages = self._collect_manifest_packages(req_tasks)

        return _RefreshData(
            plugins=plugins,
            packages_map=packages_map,
            manifest_packages=manifest_packages,
        )

    @staticmethod
    def _collect_manifest_packages(
        req_tasks: list[asyncio.Task[list[SetupAction]]],
    ) -> dict[str, set[str]]:
        """Extract manifest package names from completed requirement tasks."""
        manifest_packages: dict[str, set[str]] = {}
        for task in req_tasks:
            for action in task.result():
                if action.package and action.installer:
                    manifest_packages.setdefault(action.installer, set()).add(
                        str(action.package.name),
                    )
        return manifest_packages

    def _build_widget_tree(self, data: _RefreshData) -> None:
        """Clear existing widgets and rebuild the tool/package tree."""
        self._clear_section_widgets()

        auto_update_map = self._config.plugin_auto_update or {}
        kind_buckets = self._bucket_by_kind(data.plugins, data.packages_map)

        sorted_kinds = sorted(
            kind_buckets,
            key=lambda k: _KIND_DISPLAY_ORDER.get(k, 99),
        )

        for kind in sorted_kinds:
            self._insert_section_widget(PluginKindHeader(kind, parent=self._container))
            for plugin in kind_buckets[kind]:
                self._build_plugin_section(plugin, data, auto_update_map)

    def _clear_section_widgets(self) -> None:
        """Remove and delete all current section widgets."""
        for widget in self._section_widgets:
            self._container_layout.removeWidget(widget)
            widget.deleteLater()
        self._section_widgets.clear()

    @staticmethod
    def _bucket_by_kind(
        plugins: list[PluginInfo],
        packages_map: dict[str, list[PackageEntry]],
    ) -> OrderedDict[PluginKind, list[PluginInfo]]:
        """Group updatable plugins by kind, filtering out empty entries."""
        buckets: OrderedDict[PluginKind, list[PluginInfo]] = OrderedDict()
        for plugin in plugins:
            if plugin.kind not in _UPDATABLE_KINDS:
                continue
            has_content = plugin.tool_version is not None or bool(packages_map.get(plugin.name))
            if has_content:
                buckets.setdefault(plugin.kind, []).append(plugin)
        return buckets

    def _build_plugin_section(
        self,
        plugin: PluginInfo,
        data: _RefreshData,
        auto_update_map: dict[str, bool | dict[str, bool]],
    ) -> None:
        """Build the provider header and package rows for a single plugin."""
        auto_val = auto_update_map.get(plugin.name, True)
        plugin_updates = self._updates_available.get(plugin.name, set())

        provider = PluginProviderHeader(
            plugin,
            auto_val is not False,
            show_controls=True,
            has_updates=bool(plugin_updates),
            parent=self._container,
        )
        provider.auto_update_toggled.connect(self._on_auto_update_toggled)
        provider.update_requested.connect(self.plugin_update_requested.emit)
        self._insert_section_widget(provider)

        plugin_manifest = data.manifest_packages.get(plugin.name, set())
        raw_packages = data.packages_map.get(plugin.name, [])
        merged = self._merge_raw_packages(raw_packages, plugin_manifest)

        if merged:
            for pkg_name, pkg in merged.items():
                pkg_auto = self._resolve_package_auto_update(auto_val, pkg_name, pkg.is_global)
                row = self._create_connected_row(
                    PluginRowData(
                        name=pkg_name,
                        project=', '.join(pkg.projects),
                        version=pkg.version,
                        plugin_name=plugin.name,
                        auto_update=pkg_auto,
                        show_toggle=True,
                        has_update=pkg_name in plugin_updates,
                        is_global=pkg.is_global,
                        host_tool=pkg.host_tool,
                        project_paths=list(pkg.project_paths),
                    ),
                )
                self._insert_section_widget(row)
        else:
            version_text = str(plugin.tool_version) if plugin.tool_version is not None else ''
            row = PluginRow(PluginRowData(name=plugin.name, version=version_text), parent=self._container)
            self._insert_section_widget(row)

    @staticmethod
    def _merge_raw_packages(
        raw_packages: list[PackageEntry],
        plugin_manifest: set[str],
    ) -> OrderedDict[str, MergedPackage]:
        """Deduplicate packages across directories into a merged view.

        Same package from multiple directories becomes one row with a
        combined project label.  Global packages are always deduplicated;
        manifest packages merge their project names.
        """
        merged: OrderedDict[str, MergedPackage] = OrderedDict()
        for entry in raw_packages:
            is_global = entry.name not in plugin_manifest
            if entry.name in merged:
                existing = merged[entry.name]
                if not is_global and entry.project_label and entry.project_label not in existing.projects:
                    existing.projects.append(entry.project_label)
                if not is_global and entry.project_path and entry.project_path not in existing.project_paths:
                    existing.project_paths.append(entry.project_path)
            else:
                merged[entry.name] = MergedPackage(
                    projects=([] if is_global else ([entry.project_label] if entry.project_label else [])),
                    project_paths=([] if is_global else ([entry.project_path] if entry.project_path else [])),
                    version=entry.version,
                    is_global=is_global,
                    host_tool=entry.host_tool,
                )
        return merged

    @staticmethod
    def _resolve_package_auto_update(
        auto_val: bool | dict[str, bool],
        pkg_name: str,
        is_global: bool,
    ) -> bool:
        """Determine the effective auto-update setting for a single package."""
        if isinstance(auto_val, dict):
            return auto_val.get(pkg_name, not is_global)
        if auto_val is False:
            return False
        return not is_global

    def _create_connected_row(self, data: PluginRowData) -> PluginRow:
        """Create a :class:`PluginRow` and wire all its signals."""
        row = PluginRow(data, parent=self._container)
        row.auto_update_toggled.connect(self._on_package_auto_update_toggled)
        row.update_requested.connect(self.package_update_requested.emit)
        row.remove_requested.connect(self.package_remove_requested.emit)
        row.navigate_to_project.connect(self.navigate_to_project_requested.emit)
        return row

    def _insert_section_widget(self, widget: QWidget) -> None:
        """Append a widget to the container layout above the stretch."""
        idx = self._container_layout.count() - 1
        self._container_layout.insertWidget(idx, widget)
        self._section_widgets.append(widget)

    async def _fetch_data(self) -> tuple[list[PluginInfo], list[ManifestDirectory]]:
        """Fetch plugin list and directories."""
        plugins = await self._porringer.plugin.list()
        directories = self._porringer.cache.list_directories()
        return plugins, directories

    async def _gather_packages(
        self,
        plugin_name: str,
        directories: list[ManifestDirectory],
    ) -> list[PackageEntry]:
        """Collect packages managed by *plugin_name*.

        A global query (``project_path=None``) is always issued so that
        globally-scoped plugins (pipx, apt, brew) report their packages
        — including injected packages — even when no directories are
        cached.  Per-directory queries run in parallel alongside it to
        capture project-scoped packages.

        Returns:
            A list of :class:`PackageEntry` instances.
        """
        packages: list[PackageEntry] = []

        async def _list_global() -> None:
            try:
                pkgs = await self._porringer.plugin.list_packages(plugin_name)
                packages.extend(
                    PackageEntry(
                        name=str(pkg.name),
                        version=str(pkg.version) if pkg.version else '',
                        host_tool=pkg.relation.host if pkg.relation else '',
                    )
                    for pkg in pkgs
                )
            except Exception:
                logger.debug(
                    'Could not list global packages for %s',
                    plugin_name,
                    exc_info=True,
                )

        async def _list_one(directory: ManifestDirectory) -> None:
            try:
                pkgs = await self._porringer.plugin.list_packages(
                    plugin_name,
                    Path(directory.path),
                )
                packages.extend(
                    PackageEntry(
                        name=str(pkg.name),
                        project_label=directory.name or str(directory.path),
                        version=str(pkg.version) if pkg.version else '',
                        host_tool=pkg.relation.host if pkg.relation else '',
                        project_path=str(directory.path),
                    )
                    for pkg in pkgs
                )
            except Exception:
                logger.debug(
                    'Could not list packages for %s in %s',
                    plugin_name,
                    directory.path,
                    exc_info=True,
                )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_list_global())
            for d in directories:
                tg.create_task(_list_one(d))
        return packages

    # ------------------------------------------------------------------
    # PluginManager sub-plugin discovery
    # ------------------------------------------------------------------

    async def _gather_tool_plugins(
        self,
    ) -> dict[str, list[PackageEntry]]:
        """Query :class:`PluginManager` instances for natively managed sub-plugins.

        Discovers project-environment plugins that implement the
        ``PluginManager`` protocol (e.g. PDM, Poetry) and calls
        ``installed_plugins()`` on each.  Each returned
        :class:`Package` carries a :class:`PackageRelation` whose
        *host* field identifies the parent tool.

        Returns:
            A dict mapping host-tool name (e.g. ``"pdm"``) to a list of
            :class:`PackageEntry` instances.
        """
        results: dict[str, list[PackageEntry]] = {}

        loop = asyncio.get_running_loop()
        managers = await loop.run_in_executor(None, self._discover_plugin_managers)

        async def _query(tool_name: str, manager: PluginManager) -> None:
            try:
                plugins = await manager.installed_plugins()
                results[tool_name] = [
                    PackageEntry(
                        name=str(pkg.name),
                        version=str(pkg.version) if pkg.version else '',
                        host_tool=pkg.relation.host if pkg.relation else tool_name,
                    )
                    for pkg in plugins
                ]
            except Exception:
                logger.debug(
                    'Could not list plugins for %s',
                    tool_name,
                    exc_info=True,
                )

        async with asyncio.TaskGroup() as tg:
            for tool_name, manager in managers.items():
                tg.create_task(_query(tool_name, manager))

        return results

    @staticmethod
    def _discover_plugin_managers() -> dict[str, PluginManager]:
        """Discover project-environment plugins implementing ``PluginManager`` (sync).

        Returns:
            A dict mapping tool name to :class:`PluginManager` instance.
        """
        project_types = Builder.find_plugins('project_environment', ProjectEnvironment)
        instances = Builder.build_plugins(project_types)
        managers: dict[str, PluginManager] = {}
        for _info, inst in zip(project_types, instances, strict=True):
            if isinstance(inst, PluginManager) and inst.is_available():
                managers[inst.tool_name()] = inst
        return managers

    async def _gather_project_requirements(
        self,
        directory: ManifestDirectory,
    ) -> list[SetupAction]:
        """Run a dry-run execute_stream for *directory* and collect actions."""
        actions: list[SetupAction] = []
        try:
            path = Path(directory.path)
            filenames = self._porringer.sync.manifest_filenames()
            manifest_path: Path | None = None
            for fname in filenames:
                candidate = path / fname
                if candidate.exists():
                    manifest_path = candidate
                    break

            if manifest_path is None:
                return actions

            params = SetupParameters(
                paths=[str(manifest_path)],
                dry_run=True,
                project_directory=path,
            )
            async with contextlib.aclosing(self._porringer.sync.execute_stream(params)) as stream:
                async for event in stream:
                    if event.kind == ProgressEventKind.MANIFEST_PARSED and event.manifest:
                        actions.extend(event.manifest.actions)
                        break
        except Exception:
            logger.debug(
                'Could not gather requirements for %s',
                directory.path,
                exc_info=True,
            )
        return actions

    # --- Callbacks ---

    def _on_auto_update_toggled(self, plugin_name: str, enabled: bool) -> None:
        """Persist the plugin-level auto-update toggle change to config."""
        mapping = dict(self._config.plugin_auto_update or {})

        if enabled:
            mapping.pop(plugin_name, None)
        else:
            mapping[plugin_name] = False

        new_value = mapping if mapping else None
        self._config = update_user_config(plugin_auto_update=new_value)
        logger.info('Auto-update for %s set to %s', plugin_name, enabled)

    def _on_package_auto_update_toggled(
        self,
        plugin_name: str,
        package_name: str,
        enabled: bool,
    ) -> None:
        """Persist a per-package auto-update override to the nested config dict."""
        mapping = dict(self._config.plugin_auto_update or {})
        current = mapping.get(plugin_name)

        if isinstance(current, dict):
            pkg_dict: dict[str, bool] = dict(current)
        else:
            pkg_dict = {}

        pkg_dict[package_name] = enabled

        if pkg_dict:
            mapping[plugin_name] = pkg_dict
        else:
            mapping.pop(plugin_name, None)

        new_value = mapping if mapping else None
        self._config = update_user_config(plugin_auto_update=new_value)
        logger.info(
            'Auto-update for %s/%s set to %s',
            plugin_name,
            package_name,
            enabled,
        )

    def _on_check_for_updates(self) -> None:
        """Start an inline update check with per-row spinners."""
        if self._check_in_progress or self._refresh_in_progress:
            return
        self._check_btn.setEnabled(False)
        self._check_btn.setText('Checking\u2026')
        self._set_all_checking(True)
        asyncio.create_task(self._run_inline_update_check())

    async def _run_inline_update_check(self) -> None:
        """Check for updates with inline spinners (no overlay / rebuild)."""
        self._check_in_progress = True
        try:
            self._updates_available = await self._check_for_updates(self._directories)
            self._updates_checked = True
            self._apply_update_badges()
        except Exception:
            logger.debug('Inline update check failed', exc_info=True)
        finally:
            self._set_all_checking(False)
            self._check_btn.setEnabled(True)
            self._check_btn.setText('Check for Updates')
            self._check_in_progress = False

    async def _check_for_updates(
        self,
        directories: list[ManifestDirectory],
    ) -> dict[str, set[str]]:
        """Detect available updates across cached manifests via dry-run.

        All directories are checked in parallel via ``asyncio.TaskGroup``.

        Returns a mapping of ``{plugin_name: {package_names…}}`` for
        packages that have a newer version available.
        """
        available: dict[str, set[str]] = {}

        async def _check_one(directory: ManifestDirectory) -> None:
            partial = await self._check_directory_updates(directory)
            for installer, packages in partial.items():
                available.setdefault(installer, set()).update(packages)

        async with asyncio.TaskGroup() as tg:
            for d in directories:
                tg.create_task(_check_one(d))

        return available

    async def _check_directory_updates(
        self,
        directory: ManifestDirectory,
    ) -> dict[str, set[str]]:
        """Check a single directory for available updates (dry-run)."""
        available: dict[str, set[str]] = {}
        try:
            path = Path(directory.path)
            filenames = self._porringer.sync.manifest_filenames()
            manifest_path: Path | None = None
            for fname in filenames:
                candidate = path / fname
                if candidate.exists():
                    manifest_path = candidate
                    break

            if manifest_path is None:
                return available

            params = SetupParameters(
                paths=[str(manifest_path)],
                dry_run=True,
                detect_updates=True,
                project_directory=path,
            )
            async for event in self._porringer.sync.execute_stream(params):
                if (
                    event.kind == ProgressEventKind.ACTION_COMPLETED
                    and event.result is not None
                    and event.result.skip_reason == SkipReason.UPDATE_AVAILABLE
                ):
                    action = event.result.action
                    if action.installer and action.package:
                        available.setdefault(action.installer, set()).add(
                            str(action.package.name),
                        )
        except Exception:
            logger.debug(
                'Could not detect updates for %s',
                directory.path,
                exc_info=True,
            )
        return available

    async def _deferred_update_check(
        self,
        directories: list[ManifestDirectory],
    ) -> None:
        """Run update detection in the background, then patch the widget tree.

        Called after the initial render so the user sees the tool list
        immediately while update badges are populated asynchronously.
        Inline per-row spinners provide visual feedback.
        """
        self._check_in_progress = True
        self._check_btn.setEnabled(False)
        self._check_btn.setText('Checking\u2026')
        self._set_all_checking(True)
        try:
            self._updates_available = await self._check_for_updates(directories)
            self._updates_checked = True
            self._apply_update_badges()
        except Exception:
            logger.debug('Deferred update check failed', exc_info=True)
        finally:
            self._set_all_checking(False)
            self._check_btn.setEnabled(True)
            self._check_btn.setText('Check for Updates')
            self._check_in_progress = False

    def _apply_update_badges(self) -> None:
        """Walk existing widgets and show/hide Update buttons based on detection results."""
        current_plugin: str = ''
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader):
                current_plugin = widget._plugin_name
                plugin_updates = self._updates_available.get(current_plugin, set())
                has = bool(plugin_updates)
                if widget._update_btn is not None:
                    widget._update_btn.setVisible(has)
            elif isinstance(widget, PluginRow) and widget._plugin_name:
                plugin_updates = self._updates_available.get(widget._plugin_name, set())
                has = widget._package_name in plugin_updates
                if widget._update_btn is not None:
                    widget._update_btn.setVisible(has)
                elif has:
                    # Need to create the button that wasn't built at render time
                    self._inject_update_button(widget)

    @staticmethod
    def _inject_update_button(row: PluginRow) -> None:
        """Dynamically add an Update button to a row that was built without one."""
        update_btn = QPushButton('Update')
        update_btn.setStyleSheet(PLUGIN_ROW_UPDATE_STYLE)
        update_btn.setToolTip(f'Update {row._package_name}')
        update_btn.clicked.connect(
            lambda: row.update_requested.emit(row._plugin_name, row._package_name),
        )
        row._update_btn = update_btn
        # Insert before the version label (last widget) if present, else append
        layout = row.layout()
        if isinstance(layout, QHBoxLayout):
            layout.insertWidget(max(layout.count() - 1, 0), update_btn)

    def _set_all_checking(self, checking: bool) -> None:
        """Show or hide inline checking spinners on all plugin rows."""
        for widget in self._section_widgets:
            if isinstance(widget, (PluginProviderHeader, PluginRow)):
                widget.set_checking(checking)

    def set_plugin_updating(self, plugin_name: str, updating: bool) -> None:
        """Toggle the *Updating…* state on the header for *plugin_name*."""
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader) and widget._plugin_name == plugin_name:
                widget.set_updating(updating)
                break

    def set_package_updating(
        self,
        plugin_name: str,
        package_name: str,
        updating: bool,
    ) -> None:
        """Toggle the *Updating…* state on a specific package row."""
        for widget in self._section_widgets:
            if (
                isinstance(widget, PluginRow)
                and widget._plugin_name == plugin_name
                and widget._package_name == package_name
            ):
                widget.set_updating(updating)
                break

    def set_package_removing(
        self,
        plugin_name: str,
        package_name: str,
        removing: bool,
    ) -> None:
        """Toggle the *Removing…* state on a specific package row."""
        for widget in self._section_widgets:
            if (
                isinstance(widget, PluginRow)
                and widget._plugin_name == plugin_name
                and widget._package_name == package_name
            ):
                widget.set_removing(removing)
                break

    def set_package_error(
        self,
        plugin_name: str,
        package_name: str,
        message: str,
    ) -> None:
        """Show a transient inline error on a specific package row."""
        for widget in self._section_widgets:
            if (
                isinstance(widget, PluginRow)
                and widget._plugin_name == plugin_name
                and widget._package_name == package_name
            ):
                widget.set_error(message)
                break

    def set_plugin_error(self, plugin_name: str, message: str) -> None:
        """Show a transient inline error on the header for *plugin_name*."""
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader) and widget._plugin_name == plugin_name:
                widget.set_error(message)
                break


class ProjectsView(QWidget):
    """Widget for managing project directories and previewing their manifests.

    Displays a vertical sidebar of cached project directories on the
    left with a stacked widget on the right showing one
    :class:`SetupPreviewWidget` per manifest.  All manifests are loaded
    in parallel on first refresh; switching between them is instant.
    """

    def __init__(self, porringer: API, config: ResolvedConfig, parent: QWidget | None = None) -> None:
        """Initialize the projects view.

        Args:
            porringer: The porringer API instance.
            config: Resolved configuration.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._config = config
        self._refresh_in_progress = False
        self._pending_select: Path | None = None
        self._widgets: dict[Path, SetupPreviewWidget] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        """Build the sidebar + stacked widget layout."""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left — sidebar
        self._sidebar = ManifestSidebar()
        self._sidebar.add_requested.connect(self._on_add)
        self._sidebar.remove_requested.connect(self._on_remove)
        self._sidebar.selection_changed.connect(self._on_selection_changed)
        outer.addWidget(self._sidebar)

        # Right — stacked previews + empty placeholder
        right = QVBoxLayout()
        right.setContentsMargins(*COMPACT_MARGINS)
        right.setSpacing(0)

        self._stack = QStackedWidget()
        right.addWidget(self._stack, stretch=1)

        # Empty placeholder shown when there are no manifests
        self._empty_placeholder = QLabel('No projects. Click + Add Project to get started.')
        self._empty_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_placeholder.setStyleSheet('color: grey; font-size: 13px;')
        self._stack.addWidget(self._empty_placeholder)

        outer.addLayout(right, stretch=1)

        self._loading_spinner = SpinnerWidget('Loading projects\u2026', parent=self)

    # --- Public API ---

    def refresh(self) -> None:
        """Schedule an asynchronous refresh of the cached directories."""
        if self._refresh_in_progress:
            return
        asyncio.create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        """Refresh the sidebar and stacked widgets from the porringer cache."""
        self._refresh_in_progress = True
        self._loading_spinner.start()
        self._sidebar.set_enabled(False)

        try:
            previous = self._pending_select or self._sidebar.selected_path
            self._pending_select = None

            loop = asyncio.get_running_loop()
            results: list[DirectoryValidationResult] = await loop.run_in_executor(
                None,
                lambda: self._porringer.cache.validate_directories(check_manifest=True),
            )

            directories: list[tuple[Path, str, bool]] = []
            current_paths: set[Path] = set()
            for result in results:
                d = result.directory
                valid = result.exists and result.has_manifest is not False
                path = Path(d.path)
                directories.append((path, d.name or '', valid))
                current_paths.add(path)

            # Remove widgets for directories no longer in cache
            for path in list(self._widgets):
                if path not in current_paths:
                    widget = self._widgets.pop(path)
                    self._stack.removeWidget(widget)
                    widget.reset()
                    widget.deleteLater()

            # Create new widgets for new directories
            for path, _name, valid in directories:
                if path not in self._widgets and valid:
                    widget = SetupPreviewWidget(
                        self._porringer,
                        self,
                        show_close=False,
                        config=self._config,
                    )
                    widget.install_finished.connect(self._on_install_finished)
                    widget.phase_changed.connect(
                        lambda phase, p=path: self._on_widget_phase_changed(p, phase),
                    )
                    self._widgets[path] = widget
                    self._stack.addWidget(widget)

            # Rebuild sidebar
            self._sidebar.set_directories(directories)
            self._sidebar.select(previous)

            # Load all stacked widgets in parallel
            for path, _name, valid in directories:
                widget = self._widgets.get(path)
                if widget is not None and valid:
                    widget.load(
                        str(path),
                        project_directory=path if path.is_dir() else path.parent,
                        detect_updates=self._config.detect_updates,
                    )

        except Exception:
            logger.exception('Failed to refresh projects')
        finally:
            self._loading_spinner.stop()
            self._sidebar.set_enabled(True)
            self._refresh_in_progress = False

    # --- Event handlers ---

    def _on_selection_changed(self, path: Path) -> None:
        """Handle sidebar selection — switch the stacked widget."""
        widget = self._widgets.get(path)
        if widget is not None:
            self._stack.setCurrentWidget(widget)
        else:
            self._stack.setCurrentWidget(self._empty_placeholder)

    def _on_widget_phase_changed(self, path: Path, phase: PreviewPhase) -> None:
        """Update the sidebar item's phase indicator."""
        item = self._sidebar.get_item(path)
        if item is not None:
            item.set_phase(phase)

    def _on_add(self) -> None:
        """Open a file picker and immediately cache the chosen directory."""
        filenames = self._porringer.sync.manifest_filenames()
        filter_str = 'Manifests (' + ' '.join(filenames) + ');;All Files (*)'
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            'Select Manifest File',
            '',
            filter_str,
        )
        if not chosen:
            return

        selected = Path(chosen)
        directory = selected if selected.is_dir() else selected.parent

        try:
            self._porringer.cache.add_directory(directory)
            logger.info('Cached new project directory: %s', directory)
        except ValueError:
            logger.debug('Directory already cached: %s', directory)

        self._pending_select = directory
        self.refresh()

    def _on_remove(self, path: Path) -> None:
        """Remove a directory from the porringer cache."""
        self._porringer.cache.remove_directory(path)
        logger.info('Removed project directory from cache: %s', path)

        # Tear down the widget immediately
        widget = self._widgets.pop(path, None)
        if widget is not None:
            self._stack.removeWidget(widget)
            widget.reset()
            widget.deleteLater()

        self.refresh()

    def _on_install_finished(self, _results: object) -> None:
        """Refresh after a successful install."""
        self.refresh()


class MainWindow(QMainWindow):
    """Main window for the application."""

    settings_requested = Signal()
    """Emitted when the user clicks the settings gear button."""

    tools_view_created = Signal(ToolsView)
    """Emitted once when the :class:`ToolsView` is lazily initialised."""

    _tabs: QTabWidget | None = None
    _tools_view: ToolsView | None = None
    _projects_view: ProjectsView | None = None

    def __init__(
        self,
        porringer: API | None = None,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialize the main window.

        Args:
            porringer: Optional porringer API instance for manifest display.
            config: Resolved configuration for plugin auto-update state.
        """
        super().__init__()
        self._porringer = porringer
        self._config = config
        self.setWindowTitle('Synodic Client')
        self.setMinimumSize(*MAIN_WINDOW_MIN_SIZE)
        self.setWindowIcon(app_icon())

        # Update banner — always available, starts hidden.
        self._update_banner = UpdateBanner(self)

    @property
    def porringer(self) -> API | None:
        """Return the porringer API instance, if available."""
        return self._porringer

    @property
    def tools_view(self) -> ToolsView | None:
        """Return the tools view, if initialised."""
        return self._tools_view

    @property
    def update_banner(self) -> UpdateBanner:
        """Return the update banner widget."""
        return self._update_banner

    def show(self) -> None:
        """Show the window, initializing UI lazily on first show."""
        if self._tabs is None and self._porringer is not None and self._config is not None:
            self._tabs = QTabWidget(self)

            self._projects_view = ProjectsView(self._porringer, self._config, self)
            self._tabs.addTab(self._projects_view, 'Projects')

            self._tools_view = ToolsView(self._porringer, self._config, self)
            self._tabs.addTab(self._tools_view, 'Tools')
            self.tools_view_created.emit(self._tools_view)

            # Navigate-to-project: switch to Projects tab and select directory
            self._tools_view.navigate_to_project_requested.connect(self._navigate_to_project)

            gear_btn = QPushButton('\u2699')
            gear_btn.setStyleSheet(SETTINGS_GEAR_STYLE)
            gear_btn.setToolTip('Settings')
            gear_btn.setFlat(True)
            gear_btn.clicked.connect(self.settings_requested.emit)
            self._tabs.setCornerWidget(gear_btn)

            # Container: banner above tabs
            container = QWidget(self)
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            container_layout.addWidget(self._update_banner)
            container_layout.addWidget(self._tabs)
            self.setCentralWidget(container)

        # Paint the window immediately, then refresh data asynchronously
        super().show()

        if self._tools_view is not None:
            self._tools_view.refresh()
        if self._projects_view is not None:
            self._projects_view.refresh()

    def _navigate_to_project(self, path_str: str) -> None:
        """Switch to the Projects tab and select the given directory."""
        if self._tabs is not None and self._projects_view is not None:
            self._tabs.setCurrentIndex(0)
            self._projects_view._sidebar.select(Path(path_str))


class Screen:
    """Screen class for the Synodic Client application."""

    _window: MainWindow | None = None

    def __init__(
        self,
        porringer: API | None = None,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialize the screen.

        Args:
            porringer: Optional porringer API instance.
            config: Resolved configuration.
        """
        self._porringer = porringer
        self._config = config

    @property
    def window(self) -> MainWindow:
        """Lazily create the main window on first access.

        Returns:
            The MainWindow instance.
        """
        if self._window is None:
            self._window = MainWindow(self._porringer, self._config)
        return self._window
