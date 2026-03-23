"""WSL package management view.

Shows packages installed in each WSL2 distro, using the same plugin row
widgets as :class:`~synodic_client.application.screen.screen.ToolsView`
but scoped per-distro.

Only rendered when :func:`porringer.plugin.wsl.utility.is_wsl_host`
returns ``True`` (Windows + ``wsl`` on PATH).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.screen.plugin_row import (
    PluginProviderHeader,
    PluginRow,
    RowPhase,
)
from synodic_client.application.screen.schema import PackageEntry, PluginRowData
from synodic_client.application.screen.spinner import LoadingIndicator
from synodic_client.application.theme import (
    COMPACT_MARGINS,
    PLUGIN_KIND_HEADER_STYLE,
    PLUGIN_SECTION_SPACING,
)

if TYPE_CHECKING:
    from porringer.api import API
    from porringer.schema import PluginInfo

    from synodic_client.application.config_store import ConfigStore
    from synodic_client.application.data import DataCoordinator
    from synodic_client.application.package_state import PackageStateStore

logger = logging.getLogger(__name__)

#: Plugin kinds queried when listing packages inside a WSL distro.
_WSL_QUERYABLE_KINDS = frozenset({PluginKind.TOOL, PluginKind.PACKAGE})


# ---------------------------------------------------------------------------
# _WslDistroHeader — section divider for one WSL distro
# ---------------------------------------------------------------------------


class _WslDistroHeader(QLabel):
    """Uppercase section divider labelling a WSL2 distro group.

    Styled like :class:`PluginKindHeader` but with a purple tint to
    visually distinguish WSL sections from native host sections.
    """

    def __init__(self, distro_name: str, parent: QWidget | None = None) -> None:
        super().__init__(distro_name.upper(), parent)
        self.setObjectName('pluginKindHeader')
        self.setStyleSheet(PLUGIN_KIND_HEADER_STYLE)


# ---------------------------------------------------------------------------
# WslView
# ---------------------------------------------------------------------------


class WslView(QWidget):
    """Tool management view for packages installed inside WSL2 distros.

    Mirrors the structure of ``ToolsView`` — distro section headers,
    per-plugin :class:`PluginProviderHeader` rows, and per-package
    :class:`PluginRow` widgets — but queries are routed through the
    ``distro=`` parameter on :meth:`porringer.PackageCommands.list`,
    :meth:`~porringer.PackageCommands.upgrade`, and
    :meth:`~porringer.PackageCommands.uninstall`.

    Each distro's packages are loaded in parallel.  Packages are
    displayed globally (WSL environments don't have per-project venvs
    in the same sense as the host).
    """

    package_update_requested = Signal(str, str, str)
    """Emitted with ``(distro, plugin_name, package_name)`` when update is clicked."""

    package_remove_requested = Signal(str, str, str)
    """Emitted with ``(distro, plugin_name, package_name)`` when remove is clicked."""

    def __init__(
        self,
        porringer: API,
        store: ConfigStore,
        parent: QWidget | None = None,
        *,
        coordinator: DataCoordinator | None = None,
        package_store: PackageStateStore | None = None,
    ) -> None:
        """Initialize the WSL view.

        Args:
            porringer: The porringer API instance.
            store: The centralised :class:`ConfigStore`.
            parent: Optional parent widget.
            coordinator: Shared data coordinator for reusing discovery results.
            package_store: Shared package update state registry (currently unused
                by WslView but accepted for API consistency with ToolsView).
        """
        super().__init__(parent)
        self._porringer = porringer
        self._store = store
        self._coordinator = coordinator
        self._section_widgets: list[QWidget] = []
        self._plugin_info_map: dict[str, PluginInfo] = {}
        self._refresh_in_progress = False
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Build the view layout: toolbar, scroll area, loading indicator."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*COMPACT_MARGINS)

        outer.addLayout(self._build_toolbar())

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

        self._loading_indicator = LoadingIndicator('Loading WSL packages\u2026')
        outer.addWidget(self._loading_indicator)

    def _build_toolbar(self) -> QHBoxLayout:
        """Build the toolbar with a refresh button."""
        toolbar = QHBoxLayout()
        toolbar.addStretch()

        self._refresh_btn = QPushButton('Refresh')
        self._refresh_btn.setFlat(True)
        self._refresh_btn.setToolTip('Re-scan WSL packages')
        self._refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self._refresh_btn)

        return toolbar

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Schedule an asynchronous rebuild of the WSL package list."""
        if self._refresh_in_progress:
            return
        asyncio.create_task(self._async_refresh())

    # ------------------------------------------------------------------
    # Async refresh pipeline
    # ------------------------------------------------------------------

    async def _async_refresh(self) -> None:
        """Rebuild the WSL package tree from porringer data."""
        self._refresh_in_progress = True
        self._scroll.hide()
        self._loading_indicator.start()
        self._refresh_btn.setEnabled(False)

        try:
            data = await self._gather_wsl_data()
            self._build_widget_tree(data)
        except Exception:
            logger.exception('Failed to refresh WSL packages')
        finally:
            self._loading_indicator.stop()
            self._scroll.show()
            self._refresh_btn.setEnabled(True)
            self._refresh_in_progress = False

    async def _gather_wsl_data(self) -> dict[str, dict[str, list[PackageEntry]]]:
        """Fetch packages for every available WSL2 distro.

        For each distro, all TOOL- and PACKAGE-kind plugins are queried
        in parallel using ``porringer.package.list(..., distro=distro)``.

        Returns:
            ``{distro_name: {plugin_name: [PackageEntry, ...]}}`` for
            distros that have at least one non-empty plugin result.
        """
        from porringer.plugin.wsl.utility import available_distros

        discovered = self._coordinator.discovered_plugins if self._coordinator else None

        if self._coordinator is not None:
            snapshot = await self._coordinator.refresh()
            plugins = snapshot.plugins
        else:
            plugins = await self._porringer.plugin.list()

        # Update the plugin-info lookup for PluginProviderHeader construction.
        self._plugin_info_map = {p.name: p for p in plugins}

        queryable = [p for p in plugins if p.kind in _WSL_QUERYABLE_KINDS and p.installed]

        loop = asyncio.get_running_loop()
        distros: list[str] = await loop.run_in_executor(None, available_distros)

        result: dict[str, dict[str, list[PackageEntry]]] = {}

        async def _fetch_distro(distro: str) -> None:
            distro_pkgs: dict[str, list[PackageEntry]] = {}

            async def _fetch_plugin(plugin: PluginInfo) -> None:
                try:
                    pkgs = await self._porringer.package.list(
                        plugin.name,
                        plugins=discovered,
                        distro=distro,
                    )
                    if pkgs:
                        distro_pkgs[plugin.name] = [
                            PackageEntry(
                                name=str(pkg.name),
                                version=str(pkg.version) if pkg.version else '',
                                host_tool=pkg.relation.host if pkg.relation else '',
                            )
                            for pkg in pkgs
                        ]
                except Exception:
                    logger.debug(
                        'Could not list packages for %s in distro %s',
                        plugin.name,
                        distro,
                        exc_info=True,
                    )

            async with asyncio.TaskGroup() as tg:
                for plugin in queryable:
                    tg.create_task(_fetch_plugin(plugin))

            if distro_pkgs:
                result[distro] = distro_pkgs

        async with asyncio.TaskGroup() as tg:
            for distro in distros:
                tg.create_task(_fetch_distro(distro))

        return result

    # ------------------------------------------------------------------
    # Widget tree construction
    # ------------------------------------------------------------------

    def _build_widget_tree(self, data: dict[str, dict[str, list[PackageEntry]]]) -> None:
        """Clear and rebuild section widgets from *data*."""
        self._clear_section_widgets()

        if not data:
            empty = QLabel('No WSL packages found.')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet('color: grey; padding: 20px;')
            self._insert_section_widget(empty)
            return

        for distro_name in sorted(data):
            header = _WslDistroHeader(distro_name, parent=self._container)
            self._insert_section_widget(header)

            for plugin_name, packages in sorted(data[distro_name].items()):
                plugin_info = self._plugin_info_map.get(plugin_name)
                if plugin_info is not None:
                    provider = PluginProviderHeader(
                        plugin_info,
                        show_controls=False,
                        parent=self._container,
                    )
                    self._insert_section_widget(provider)

                for entry in packages:
                    row = PluginRow(
                        PluginRowData(
                            name=entry.name,
                            version=entry.version,
                            plugin_name=plugin_name,
                            show_toggle=False,
                            is_global=True,
                            host_tool=entry.host_tool,
                        ),
                        parent=self._container,
                    )
                    # Capture distro_name in the lambda so the handler
                    # knows which distro to route the operation to.
                    row.update_requested.connect(
                        lambda pn, pkg, d=distro_name: asyncio.create_task(
                            self._update_package(d, pn, pkg),
                        ),
                    )
                    row.remove_requested.connect(
                        lambda pn, pkg, d=distro_name: asyncio.create_task(
                            self._remove_package(d, pn, pkg),
                        ),
                    )
                    self._insert_section_widget(row)

    def _insert_section_widget(self, widget: QWidget) -> None:
        """Append *widget* to the container layout above the trailing stretch."""
        idx = self._container_layout.count() - 1
        self._container_layout.insertWidget(idx, widget)
        self._section_widgets.append(widget)

    def _clear_section_widgets(self) -> None:
        """Remove and delete all current section widgets."""
        for widget in self._section_widgets:
            self._container_layout.removeWidget(widget)
            widget.deleteLater()
        self._section_widgets.clear()

    # ------------------------------------------------------------------
    # Package operations
    # ------------------------------------------------------------------

    async def _update_package(self, distro: str, plugin_name: str, package_name: str) -> None:
        """Upgrade *package_name* inside *distro* via *plugin_name*.

        Transitions the matching :class:`PluginRow` to the ``UPDATING``
        phase, executes the upgrade, then returns it to ``IDLE`` or
        shows an inline error on failure.
        """
        from porringer.core.schema import PackageRef

        discovered = self._coordinator.discovered_plugins if self._coordinator else None
        row = self._find_row(plugin_name, package_name)
        if row is not None:
            row.set_phase(RowPhase.UPDATING)

        try:
            ref = PackageRef(name=package_name)
            action_result = await self._porringer.package.upgrade(
                plugin_name,
                ref,
                plugins=discovered,
                distro=distro,
            )
            if not action_result.success and not action_result.skipped:
                msg = action_result.message or 'Update failed'
                logger.warning('WSL package update failed: %s/%s in %s: %s', plugin_name, package_name, distro, msg)
                if row is not None:
                    row.set_error(msg)
            else:
                if row is not None:
                    row.set_phase(RowPhase.IDLE)
                self.package_update_requested.emit(distro, plugin_name, package_name)
        except Exception:
            logger.exception('WSL update error: %s/%s in %s', plugin_name, package_name, distro)
            if row is not None:
                row.set_error('Update error — see log')

    async def _remove_package(self, distro: str, plugin_name: str, package_name: str) -> None:
        """Uninstall *package_name* from *distro* via *plugin_name*.

        On success, triggers a refresh so the removed package disappears
        from the list.  On failure, shows an inline error on the row.
        """
        from porringer.core.schema import PackageRef

        discovered = self._coordinator.discovered_plugins if self._coordinator else None
        row = self._find_row(plugin_name, package_name)

        try:
            ref = PackageRef(name=package_name)
            action_result = await self._porringer.package.uninstall(
                plugin_name,
                ref,
                plugins=discovered,
                distro=distro,
            )
            if action_result.success or action_result.skipped:
                self.package_remove_requested.emit(distro, plugin_name, package_name)
                # Refresh to remove the row from the list.
                self.refresh()
            else:
                msg = action_result.message or 'Removal failed'
                logger.warning('WSL package removal failed: %s/%s in %s: %s', plugin_name, package_name, distro, msg)
                if row is not None:
                    row.set_error(msg)
        except Exception:
            logger.exception('WSL removal error: %s/%s in %s', plugin_name, package_name, distro)
            if row is not None:
                row.set_error('Removal error — see log')

    def _find_row(self, plugin_name: str, package_name: str) -> PluginRow | None:
        """Return the first :class:`PluginRow` matching *plugin_name* and *package_name*."""
        for widget in self._section_widgets:
            if (
                isinstance(widget, PluginRow)
                and widget._plugin_name == plugin_name
                and widget._package_name == package_name
            ):
                return widget
        return None
