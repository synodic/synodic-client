"""Screen class for the Synodic Client application."""

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from porringer.api import API
from porringer.schema import DirectoryValidationResult, ManifestDirectory, PluginInfo, PluginKind, SetupResults
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen import plugin_kind_group_label
from synodic_client.application.screen.install import PreviewWorker, SetupPreviewWidget
from synodic_client.application.theme import (
    COMPACT_MARGINS,
    LOG_CHEVRON_STYLE,
    LOG_SECTION_TITLE_STYLE,
    MAIN_WINDOW_MIN_SIZE,
    PLUGIN_GROUP_HEADER_STYLE,
    PLUGIN_GROUP_SECTION_SPACING,
    PLUGIN_GROUP_TITLE_STYLE,
    PLUGIN_SECTION_HEADER_STYLE,
    PLUGIN_SECTION_SPACING,
    PLUGIN_TOGGLE_STYLE,
    PLUGIN_UPDATE_STYLE,
)
from synodic_client.config import GlobalConfiguration, save_config

logger = logging.getLogger(__name__)

# Plugin kinds that support auto-update and per-plugin upgrade.
_UPDATABLE_KINDS = frozenset({PluginKind.TOOL, PluginKind.PACKAGE})

# Unicode chevrons
_CHEVRON_DOWN = '\u25bc'
_CHEVRON_RIGHT = '\u25b6'


@dataclass
class PluginSectionData:
    """Data needed to construct a :class:`PluginSection`."""

    name: str
    version: str
    packages: list[tuple[str, str]] = field(default_factory=list)
    auto_update: bool = True
    show_controls: bool = False
    found: bool = True


