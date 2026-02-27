"""Screen class for the Synodic Client application."""

import asyncio
import logging
from collections import OrderedDict
from pathlib import Path

from porringer.api import API
from porringer.schema import (
    DirectoryValidationResult,
    ManifestDirectory,
    PluginInfo,
    ProgressEventKind,
    SetupAction,
    SetupParameters,
)
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
    PLUGIN_ROW_GLOBAL_STYLE,
    PLUGIN_ROW_NAME_STYLE,
    PLUGIN_ROW_PROJECT_STYLE,
    PLUGIN_ROW_STYLE,
    PLUGIN_ROW_TOGGLE_STYLE,
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

# Preferred display ordering — Tools first, then alphabetical for the rest.
_KIND_DISPLAY_ORDER: dict[PluginKind, int] = {
    PluginKind.TOOL: 0,
    PluginKind.PACKAGE: 1,
    PluginKind.RUNTIME: 2,
    PluginKind.PROJECT: 3,
    PluginKind.SCM: 4,
}


# ---------------------------------------------------------------------------
# Plugin kind header — uppercase section divider
# ---------------------------------------------------------------------------


class PluginKindHeader(QLabel):
    """Uppercase, muted section divider for a plugin-kind group.

    Displays a label like ``TOOLS`` or ``PACKAGES`` with a subtle bottom
    border, matching VS Code's sidebar heading style.
    """

    def __init__(self, kind: PluginKind, parent: QWidget | None = None) -> None:
        super().__init__(plugin_kind_group_label(kind).upper(), parent)
        self.setObjectName('pluginKindHeader')
        self.setStyleSheet(PLUGIN_KIND_HEADER_STYLE)


# ---------------------------------------------------------------------------
# Plugin provider header — thin row for the managing plugin
# ---------------------------------------------------------------------------


