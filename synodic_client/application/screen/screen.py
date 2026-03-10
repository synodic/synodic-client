"""Screen class for the Synodic Client application."""

import asyncio
import logging
import traceback
from collections import OrderedDict
from pathlib import Path

from porringer.api import API
from porringer.backend.builder import Builder
from porringer.core.plugin_schema.plugin_manager import PluginManager
from porringer.core.plugin_schema.project_environment import ProjectEnvironment
from porringer.schema import (
    ManifestDirectory,
    PluginInfo,
    ProgressEventKind,
    SetupAction,
    SetupParameters,
    SkipReason,
    SyncStrategy,
)
from porringer.schema.plugin import PluginKind, RuntimePackageResult
from porringer.utility.exception import PluginError
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.config_store import ConfigStore
from synodic_client.application.data import DataCoordinator
from synodic_client.application.icon import app_icon
from synodic_client.application.package_state import PackageStateStore
from synodic_client.application.screen.plugin_row import (
    FilterChip,
    PluginKindHeader,
    PluginProviderHeader,
    PluginRow,
)
from synodic_client.application.screen.projects import ProjectsView
from synodic_client.application.screen.schema import (
    DisplayPackage,
    PackageEntry,
    PluginRowData,
    ProjectInstance,
    RefreshData,
)
from synodic_client.application.screen.spinner import LoadingIndicator
from synodic_client.application.screen.update_banner import UpdateBanner
from synodic_client.application.theme import (
    COMPACT_MARGINS,
    FILTER_CHIP_SPACING,
    FILTER_PANEL_ANIMATION_MS,
    FILTER_TOGGLE_ACTIVE_STYLE,
    FILTER_TOGGLE_STYLE,
    MAIN_WINDOW_MIN_SIZE,
    PLUGIN_ROW_STATUS_AVAILABLE_STYLE,
    PLUGIN_ROW_STATUS_UP_TO_DATE_STYLE,
    PLUGIN_SECTION_SPACING,
    SEARCH_INPUT_STYLE,
    SETTINGS_GEAR_STYLE,
)

logger = logging.getLogger(__name__)

# Plugin kinds that support auto-update and per-plugin upgrade.
_UPDATABLE_KINDS = frozenset({PluginKind.TOOL, PluginKind.PACKAGE, PluginKind.RUNTIME})

# Kinds whose packages are inherently global (no per-directory queries).
_GLOBAL_ONLY_KINDS = frozenset({PluginKind.RUNTIME})