class PluginSection(QWidget):
    """Collapsible section displaying a single plugin and its managed packages."""

    auto_update_toggled = Signal(str, bool)
    """Emitted with ``(plugin_name, enabled)`` when the auto-update toggle changes."""

    update_requested = Signal(str)
    """Emitted with the plugin name when the per-plugin Update button is clicked."""

    def __init__(self, data: PluginSectionData, parent: QWidget | None = None) -> None:
        """Initialise the section.

        Args:
            data: Plugin metadata and package list.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._plugin_name = data.name
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = self._build_header(
            data.name,
            data.version,
            data.auto_update,
            data.show_controls,
            found=data.found,
        )
        layout.addWidget(self._header)

        self._body = self._build_body(data.packages)
        self._body.setVisible(False)
        layout.addWidget(self._body)

    # --- Header / body builders ---

    def _build_header(
        self,
        plugin_name: str,
        version: str,
        auto_update: bool,
        show_controls: bool,
        *,
        found: bool = True,
    ) -> QWidget:
        """Construct the clickable header row."""
        header = QWidget()
        header.setObjectName('pluginHeader')
        header.setStyleSheet(PLUGIN_SECTION_HEADER_STYLE)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda _event: self._toggle()

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self._chevron = QLabel(_CHEVRON_RIGHT)
        self._chevron.setStyleSheet(LOG_CHEVRON_STYLE)
        self._chevron.setFixedWidth(14)
        header_layout.addWidget(self._chevron)

        title = QLabel(plugin_name)
        title.setStyleSheet(LOG_SECTION_TITLE_STYLE)
        header_layout.addWidget(title)

        version_label = QLabel(version)
        version_label.setStyleSheet('color: grey;')
        header_layout.addWidget(version_label)

        header_layout.addStretch()

        if show_controls:
            self._toggle_btn = QPushButton('Auto')
            self._toggle_btn.setCheckable(True)
            self._toggle_btn.setChecked(auto_update)
            self._toggle_btn.setStyleSheet(PLUGIN_TOGGLE_STYLE)
            self._toggle_btn.setToolTip('Enable automatic updates for this plugin')
            self._toggle_btn.clicked.connect(self._on_toggle_clicked)
            header_layout.addWidget(self._toggle_btn)

            update_btn = QPushButton('Update')
            update_btn.setStyleSheet(PLUGIN_UPDATE_STYLE)
            update_btn.setToolTip(f'Upgrade packages via {plugin_name} now')
            update_btn.clicked.connect(
                lambda: self.update_requested.emit(self._plugin_name),
            )
            header_layout.addWidget(update_btn)

            if not found:
                self._toggle_btn.setEnabled(False)
                self._toggle_btn.setChecked(False)
                self._toggle_btn.setToolTip('Plugin not found \u2014 cannot auto-update')
                update_btn.setEnabled(False)
                update_btn.setToolTip('Plugin not found \u2014 cannot update')

        return header

    @staticmethod
    def _build_body(packages: list[tuple[str, str]]) -> QWidget:
        """Construct the collapsible body with a package table."""
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 4, 0, 4)
        body_layout.setSpacing(2)

        if packages:
            table = QTableWidget(len(packages), 2)
            table.setHorizontalHeaderLabels(['Package', 'Project'])
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)
            h = table.horizontalHeader()
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            for row, (pkg, proj) in enumerate(packages):
                table.setItem(row, 0, QTableWidgetItem(pkg))
                table.setItem(row, 1, QTableWidgetItem(proj))
            body_layout.addWidget(table)
        else:
            body_layout.addWidget(QLabel('No packages found'))

        return body

    # --- Collapse / expand ---

    def _toggle(self) -> None:
        """Toggle the body visibility."""
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._chevron.setText(_CHEVRON_DOWN if self._expanded else _CHEVRON_RIGHT)

    # --- Callbacks ---

    def _on_toggle_clicked(self, checked: bool) -> None:
        """Forward auto-update toggle state change."""
        self.auto_update_toggled.emit(self._plugin_name, checked)


class PluginGroupSection(QWidget):
    """Collapsible group of :class:`PluginSection` widgets sharing the same kind.

    The group header displays a human-readable label derived from the
    :class:`~porringer.schema.PluginKind`.  New kinds are handled
    automatically via :func:`plugin_kind_group_label`.
    """

    def __init__(
        self,
        kind: PluginKind,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the group section.

        Args:
            kind: The plugin kind this group represents.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._kind = kind
        self._expanded = True
        self._sections: list[PluginSection] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = self._build_header(kind)
        layout.addWidget(self._header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 0, 0, 0)
        self._body_layout.setSpacing(PLUGIN_GROUP_SECTION_SPACING)
        layout.addWidget(self._body)

    # --- Header builder ---

    def _build_header(self, kind: PluginKind) -> QWidget:
        """Construct the clickable group header row."""
        header = QWidget()
        header.setObjectName('pluginGroupHeader')
        header.setStyleSheet(PLUGIN_GROUP_HEADER_STYLE)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda _event: self._toggle()

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self._chevron = QLabel(_CHEVRON_DOWN)
        self._chevron.setStyleSheet(LOG_CHEVRON_STYLE)
        self._chevron.setFixedWidth(14)
        header_layout.addWidget(self._chevron)

        title = QLabel(plugin_kind_group_label(kind))
        title.setStyleSheet(PLUGIN_GROUP_TITLE_STYLE)
        header_layout.addWidget(title)

        header_layout.addStretch()
        return header

    # --- Public helpers ---

    @property
    def kind(self) -> PluginKind:
        """Return the plugin kind for this group."""
        return self._kind

    @property
    def sections(self) -> list[PluginSection]:
        """Return the child plugin sections."""
        return list(self._sections)

    def add_section(self, section: PluginSection) -> None:
        """Append a :class:`PluginSection` to this group."""
        self._body_layout.addWidget(section)
        self._sections.append(section)

    # --- Collapse / expand ---

    def _toggle(self) -> None:
        """Toggle the body visibility."""
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._chevron.setText(_CHEVRON_DOWN if self._expanded else _CHEVRON_RIGHT)


class PluginsView(QWidget):
    """Scrollable list of collapsible plugin sections with auto-update controls."""

    update_all_requested = Signal()
    """Emitted when the global *Update All* button is clicked."""

    plugin_update_requested = Signal(str)
    """Emitted with a plugin name when its per-plugin *Update* button is clicked."""

    def __init__(
        self,
        porringer: API,
        config: GlobalConfiguration,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the plugins view.

        Args:
            porringer: The porringer API instance.
            config: Resolved global configuration (for auto-update toggles).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._config = config
        self._groups: list[PluginGroupSection] = []
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*COMPACT_MARGINS)

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
        """Rebuild the plugin sections from porringer data, grouped by kind."""
        # Clear existing groups
        for group in self._groups:
            self._container_layout.removeWidget(group)
            group.deleteLater()
        self._groups.clear()

        plugins = self._porringer.plugin.list()
        directories = self._porringer.cache.list_directories()
        auto_update_map = self._config.plugin_auto_update or {}

        # Bucket plugins by kind, preserving discovery order within each bucket
        kind_buckets: OrderedDict[PluginKind, list[PluginInfo]] = OrderedDict()
        for plugin in plugins:
            kind_buckets.setdefault(plugin.kind, []).append(plugin)

        for kind, bucket in kind_buckets.items():
            group = PluginGroupSection(kind, parent=self._container)

            for plugin in bucket:
                section = self._build_plugin_section(
                    plugin,
                    directories,
                    auto_update_map,
                    parent=group,
                )
                section.auto_update_toggled.connect(self._on_auto_update_toggled)
                section.update_requested.connect(self.plugin_update_requested.emit)
                group.add_section(section)

            # Insert before the trailing stretch
            idx = self._container_layout.count() - 1
            self._container_layout.insertWidget(idx, group)
            self._groups.append(group)

    def _build_plugin_section(
        self,
        plugin: PluginInfo,
        directories: list[ManifestDirectory],
        auto_update_map: dict[str, bool],
        *,
        parent: QWidget | None = None,
    ) -> PluginSection:
        """Create a :class:`PluginSection` for a single plugin."""
        found = plugin.installed
        version = str(plugin.tool_version) if plugin.tool_version is not None else 'Installed' if found else 'Not found'
        show_controls = plugin.kind in _UPDATABLE_KINDS
        auto_update = auto_update_map.get(plugin.name, True)

        packages = self._gather_packages(plugin.name, directories) if show_controls else []

        return PluginSection(
            PluginSectionData(
                name=plugin.name,
                version=version,
                packages=packages,
                auto_update=auto_update,
                show_controls=show_controls,
                found=found,
            ),
            parent=parent,
        )

    def _gather_packages(
        self,
        plugin_name: str,
        directories: list[ManifestDirectory],
    ) -> list[tuple[str, str]]:
        """Collect packages managed by *plugin_name* across cached projects."""
        packages: list[tuple[str, str]] = []
        for directory in directories:
            try:
                pkgs = self._porringer.plugin.list_packages(
                    plugin_name,
                    Path(directory.path),
                )
                for pkg in pkgs:
                    packages.append(
                        (str(pkg.name), directory.name or str(directory.path)),
                    )
            except Exception:
                logger.debug(
                    'Could not list packages for %s in %s',
                    plugin_name,
                    directory.path,
                    exc_info=True,
                )
        return packages

    # --- Callbacks ---

    def _on_auto_update_toggled(self, plugin_name: str, enabled: bool) -> None:
        """Persist the auto-update toggle change to config."""
        mapping = self._config.plugin_auto_update
        if mapping is None:
            mapping = {}
            self._config.plugin_auto_update = mapping

        if enabled:
            mapping.pop(plugin_name, None)
        else:
            mapping[plugin_name] = False

        # Clean up the dict if all plugins are enabled
        if not mapping:
            self._config.plugin_auto_update = None

        save_config(self._config)
        logger.info('Auto-update for %s set to %s', plugin_name, enabled)


class ProjectsView(QWidget):
    """Widget for managing project directories and previewing their manifests.

    Combines a cached-directory selector (editable ``QComboBox`` with
    Browse) and a :class:`SetupPreviewWidget` for dry-run preview and
    install execution.
    """

    def __init__(self, porringer: API, parent: QWidget | None = None) -> None:
        """Initialize the projects view.

        Args:
            porringer: The porringer API instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._runner: QThread | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*COMPACT_MARGINS)

        # --- Project directory selector ---
        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 8)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setToolTip('Select a cached project directory or enter a new path')
        self._combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(40)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        selector_row.addWidget(self._combo, 1)

        self._browse_btn = QPushButton('Browse…')
        self._browse_btn.clicked.connect(self._on_browse)
        selector_row.addWidget(self._browse_btn)

        self._remove_btn = QPushButton('Remove')
        self._remove_btn.setToolTip('Remove the selected directory from the cache')
        self._remove_btn.clicked.connect(self._on_remove)
        self._remove_btn.setEnabled(False)
        selector_row.addWidget(self._remove_btn)

        layout.addLayout(selector_row)

        # --- Shared preview widget ---
        self._preview = SetupPreviewWidget(self._porringer, self, show_close=False)
        self._preview.install_finished.connect(self._on_install_finished)
        layout.addWidget(self._preview)

    # --- Public API ---

    def refresh(self) -> None:
        """Refresh the cached directories combo box from porringer cache."""
        self._combo.blockSignals(True)
        current_text = self._combo.currentText()
        self._combo.clear()

        results: list[DirectoryValidationResult] = self._porringer.cache.validate_directories(check_manifest=True)
        for result in results:
            directory = result.directory
            display = str(directory.path)
            tooltip = directory.name or ''

            idx = self._combo.count()
            self._combo.addItem(display)
            self._combo.setItemData(idx, tooltip, Qt.ItemDataRole.ToolTipRole)
            self._combo.setItemData(idx, str(directory.path), Qt.ItemDataRole.UserRole)

            if not result.exists:
                # Grey out entries whose path no longer exists on disk
                self._grey_out_item(idx, tooltip, 'Path not found')
            elif result.has_manifest is False:
                # Dim entries where the path exists but no manifest is found
                self._grey_out_item(idx, tooltip, 'No manifest found')

        # Restore previous selection if it still exists
        idx = self._combo.findText(current_text)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        elif self._combo.count() > 0:
            self._combo.setCurrentIndex(0)

        self._combo.blockSignals(False)
        self._update_remove_btn()

        # Trigger preview for the current selection
        if self._combo.currentText():
            self._load_preview()

    def _grey_out_item(self, idx: int, tooltip: str, reason: str) -> None:
        """Grey out a combo box item and append a reason to its tooltip."""
        model = self._combo.model()
        item = model.item(idx) if hasattr(model, 'item') else None
        if isinstance(item, QStandardItem):
            item.setForeground(self.palette().placeholderText())
            item.setToolTip(f'{tooltip} \u2014 {reason}' if tooltip else reason)

    # --- Event handlers ---

    def _on_selection_changed(self, _index: int) -> None:
        """Handle combo box selection changes."""
        self._update_remove_btn()
        if self._combo.currentText():
            self._load_preview()

    def _on_browse(self) -> None:
        """Open a file picker filtered to recognised manifest filenames."""
        filenames = self._porringer.sync.manifest_filenames()
        filter_str = 'Manifests (' + ' '.join(filenames) + ');;All Files (*)'
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            'Select Manifest File',
            self._combo.currentText() or '',
            filter_str,
        )
        if chosen:
            self._combo.setEditText(chosen)
            self._load_preview()

    def _on_remove(self) -> None:
        """Remove the currently selected directory from the cache."""
        idx = self._combo.currentIndex()
        if idx < 0:
            return

        path_str = self._combo.itemData(idx, Qt.ItemDataRole.UserRole)
        if path_str:
            self._porringer.cache.remove_directory(Path(path_str))

        self.refresh()

    def _on_install_finished(self, _results: object) -> None:
        """Register a new path in the cache after successful install."""
        current_text = self._combo.currentText().strip()
        if not current_text:
            return

        # Only register if the path isn't already in the combo's cached items
        idx = self._combo.findText(current_text)
        item_data = self._combo.itemData(idx, Qt.ItemDataRole.UserRole) if idx >= 0 else None
        if item_data is None:
            try:
                self._porringer.cache.add_directory(Path(current_text))
                logger.info('Registered new project directory: %s', current_text)
                self.refresh()
            except ValueError:
                logger.debug('Directory already cached or invalid: %s', current_text)

    # --- Preview loading ---

    def _load_preview(self) -> None:
        """Run a dry-run preview for the currently selected path."""
        path_text = self._combo.currentText().strip()
        if not path_text:
            return

        selected_path = Path(path_text)

        self._preview.reset()

        if not selected_path.exists():
            self._preview.show_not_found(f'Path not found: {selected_path}')
            return

        if not self._porringer.sync.has_manifest(selected_path):
            self._preview.show_not_found(f'No manifest found at: {selected_path}')
            return

        # Defer project directory assignment until the preview result
        # provides root_directory — handles both file and directory inputs.
        preview_worker = PreviewWorker(
            self._porringer,
            str(selected_path),
            project_directory=selected_path if selected_path.is_dir() else None,
        )
        preview_worker.preview_ready.connect(self._on_preview_ready)
        preview_worker.action_checked.connect(self._preview.on_action_checked)
        preview_worker.finished.connect(self._preview.on_preview_finished)
        preview_worker.error.connect(self._on_preview_error)

        self._runner = preview_worker
        self._runner.start()

    def _on_preview_ready(self, preview: SetupResults, manifest_path: str, temp_dir_path: str) -> None:
        """Set the project directory from the manifest result and forward."""
        if preview.root_directory:
            self._preview.set_project_directory(preview.root_directory)
        self._preview.on_preview_ready(preview, manifest_path, temp_dir_path)

    def _on_preview_error(self, message: str) -> None:
        """Handle preview errors inline instead of showing a modal dialog."""
        logger.warning('Preview error: %s', message)
        self._preview.show_not_found(message)

    def _update_remove_btn(self) -> None:
        """Enable the Remove button only for cached (non-freeform) entries."""
        idx = self._combo.currentIndex()
        has_data = idx >= 0 and self._combo.itemData(idx, Qt.ItemDataRole.UserRole) is not None
        self._remove_btn.setEnabled(has_data)