class PluginProviderHeader(QFrame):
    """Thin sub-header row identifying the plugin that provides a set of tools.

    Shows the plugin name, version, installed status, and — for updatable
    kinds — ``Auto`` and ``Update`` buttons.
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName('pluginProvider')
        self.setStyleSheet(PLUGIN_PROVIDER_STYLE)
        self._plugin_name = plugin.name

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

            update_btn = QPushButton('Update')
            update_btn.setStyleSheet(PLUGIN_UPDATE_STYLE)
            update_btn.setToolTip(f'Upgrade packages via {plugin.name} now')
            update_btn.clicked.connect(
                lambda: self.update_requested.emit(self._plugin_name),
            )
            layout.addWidget(update_btn)

            if not plugin.installed:
                toggle_btn.setEnabled(False)
                toggle_btn.setChecked(False)
                toggle_btn.setToolTip('Not installed \u2014 cannot auto-update')
                update_btn.setEnabled(False)
                update_btn.setToolTip('Not installed \u2014 cannot update')


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
    """

    auto_update_toggled = Signal(str, str, bool)
    """Emitted with ``(plugin_name, package_name, enabled)`` on toggle."""

    def __init__(
        self,
        name: str,
        project: str = '',
        version: str = '',
        *,
        plugin_name: str = '',
        auto_update: bool = False,
        show_toggle: bool = False,
        is_global: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName('pluginRow')
        self.setStyleSheet(PLUGIN_ROW_STYLE)
        self._plugin_name = plugin_name
        self._package_name = name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        name_label = QLabel(name)
        name_label.setStyleSheet(PLUGIN_ROW_NAME_STYLE)
        layout.addWidget(name_label)

        if project:
            project_label = QLabel(project)
            project_label.setStyleSheet(PLUGIN_ROW_PROJECT_STYLE)
            layout.addWidget(project_label)
        elif is_global:
            global_label = QLabel('(global)')
            global_label.setStyleSheet(PLUGIN_ROW_GLOBAL_STYLE)
            layout.addWidget(global_label)

        layout.addStretch()

        if show_toggle:
            toggle_btn = QPushButton('Auto')
            toggle_btn.setCheckable(True)
            toggle_btn.setChecked(auto_update)
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

        if version:
            version_label = QLabel(version)
            version_label.setStyleSheet(PLUGIN_ROW_VERSION_STYLE)
            layout.addWidget(version_label)


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
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*COMPACT_MARGINS)

        # Loading indicator
        self._loading_spinner = SpinnerWidget('Loading tools\u2026')
        outer.addWidget(self._loading_spinner)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addStretch()
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

    # --- Public API ---

    def refresh(self) -> None:
        """Schedule an asynchronous rebuild of the tool list."""
        if self._refresh_in_progress:
            return
        asyncio.create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        """Rebuild the tool list from porringer data.

        Walks every cached project manifest to determine which packages
        are *manifest-referenced* vs. *global*.  Manifest packages
        default to auto-update **on**; global packages default to **off**.
        Per-package toggles honour the nested-dict config shape.
        """
        self._refresh_in_progress = True
        self._loading_spinner.start()

        try:
            loop = asyncio.get_running_loop()
            plugins, directories = await loop.run_in_executor(
                None,
                self._fetch_data,
            )

            # Gather packages for updatable plugins
            packages_map: dict[str, list[tuple[str, str, str]]] = {}
            for plugin in plugins:
                if plugin.kind in _UPDATABLE_KINDS:
                    packages_map[plugin.name] = await self._gather_packages(
                        plugin.name,
                        directories,
                    )

            # Gather manifest requirements → plugin_name → set of package names
            manifest_packages: dict[str, set[str]] = {}
            for directory in directories:
                actions = await self._gather_project_requirements(directory)
                for action in actions:
                    if action.package and action.installer:
                        manifest_packages.setdefault(action.installer, set()).add(
                            str(action.package.name),
                        )

            # Clear existing widgets
            for widget in self._section_widgets:
                self._container_layout.removeWidget(widget)
                widget.deleteLater()
            self._section_widgets.clear()

            auto_update_map = self._config.plugin_auto_update or {}

            # Only show TOOL / PACKAGE kinds that have content
            updatable = [p for p in plugins if p.kind in _UPDATABLE_KINDS]

            # Bucket by kind
            kind_buckets: OrderedDict[PluginKind, list[PluginInfo]] = OrderedDict()
            for plugin in updatable:
                has_version = plugin.tool_version is not None
                has_packages = bool(packages_map.get(plugin.name))
                if has_version or has_packages:
                    kind_buckets.setdefault(plugin.kind, []).append(plugin)

            sorted_kinds = sorted(
                kind_buckets.keys(),
                key=lambda k: _KIND_DISPLAY_ORDER.get(k, 99),
            )

            for kind in sorted_kinds:
                bucket = kind_buckets[kind]

                kind_header = PluginKindHeader(kind, parent=self._container)
                idx = self._container_layout.count() - 1
                self._container_layout.insertWidget(idx, kind_header)
                self._section_widgets.append(kind_header)

                for plugin in bucket:
                    auto_val = auto_update_map.get(plugin.name, True)
                    provider_checked = auto_val is not False

                    provider = PluginProviderHeader(
                        plugin,
                        provider_checked,
                        show_controls=True,
                        parent=self._container,
                    )
                    provider.auto_update_toggled.connect(self._on_auto_update_toggled)
                    provider.update_requested.connect(self.plugin_update_requested.emit)
                    idx = self._container_layout.count() - 1
                    self._container_layout.insertWidget(idx, provider)
                    self._section_widgets.append(provider)

                    plugin_manifest = manifest_packages.get(plugin.name, set())
                    raw_packages = packages_map.get(plugin.name, [])

                    # Merge duplicates: same package from multiple
                    # directories becomes one row with a combined
                    # project label.  Global packages are always
                    # deduplicated; manifest packages merge their
                    # project names with ", ".
                    merged: OrderedDict[str, tuple[list[str], str, bool]] = OrderedDict()
                    for pkg_name, proj_name, pkg_version in raw_packages:
                        is_global = pkg_name not in plugin_manifest
                        if pkg_name in merged:
                            existing_projects, _, _ = merged[pkg_name]
                            if not is_global and proj_name and proj_name not in existing_projects:
                                existing_projects.append(proj_name)
                        else:
                            projects = [] if is_global else ([proj_name] if proj_name else [])
                            merged[pkg_name] = (projects, pkg_version, is_global)

                    if merged:
                        for pkg_name, (
                            projects,
                            pkg_version,
                            is_global,
                        ) in merged.items():
                            # Determine per-package auto-update state
                            if isinstance(auto_val, dict):
                                pkg_auto = auto_val.get(pkg_name, not is_global)
                            elif auto_val is False:
                                pkg_auto = False
                            else:
                                pkg_auto = not is_global

                            row = PluginRow(
                                pkg_name,
                                project=', '.join(projects),
                                version=pkg_version,
                                plugin_name=plugin.name,
                                auto_update=pkg_auto,
                                show_toggle=True,
                                is_global=is_global,
                                parent=self._container,
                            )
                            row.auto_update_toggled.connect(
                                self._on_package_auto_update_toggled,
                            )
                            idx = self._container_layout.count() - 1
                            self._container_layout.insertWidget(idx, row)
                            self._section_widgets.append(row)
                    else:
                        version_text = str(plugin.tool_version) if plugin.tool_version is not None else ''
                        row = PluginRow(
                            plugin.name,
                            version=version_text,
                            parent=self._container,
                        )
                        idx = self._container_layout.count() - 1
                        self._container_layout.insertWidget(idx, row)
                        self._section_widgets.append(row)

        except Exception:
            logger.exception('Failed to refresh tools')
        finally:
            self._loading_spinner.stop()
            self._refresh_in_progress = False

    def _fetch_data(self) -> tuple[list[PluginInfo], list[ManifestDirectory]]:
        """Fetch plugin list and directories (sync, run in executor)."""
        plugins = self._porringer.plugin.list()
        directories = self._porringer.cache.list_directories()
        return plugins, directories

    async def _gather_packages(
        self,
        plugin_name: str,
        directories: list[ManifestDirectory],
    ) -> list[tuple[str, str, str]]:
        """Collect packages managed by *plugin_name* across cached projects.

        Returns:
            A list of ``(package_name, project_label, version)`` tuples.
        """
        packages: list[tuple[str, str, str]] = []
        for directory in directories:
            try:
                pkgs = await self._porringer.plugin.list_packages(
                    plugin_name,
                    Path(directory.path),
                )
                for pkg in pkgs:
                    packages.append(
                        (
                            str(pkg.name),
                            directory.name or str(directory.path),
                            str(pkg.version) if pkg.version else '',
                        ),
                    )
            except Exception:
                logger.debug(
                    'Could not list packages for %s in %s',
                    plugin_name,
                    directory.path,
                    exc_info=True,
                )
        return packages

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

        # Floating overlay spinner — positioned in resizeEvent
        self._loading_spinner = SpinnerWidget('Loading projects\u2026', parent=self)
        self._loading_spinner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._loading_spinner.raise_()

    # ------------------------------------------------------------------
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the overlay spinner filling the entire view."""
        super().resizeEvent(event)
        self._loading_spinner.setGeometry(self.rect())

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
            self._loading_spinner.lower()
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