# Preferred display ordering â€” Tools first, then alphabetical for the rest.
_KIND_DISPLAY_ORDER: dict[PluginKind, int] = {
    PluginKind.TOOL: 0,
    PluginKind.PACKAGE: 1,
    PluginKind.RUNTIME: 2,
    PluginKind.PROJECT: 3,
    PluginKind.SCM: 4,
}


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
        store: ConfigStore,
        parent: QWidget | None = None,
        *,
        coordinator: DataCoordinator | None = None,
        package_store: PackageStateStore | None = None,
    ) -> None:
        """Initialize the tools view.

        Args:
            porringer: The porringer API instance.
            store: The centralised :class:`ConfigStore`.
            parent: Optional parent widget.
            coordinator: Shared data coordinator.  When provided, the
                view delegates plugin/directory fetching to the
                coordinator instead of calling porringer directly.
            package_store: Shared package update state registry.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._store = store
        self._coordinator = coordinator
        self._package_store = package_store
        self._section_widgets: list[QWidget] = []
        self._filter_chips: dict[str, FilterChip] = {}
        self._deselected_plugins: set[str] = set()
        self._refresh_in_progress = False
        self._check_in_progress = False
        self._directories: list[ManifestDirectory] = []
        self._timestamp_timer: QTimer | None = None
        self._init_ui()

        if self._package_store is not None:
            self._package_store.state_changed.connect(self._on_package_state_changed)

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*COMPACT_MARGINS)

        outer.addLayout(self._build_toolbar())

        # Collapsible filter panel â€” search input + chip row
        self._filter_panel = QWidget()
        self._filter_panel.setMaximumHeight(0)
        self._filter_panel.setVisible(False)
        filter_layout = QVBoxLayout(self._filter_panel)
        filter_layout.setContentsMargins(0, 4, 0, 4)
        filter_layout.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText('Search packages\u2026')
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(SEARCH_INPUT_STYLE)
        self._search_input.textChanged.connect(self._apply_filter)
        self._search_input.installEventFilter(self)
        filter_layout.addWidget(self._search_input)

        # Filter chips row â€” auto-populated from discovered plugins
        chip_container = QWidget()
        self._chip_layout = QHBoxLayout(chip_container)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(FILTER_CHIP_SPACING)
        self._chip_layout.addStretch()
        filter_layout.addWidget(chip_container)

        outer.addWidget(self._filter_panel)

        # Animation for filter panel slide-in / slide-out
        self._filter_anim = QPropertyAnimation(self._filter_panel, b'maximumHeight')
        self._filter_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._filter_anim.setDuration(FILTER_PANEL_ANIMATION_MS)
        self._filter_panel_open = False

        # Ctrl+F shortcut to toggle filter panel
        QShortcut(QKeySequence.StandardKey.Find, self, self._toggle_filter_panel)

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

        self._loading_indicator = LoadingIndicator('Loading tools\u2026')
        outer.addWidget(self._loading_indicator)

        # Periodic timer to refresh relative timestamps (every 60s)
        self._timestamp_timer = QTimer(self)
        self._timestamp_timer.setInterval(60_000)
        self._timestamp_timer.timeout.connect(self._refresh_timestamps)
        self._timestamp_timer.start()

    def _build_toolbar(self) -> QHBoxLayout:
        """Build the toolbar with filter toggle and action buttons."""
        toolbar = QHBoxLayout()

        self._filter_btn = QPushButton('\U0001f50d')
        self._filter_btn.setToolTip('Filter packages (Ctrl+F)')
        self._filter_btn.setFlat(True)
        self._filter_btn.setStyleSheet(FILTER_TOGGLE_STYLE)
        self._filter_btn.clicked.connect(self._toggle_filter_panel)
        toolbar.addWidget(self._filter_btn)

        toolbar.addStretch()

        check_btn = QPushButton('Check for Updates')
        check_btn.setToolTip('Scan all manifests for available package updates')
        check_btn.clicked.connect(self._on_check_for_updates)
        toolbar.addWidget(check_btn)
        self._check_btn = check_btn

        self._update_all_btn = QPushButton('Update All')
        self._update_all_btn.setToolTip('Upgrade all auto-update-enabled plugins now')
        self._update_all_btn.clicked.connect(self.update_all_requested.emit)
        toolbar.addWidget(self._update_all_btn)

        return toolbar

    # --- Public API ---

    def invalidate_update_data(self) -> None:
        """Clear cached update state so the next refresh re-checks."""
        if self._package_store is not None:
            self._package_store.clear()

    def refresh(self) -> None:
        """Schedule an asynchronous rebuild of the tool list."""
        if self._refresh_in_progress:
            return
        logger.debug('ToolsView.refresh() called (visible=%s)', self.isVisible())
        asyncio.create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        """Rebuild the tool list from porringer data.

        Fetches plugins and packages in parallel, then builds the
        widget tree.  Update-availability detection is deferred to a
        background task so the widget tree renders immediately.
        """
        self._refresh_in_progress = True
        self._scroll.hide()
        self._loading_indicator.start()
        self._check_btn.setEnabled(False)
        self._update_all_btn.setEnabled(False)
        need_deferred_check = False

        try:
            data = await self._gather_refresh_data()
            need_deferred_check = not self._has_update_data
            self._build_widget_tree(data)
        except Exception:
            logger.exception('Failed to refresh tools')
            need_deferred_check = False
        finally:
            self._loading_indicator.stop()
            self._scroll.show()
            self._check_btn.setEnabled(True)
            self._update_all_btn.setEnabled(True)
            self._refresh_in_progress = False

        # Fire-and-forget: detect updates in the background, then patch
        # the just-rendered widget tree with update badges.
        if need_deferred_check:
            asyncio.create_task(self._deferred_update_check())

    # ------------------------------------------------------------------
    # _async_refresh helper methods
    # ------------------------------------------------------------------

    async def _gather_refresh_data(self) -> RefreshData:
        """Fetch plugins, packages, and manifest requirements in parallel.

        For PACKAGE-kind plugins that are ``RuntimeConsumer`` instances,
        per-runtime package queries are attempted via
        ``list_packages_by_runtime``.  Plugins that succeed are excluded
        from the regular global package query (their global packages come
        from the per-runtime results); venv-scoped packages are still
        gathered via the standard ``_gather_packages`` path with
        ``skip_global=True``.

        Returns:
            A :class:`RefreshData` bundle containing all data needed
            to build the widget tree.
        """
        plugins, directories = await self._fetch_data()
        self._directories = directories

        updatable_plugins = [p for p in plugins if p.kind in _UPDATABLE_KINDS]
        discovered = self._coordinator.discovered_plugins if self._coordinator else None

        # --- Per-runtime probing for PACKAGE-kind plugins ---
        runtime_packages: dict[str, list] = {}
        runtime_probed: set[str] = set()

        package_plugins = [p for p in updatable_plugins if p.kind == PluginKind.PACKAGE]
        if package_plugins and discovered is not None:
            probe_tasks: dict[str, asyncio.Task] = {}
            async with asyncio.TaskGroup() as tg:
                for plugin in package_plugins:
                    probe_tasks[plugin.name] = tg.create_task(
                        self._gather_runtime_packages(plugin.name, discovered),
                    )
            for name, task in probe_tasks.items():
                result = task.result()
                if result is not None:
                    runtime_packages[name] = result
                    runtime_probed.add(name)

        # --- Standard package queries ---
        async with asyncio.TaskGroup() as tg:
            pkg_tasks: dict[str, asyncio.Task] = {}
            for plugin in updatable_plugins:
                if plugin.name in runtime_probed:
                    # Runtime-probed plugins show only per-runtime
                    # packages; venv/project packages belong in
                    # ProjectsView and are intentionally skipped here.
                    continue
                else:
                    pkg_tasks[plugin.name] = tg.create_task(
                        self._gather_packages(
                            plugin.name,
                            [] if plugin.kind in _GLOBAL_ONLY_KINDS else directories,
                        ),
                    )
            req_tasks = [tg.create_task(self._gather_project_requirements(d)) for d in directories]
            tool_plugins_task = tg.create_task(self._gather_tool_plugins())

        packages_map = {name: task.result() for name, task in pkg_tasks.items()}

        # Merge tool-managed sub-plugins into the environment plugin
        # that owns the host tool (e.g. cppython → pipx's pdm entry).
        for host_tool, sub_packages in tool_plugins_task.result().items():
            for env_packages in packages_map.values():
                if any(entry.name == host_tool for entry in env_packages):
                    env_packages.extend(sub_packages)
                    break

        manifest_packages = self._collect_manifest_packages(req_tasks)

        # Extract default runtime executable
        default_runtime_executable = None
        if discovered is not None and discovered.runtime_context is not None:
            default_runtime_executable = discovered.runtime_context.get('python')

        return RefreshData(
            plugins=plugins,
            packages_map=packages_map,
            manifest_packages=manifest_packages,
            runtime_packages=runtime_packages,
            default_runtime_executable=default_runtime_executable,
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

    def _build_widget_tree(self, data: RefreshData) -> None:
        """Clear existing widgets and rebuild the tool/package tree."""
        self._clear_section_widgets()

        auto_update_map = self._store.config.plugin_auto_update or {}
        kind_buckets = self._bucket_by_kind(
            data.plugins,
            data.packages_map,
            data.runtime_packages,
        )

        sorted_kinds = sorted(
            kind_buckets,
            key=lambda k: _KIND_DISPLAY_ORDER.get(k, 99),
        )

        for kind in sorted_kinds:
            self._insert_section_widget(PluginKindHeader(kind, parent=self._container))
            for plugin in kind_buckets[kind]:
                if plugin.name in data.runtime_packages:
                    self._build_runtime_sections(plugin, data, auto_update_map)
                else:
                    self._build_plugin_section(plugin, data, auto_update_map)

        self._rebuild_chips()
        self._apply_filter()

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
        runtime_packages: dict[str, list] | None = None,
    ) -> OrderedDict[PluginKind, list[PluginInfo]]:
        """Group updatable plugins by kind, filtering out empty entries."""
        buckets: OrderedDict[PluginKind, list[PluginInfo]] = OrderedDict()
        rp = runtime_packages or {}
        for plugin in plugins:
            if plugin.kind not in _UPDATABLE_KINDS:
                continue
            has_content = (
                plugin.tool_version is not None or bool(packages_map.get(plugin.name)) or bool(rp.get(plugin.name))
            )
            if has_content:
                buckets.setdefault(plugin.kind, []).append(plugin)
        return buckets

    def _build_runtime_sections(
        self,
        plugin: PluginInfo,
        data: RefreshData,
        auto_update_map: dict[str, bool | dict[str, bool]],
    ) -> None:
        """Build per-runtime provider headers and package rows.

        Each ``RuntimePackageResult`` becomes a separate
        :class:`PluginProviderHeader` with a runtime tag pill.
        The default runtime (matched by executable) is placed first.
        """
        runtime_results: list[RuntimePackageResult] = data.runtime_packages[plugin.name]
        if not runtime_results:
            return

        auto_val = auto_update_map.get(plugin.name, True)
        tool_timestamps = self._store.config.last_tool_updates or {}
        default_exe = data.default_runtime_executable

        # Sort: default runtime first, then descending by tag
        def _sort_key(rt: RuntimePackageResult) -> tuple[int, str]:
            is_default = 1 if (default_exe is not None and rt.executable == default_exe) else 0
            return (-is_default, rt.tag)

        sorted_results = sorted(runtime_results, key=_sort_key)

        for rt in sorted_results:
            is_default = default_exe is not None and rt.executable == default_exe
            tag_text = f'Python {rt.tag}'
            if is_default:
                tag_text += ' (default)'

            # Runtime updates use composite keys "plugin:tag"
            rt_updates = self._get_plugin_updates(f'{plugin.name}:{rt.tag}')

            provider = PluginProviderHeader(
                plugin,
                auto_val is not False,
                show_controls=True,
                has_updates=bool(rt_updates),
                parent=self._container,
            )
            provider.set_runtime(rt.tag, label=tag_text)
            provider.auto_update_toggled.connect(self._on_auto_update_toggled)
            provider.update_requested.connect(self.plugin_update_requested.emit)
            self._insert_section_widget(provider)

            # Convert RuntimePackageResult.packages to PackageEntry list
            raw_packages = [
                PackageEntry(
                    name=str(pkg.name),
                    version=str(pkg.version) if pkg.version else '',
                    host_tool=pkg.relation.host if pkg.relation else '',
                )
                for pkg in rt.packages
            ]
            plugin_manifest = data.manifest_packages.get(plugin.name, set())
            display_packages = self._build_display_packages(raw_packages, plugin_manifest)

            for pkg in display_packages:
                pkg_auto = self._resolve_package_auto_update(auto_val, pkg.name, pkg.is_global)
                ts_key = f'{plugin.name}/{pkg.name}'
                row = self._create_connected_row(
                    PluginRowData(
                        name=pkg.name,
                        version=pkg.global_version or '',
                        plugin_name=plugin.name,
                        auto_update=pkg_auto,
                        show_toggle=True,
                        has_update=pkg.name in rt_updates,
                        is_global=True,
                        host_tool=pkg.host_tool,
                        runtime_tag=rt.tag,
                        last_updated=tool_timestamps.get(ts_key, ''),
                    ),
                )
                self._insert_section_widget(row)

    def _build_plugin_section(
        self,
        plugin: PluginInfo,
        data: RefreshData,
        auto_update_map: dict[str, bool | dict[str, bool]],
    ) -> None:
        """Build the provider header and package rows for a single plugin.

        For each package a :class:`PluginRow` is created with inline
        project-name tags for project-scoped occurrences.  Separate
        ``ProjectChildRow`` widgets are no longer used.
        """
        auto_val = auto_update_map.get(plugin.name, True)
        plugin_updates = self._get_plugin_updates(plugin.name)

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
        display_packages = self._build_display_packages(raw_packages, plugin_manifest)
        tool_timestamps = self._store.config.last_tool_updates or {}

        if display_packages:
            for pkg in display_packages:
                pkg_auto = self._resolve_package_auto_update(auto_val, pkg.name, pkg.is_global)
                ts_key = f'{plugin.name}/{pkg.name}'
                row = self._create_connected_row(
                    PluginRowData(
                        name=pkg.name,
                        version=pkg.global_version or '',
                        plugin_name=plugin.name,
                        auto_update=pkg_auto,
                        show_toggle=True,
                        has_update=pkg.name in plugin_updates,
                        is_global=pkg.is_global,
                        host_tool=pkg.host_tool,
                        project_instances=list(pkg.project_instances),
                        last_updated=tool_timestamps.get(ts_key, ''),
                    ),
                )
                self._insert_section_widget(row)
        else:
            version_text = str(plugin.tool_version) if plugin.tool_version is not None else ''
            row = PluginRow(PluginRowData(name=plugin.name, version=version_text), parent=self._container)
            self._insert_section_widget(row)

    @staticmethod
    def _build_display_packages(
        raw_packages: list[PackageEntry],
        plugin_manifest: set[str],
    ) -> list[DisplayPackage]:
        """Build a two-tier display model from raw package entries.

        Each unique package name produces one :class:`DisplayPackage`.
        Global entries (no ``project_path``) set the global version;
        project-scoped entries become :class:`ProjectInstance` children.
        A project-scoped package is marked *transitive* when it is not
        declared in any manifest for this plugin.

        Returns:
            An ordered list of :class:`DisplayPackage` instances, with
            globals first, then project-only packages.
        """
        by_name: OrderedDict[str, DisplayPackage] = OrderedDict()
        for entry in raw_packages:
            from_project = bool(entry.project_path)

            if entry.name not in by_name:
                by_name[entry.name] = DisplayPackage(
                    name=entry.name,
                    host_tool=entry.host_tool,
                )

            dp = by_name[entry.name]

            if not from_project:
                # Global entry
                dp.is_global = True
                dp.global_version = entry.version
            else:
                # Project-scoped entry
                is_transitive = entry.name not in plugin_manifest
                # Deduplicate by project_path
                existing_paths = {pi.project_path for pi in dp.project_instances}
                if entry.project_path not in existing_paths:
                    dp.project_instances.append(
                        ProjectInstance(
                            project_label=entry.project_label,
                            project_path=entry.project_path,
                            version=entry.version,
                            is_transitive=is_transitive,
                        ),
                    )

        return list(by_name.values())

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

    # ------------------------------------------------------------------
    # Search & filter
    # ------------------------------------------------------------------

    def _rebuild_chips(self) -> None:
        """Rebuild the filter chip row from currently visible plugin providers.

        Preserves previous deselection state: if a chip was unchecked
        before a refresh, it stays unchecked (subtractive model).
        """
        # Remove old chips
        for chip in self._filter_chips.values():
            self._chip_layout.removeWidget(chip)
            chip.deleteLater()
        self._filter_chips.clear()

        # Collect unique plugin names in order
        seen: set[str] = set()
        plugin_names: list[str] = []
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader):
                name = widget._plugin_name
                if name not in seen:
                    seen.add(name)
                    plugin_names.append(name)

        # Create chips â€” insert before the trailing stretch
        stretch_idx = self._chip_layout.count() - 1
        for name in plugin_names:
            chip = FilterChip(name, parent=self._chip_layout.parentWidget())
            chip.setChecked(name not in self._deselected_plugins)
            chip.toggled_with_name.connect(self._on_chip_toggled)
            self._chip_layout.insertWidget(stretch_idx, chip)
            self._filter_chips[name] = chip
            stretch_idx += 1

    def _on_chip_toggled(self, plugin_name: str, checked: bool) -> None:
        """Track deselected plugins and reapply the filter."""
        if checked:
            self._deselected_plugins.discard(plugin_name)
        else:
            self._deselected_plugins.add(plugin_name)
        self._apply_filter()

    # ------------------------------------------------------------------
    # Filter panel toggle & animation
    # ------------------------------------------------------------------

    @property
    def _has_active_filter(self) -> bool:
        """Return whether any search text or deselected chip is active."""
        return bool(self._search_input.text().strip()) or bool(self._deselected_plugins)

    def _toggle_filter_panel(self) -> None:
        """Slide the filter panel open or closed."""
        if self._filter_panel_open:
            self._close_filter_panel()
        else:
            self._open_filter_panel()

    def _open_filter_panel(self) -> None:
        """Slide the filter panel in and focus the search input."""
        if self._filter_panel_open:
            return
        self._filter_panel_open = True
        self._filter_panel.setVisible(True)
        self._filter_panel.adjustSize()
        target = self._filter_panel.sizeHint().height()
        self._filter_anim.stop()
        self._filter_anim.setStartValue(self._filter_panel.maximumHeight())
        self._filter_anim.setEndValue(target)
        self._filter_anim.start()
        self._search_input.setFocus()

    def _close_filter_panel(self) -> None:
        """Slide the filter panel out and return focus to the toggle button."""
        if not self._filter_panel_open:
            return
        self._filter_panel_open = False
        self._filter_anim.stop()
        self._filter_anim.setStartValue(self._filter_panel.maximumHeight())
        self._filter_anim.setEndValue(0)
        self._filter_anim.finished.connect(
            self._on_filter_panel_closed,
            type=Qt.ConnectionType.SingleShotConnection,
        )
        self._filter_anim.start()

    def _on_filter_panel_closed(self) -> None:
        """Hide the panel widget after slide-out completes."""
        if not self._filter_panel_open:
            self._filter_panel.setVisible(False)
        self._filter_btn.setFocus()

    def _update_filter_badge(self) -> None:
        """Swap the toggle-button style to indicate active filters."""
        style = FILTER_TOGGLE_ACTIVE_STYLE if self._has_active_filter else FILTER_TOGGLE_STYLE
        self._filter_btn.setStyleSheet(style)

    def _clear_active_filters(self) -> None:
        """Reset search text and re-check all deselected chips."""
        self._search_input.clear()
        for name in list(self._deselected_plugins):
            chip = self._filter_chips.get(name)
            if chip is not None:
                chip.setChecked(True)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle Escape in the search input to clear filters / close panel."""
        if (
            obj is self._search_input
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            if self._has_active_filter:
                self._clear_active_filters()
            else:
                self._close_filter_panel()
            return True
        return super().eventFilter(obj, event)

    def _active_chip_plugins(self) -> set[str] | None:
        """Return the set of plugin names whose chips are checked.

        Returns ``None`` when no chips exist yet (initial state before
        any refresh), meaning all plugins should be shown.
        """
        if not self._filter_chips:
            return None
        return {name for name, chip in self._filter_chips.items() if chip.isChecked()}

    @staticmethod
    def _is_plugin_active(plugin_name: str, active: set[str] | None) -> bool:
        """Return whether *plugin_name* passes the chip filter."""
        return active is None or plugin_name in active

    @staticmethod
    def _finalise_provider(
        provider: PluginProviderHeader | None,
        has_visible: bool,
    ) -> bool:
        """Set provider visibility and return whether it had visible children."""
        if provider is not None:
            provider.setVisible(has_visible)
        return has_visible

    def _apply_filter(self, _text: str | None = None) -> None:
        """Show/hide section widgets based on search text and active chips.

        Delegates to :meth:`_is_plugin_active` for chip matching and
        :meth:`_finalise_provider` for provider visibility bookkeeping.
        """
        query = self._search_input.text().strip().lower()
        active = self._active_chip_plugins()

        current_kind_header: PluginKindHeader | None = None
        kind_has_visible = False
        current_provider: PluginProviderHeader | None = None
        provider_has_visible_child = False

        for widget in self._section_widgets:
            if isinstance(widget, PluginKindHeader):
                kind_has_visible |= self._finalise_provider(current_provider, provider_has_visible_child)
                if current_kind_header is not None:
                    current_kind_header.setVisible(kind_has_visible)

                current_kind_header = widget
                kind_has_visible = False
                current_provider = None
                provider_has_visible_child = False

            elif isinstance(widget, PluginProviderHeader):
                kind_has_visible |= self._finalise_provider(current_provider, provider_has_visible_child)

                current_provider = widget
                provider_has_visible_child = False
                if not self._is_plugin_active(widget._plugin_name, active):
                    widget.setVisible(False)

            elif isinstance(widget, PluginRow):
                if not self._is_plugin_active(widget._plugin_name, active):
                    widget.setVisible(False)
                    continue

                # Match search query against package name, plugin name, and project labels
                name_match = not query or (
                    query in widget._package_name.lower()
                    or query in widget._plugin_name.lower()
                    or any(query in lbl.lower() for lbl in widget._project_labels)
                )
                widget.setVisible(name_match)
                if name_match:
                    provider_has_visible_child = True

        # Finalise last provider and kind
        kind_has_visible |= self._finalise_provider(current_provider, provider_has_visible_child)
        if current_kind_header is not None:
            current_kind_header.setVisible(kind_has_visible)

        self._update_filter_badge()

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
        """Fetch plugin list and directories via the coordinator (or direct fallback)."""
        if self._coordinator is not None:
            snapshot = await self._coordinator.refresh()
            return snapshot.plugins, snapshot.directories
        plugins = await self._porringer.plugin.list()
        directories = [r.directory for r in self._porringer.cache.list_directories()]
        return plugins, directories

    async def _gather_packages(
        self,
        plugin_name: str,
        directories: list[ManifestDirectory],
        *,
        skip_global: bool = False,
    ) -> list[PackageEntry]:
        """Collect packages managed by *plugin_name*.

        A global query (``project_path=None``) is always issued so that
        globally-scoped plugins (pipx, apt, brew) report their packages
        â€” including injected packages â€” even when no directories are
        cached.  Per-directory queries run in parallel alongside it to
        capture project-scoped packages.

        Returns:
            A list of :class:`PackageEntry` instances.
        """
        packages: list[PackageEntry] = []
        discovered = self._coordinator.discovered_plugins if self._coordinator else None

        async def _list_global() -> None:
            try:
                pkgs = await self._porringer.package.list(
                    plugin_name,
                    plugins=discovered,
                )
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
                pkgs = await self._porringer.package.list(
                    plugin_name,
                    Path(directory.path),
                    plugins=discovered,
                )
                packages.extend(
                    PackageEntry(
                        name=str(pkg.name),
                        project_label=directory.name or Path(directory.path).stem,
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
            if not skip_global:
                tg.create_task(_list_global())
            for d in directories:
                tg.create_task(_list_one(d))
        return packages

    async def _gather_runtime_packages(self, plugin_name: str, discovered) -> list | None:
        """Try ``list_packages_by_runtime`` for *plugin_name*.

        Returns the list of :class:`RuntimePackageResult` on success,
        or ``None`` when the plugin is not a ``RuntimeConsumer``.
        """
        try:
            return await self._porringer.package.list_by_runtime(
                plugin_name,
                plugins=discovered,
            )
        except PluginError:
            return None
        except Exception:
            logger.debug(
                'Per-runtime probe failed for %s',
                plugin_name,
                exc_info=True,
            )
            return None

        # ------------------------------------------------------------------

    # PluginManager sub-plugin discovery
    # ------------------------------------------------------------------

    async def _gather_tool_plugins(
        self,
    ) -> dict[str, list[PackageEntry]]:
        """Query :class:`PluginManager` instances for natively managed sub-plugins.

        Uses the coordinator's pre-discovered ``plugin_managers`` when
        available, avoiding redundant ``Builder.find_plugins`` calls.

        Returns:
            A dict mapping host-tool name (e.g. ``"pdm"``) to a list of
            :class:`PackageEntry` instances.
        """
        results: dict[str, list[PackageEntry]] = {}

        if self._coordinator is not None:
            managers = self._coordinator.snapshot.plugin_managers
        else:
            # Fallback: discover from scratch (legacy path / tests)
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

        Fallback for when no ``DataCoordinator`` is available.

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
        """Load the manifest for *directory* and return its actions.

        When a :class:`DataCoordinator` is available the efficient
        ``async_load_manifest`` path is used (no streaming, no
        ``aclosing`` needed).  The legacy ``execute_stream`` path is
        kept as a fallback for tests and headless usage.
        """
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

            discovered = self._coordinator.discovered_plugins if self._coordinator else None

            if discovered is not None:
                # Fast path: single-shot manifest load
                result = await self._porringer.sync.async_load_manifest(
                    manifest_path,
                    SyncStrategy.MINIMAL,
                    plugins=discovered,
                )
                actions.extend(result.actions)
            else:
                # Legacy path: stream and break after first parse
                params = SetupParameters(
                    paths=[str(manifest_path)],
                    dry_run=True,
                    project_directory=path,
                )
                async for event in self._porringer.sync.execute_stream(params):
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
        mapping = dict(self._store.config.plugin_auto_update or {})

        if enabled:
            mapping.pop(plugin_name, None)
        else:
            mapping[plugin_name] = False

        new_value = mapping if mapping else None
        self._store.update(plugin_auto_update=new_value)
        logger.info('Auto-update for %s set to %s', plugin_name, enabled)

    def _on_package_auto_update_toggled(
        self,
        plugin_name: str,
        package_name: str,
        enabled: bool,
    ) -> None:
        """Persist a per-package auto-update override to the nested config dict."""
        mapping = dict(self._store.config.plugin_auto_update or {})
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
        self._store.update(plugin_auto_update=new_value)
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
        """Check for updates with inline spinners (no overlay / rebuild).

        Used by both the manual *Check for Updates* button and the
        automatic deferred check after initial refresh.
        """
        self._check_in_progress = True
        try:
            available = await self._check_for_updates(self._directories)
            self._store_check_results(available)
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
    ) -> dict[str, dict[str, str]]:
        """Detect available updates across cached manifests.

        When a :class:`DataCoordinator` is available the efficient
        ``check_updates()`` API is used (single call, no streaming).
        Falls back to per-directory ``execute_stream`` dry-runs
        otherwise.

        Returns a mapping of ``{plugin_name: {package_name: latest_version}}``
        for packages that have a newer version available.
        """
        if self._coordinator is not None:
            return await self._check_updates_via_coordinator()

        # Legacy per-directory fallback
        available: dict[str, dict[str, str]] = {}

        async def _check_one(directory: ManifestDirectory) -> None:
            partial = await self._check_directory_updates(directory)
            for installer, packages in partial.items():
                available.setdefault(installer, {}).update(packages)

        async with asyncio.TaskGroup() as tg:
            for d in directories:
                tg.create_task(_check_one(d))

        return available

    async def _check_updates_via_coordinator(self) -> dict[str, dict[str, str]]:
        """Use the coordinator's ``check_updates`` for efficient detection.

        Fetches both flat (global) and per-runtime update results.
        Per-runtime entries use composite keys ``"plugin:tag"`` so that
        :meth:`_apply_update_badges` can match runtime-specific headers.
        """
        assert self._coordinator is not None
        results, runtime_results = await asyncio.gather(
            self._coordinator.check_updates(),
            self._coordinator.check_updates_by_runtime(),
        )
        available: dict[str, dict[str, str]] = {}

        # Flat (global) results keyed by bare plugin name
        for cr in results:
            if cr.success:
                for pi in cr.packages:
                    if pi.update_available:
                        latest = str(pi.latest_version) if pi.latest_version else ''
                        available.setdefault(cr.plugin, {})[pi.name] = latest

        # Per-runtime results keyed by composite "plugin:tag"
        for rcr in runtime_results:
            for cr in rcr.results:
                if cr.success:
                    for pi in cr.packages:
                        if pi.update_available:
                            composite = f'{cr.plugin}:{rcr.tag}'
                            latest = str(pi.latest_version) if pi.latest_version else ''
                            available.setdefault(composite, {})[pi.name] = latest

        return available

    async def _check_directory_updates(
        self,
        directory: ManifestDirectory,
    ) -> dict[str, dict[str, str]]:
        """Check a single directory for available updates (dry-run).

        Legacy fallback used when no coordinator is available.
        """
        available: dict[str, dict[str, str]] = {}
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
                        pkg_name = str(action.package.name)
                        latest = event.result.available_version or ''
                        available.setdefault(action.installer, {})[pkg_name] = latest
        except Exception:
            logger.debug(
                'Could not detect updates for %s',
                directory.path,
                exc_info=True,
            )
        return available

    async def _deferred_update_check(self) -> None:
        """Run update detection in the background, then patch the widget tree.

        Called after the initial render so the user sees the tool list
        immediately while update badges are populated asynchronously.
        Delegates to :meth:`_run_inline_update_check`.
        """
        self._check_btn.setEnabled(False)
        self._check_btn.setText('Checking\u2026')
        self._set_all_checking(True)
        await self._run_inline_update_check()

    def _get_plugin_updates(self, signal_key: str) -> dict[str, str]:
        """Return ``{package_name: latest_version}`` for *signal_key*.

        Reads from the shared :class:`PackageStateStore` when available,
        otherwise returns an empty dict.
        """
        if self._package_store is not None:
            return self._package_store.get_updates(signal_key)
        return {}

    def _store_check_results(self, available: dict[str, dict[str, str]]) -> None:
        """Push check results into the store."""
        if self._package_store is not None:
            self._package_store.set_check_results(available)

    @property
    def _has_update_data(self) -> bool:
        """Return whether update data has been fetched at least once."""
        return self._package_store is not None and self._package_store.has_data

    def _on_package_state_changed(self) -> None:
        """Re-apply badges when another view writes to the shared store."""
        if not self._check_in_progress and not self._refresh_in_progress:
            self._apply_update_badges()

    def _apply_update_badges(self) -> None:
        """Walk existing widgets and show/hide Update buttons + set inline status."""
        current_plugin: str = ''
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader):
                current_plugin = widget._signal_key
                plugin_updates = self._get_plugin_updates(current_plugin)
                has = bool(plugin_updates)
                if widget._update_btn is not None:
                    widget._update_btn.setVisible(has)
            elif isinstance(widget, PluginRow) and widget._plugin_name:
                plugin_updates = self._get_plugin_updates(widget._signal_key)
                latest_version = plugin_updates.get(widget._package_name)
                has_update = latest_version is not None

                if widget._update_btn is not None:
                    widget._update_btn.setVisible(has_update)

                # Set inline status text
                if has_update:
                    version_text = f'v{latest_version} available' if latest_version else 'Update available'
                    widget.set_update_status(version_text, PLUGIN_ROW_STATUS_AVAILABLE_STYLE)
                elif self._has_update_data:
                    widget.set_update_status('Up to date', PLUGIN_ROW_STATUS_UP_TO_DATE_STYLE)

    def _set_all_checking(self, checking: bool) -> None:
        """Show or hide inline checking spinners on all plugin rows."""
        for widget in self._section_widgets:
            if isinstance(widget, (PluginProviderHeader, PluginRow)):
                widget.set_checking(checking)

    def _refresh_timestamps(self) -> None:
        """Refresh relative time labels on all plugin rows (called by timer)."""
        for widget in self._section_widgets:
            if isinstance(widget, PluginRow):
                widget.update_timestamp()

    def set_plugin_updating(self, plugin_name: str, updating: bool) -> None:
        """Toggle the *Updatingâ€¦* state on the header for *plugin_name*."""
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader) and widget._signal_key == plugin_name:
                widget.set_updating(updating)
                break

    def set_package_updating(
        self,
        plugin_name: str,
        package_name: str,
        updating: bool,
    ) -> None:
        """Toggle the *Updatingâ€¦* state on a specific package row."""
        for widget in self._section_widgets:
            if (
                isinstance(widget, PluginRow)
                and widget._signal_key == plugin_name
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
        """Toggle the *Removingâ€¦* state on a specific package row."""
        for widget in self._section_widgets:
            if (
                isinstance(widget, PluginRow)
                and widget._signal_key == plugin_name
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
                and widget._signal_key == plugin_name
                and widget._package_name == package_name
            ):
                widget.set_error(message)
                break

    def set_plugin_error(self, plugin_name: str, message: str) -> None:
        """Show a transient inline error on the header for *plugin_name*."""
        for widget in self._section_widgets:
            if isinstance(widget, PluginProviderHeader) and widget._signal_key == plugin_name:
                widget.set_error(message)
                break


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
        store: ConfigStore | None = None,
    ) -> None:
        """Initialize the main window.

        Args:
            porringer: Optional porringer API instance for manifest display.
            store: The centralised :class:`ConfigStore`.
        """
        super().__init__()
        self._porringer = porringer
        self._store = store
        self._coordinator: DataCoordinator | None = DataCoordinator(porringer) if porringer is not None else None
        self._package_store: PackageStateStore | None = PackageStateStore(self) if porringer is not None else None
        self.setWindowTitle('Synodic Client')
        self.setMinimumSize(*MAIN_WINDOW_MIN_SIZE)
        self.setWindowIcon(app_icon())

        # Update banner â€” always available, starts hidden.
        self._update_banner = UpdateBanner(self)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """[DIAG] Log every show event with a stack trace."""
        geo = self.geometry()
        stack = ''.join(traceback.format_stack(limit=10))
        logger.debug(
            '[DIAG] MainWindow.showEvent: geo=(%d,%d %dx%d) visible=%s\n%s',
            geo.x(),
            geo.y(),
            geo.width(),
            geo.height(),
            self.isVisible(),
            stack,
        )
        super().showEvent(event)

    @property
    def porringer(self) -> API | None:
        """Return the porringer API instance, if available."""
        return self._porringer

    @property
    def coordinator(self) -> DataCoordinator | None:
        """Return the shared data coordinator, if available."""
        return self._coordinator

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
        if self._tabs is None and self._porringer is not None and self._store is not None:
            self._tabs = QTabWidget(self)

            self._projects_view = ProjectsView(
                self._porringer,
                self._store,
                self,
                coordinator=self._coordinator,
                package_store=self._package_store,
            )
            self._tabs.addTab(self._projects_view, 'Projects')

            self._tools_view = ToolsView(
                self._porringer,
                self._store,
                self,
                coordinator=self._coordinator,
                package_store=self._package_store,
            )
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
        store: ConfigStore | None = None,
    ) -> None:
        """Initialize the screen.

        Args:
            porringer: Optional porringer API instance.
            store: The centralised :class:`ConfigStore`.
        """
        self._porringer = porringer
        self._store = store

    @property
    def window(self) -> MainWindow:
        """Lazily create the main window on first access.

        Returns:
            The MainWindow instance.
        """
        if self._window is None:
            self._window = MainWindow(self._porringer, self._store)
        return self._window