class MainWindow(QMainWindow):
    """Main window for the application."""

    _tabs: QTabWidget | None = None
    _plugins_view: PluginsView | None = None
    _projects_view: ProjectsView | None = None

    def __init__(
        self,
        porringer: API | None = None,
        config: GlobalConfiguration | None = None,
    ) -> None:
        """Initialize the main window.

        Args:
            porringer: Optional porringer API instance for manifest display.
            config: Resolved global configuration for plugin auto-update state.
        """
        super().__init__()
        self._porringer = porringer
        self._config = config or GlobalConfiguration()
        self.setWindowTitle('Synodic Client')
        self.setMinimumSize(*MAIN_WINDOW_MIN_SIZE)
        self.setWindowIcon(app_icon())

    @property
    def porringer(self) -> API | None:
        """Return the porringer API instance, if available."""
        return self._porringer

    @property
    def plugins_view(self) -> PluginsView | None:
        """Return the plugins view, if initialised."""
        return self._plugins_view

    def show(self) -> None:
        """Show the window, initializing UI lazily on first show."""
        if self._tabs is None and self._porringer is not None:
            self._tabs = QTabWidget(self)

            self._projects_view = ProjectsView(self._porringer, self)
            self._tabs.addTab(self._projects_view, 'Projects')

            self._plugins_view = PluginsView(self._porringer, self._config, self)
            self._tabs.addTab(self._plugins_view, 'Plugins')

            self.setCentralWidget(self._tabs)

        # Refresh both views
        if self._plugins_view is not None:
            self._plugins_view.refresh()
        if self._projects_view is not None:
            self._projects_view.refresh()

        super().show()


class Screen:
    """Screen class for the Synodic Client application."""

    _window: MainWindow | None = None

    def __init__(
        self,
        porringer: API | None = None,
        config: GlobalConfiguration | None = None,
    ) -> None:
        """Initialize the screen.

        Args:
            porringer: Optional porringer API instance.
            config: Resolved global configuration.
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
