"""Tray screen for the application."""

import asyncio
import logging
from collections.abc import Callable

from porringer.api import API
from porringer.schema.execution import SetupActionResult
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen.screen import MainWindow, ToolsView
from synodic_client.application.screen.settings import SettingsWindow
from synodic_client.application.update_controller import UpdateController
from synodic_client.application.workers import (
    ToolUpdateResult,
    run_package_remove,
    run_tool_updates,
)
from synodic_client.client import Client
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_auto_update_scope,
    resolve_config,
    resolve_update_config,
)

logger = logging.getLogger(__name__)


class TrayScreen:
    """Tray screen for the application."""

    def __init__(
        self,
        app: QApplication,
        client: Client,
        window: MainWindow,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialize the tray icon.

        Args:
            app: The running ``QApplication``.
            client: The Synodic Client service.
            window: The main application window.
            config: Optional pre-resolved configuration.  When ``None``,
                the configuration is resolved from disk on demand.
        """
        self._app = app
        self._client = client
        self._window = window
        self._config = config
        self._tool_task: asyncio.Task[None] | None = None

        self.tray_icon = app_icon()

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(True)

        self._build_menu(app, window)

        # Settings window (created once, shown/hidden on demand)
        self._settings_window = SettingsWindow(self._resolve_config())
        self._settings_window.settings_changed.connect(self._on_settings_changed)

        # MainWindow gear button → open settings
        window.settings_requested.connect(self._show_settings)

        # Update controller — owns the self-update lifecycle & timer
        self._banner = window.update_banner
        self._update_controller = UpdateController(
            app,
            client,
            self._banner,
            self._settings_window,
            config,
        )

        # Periodic tool update checking
        self._tool_update_timer: QTimer | None = None
        self._restart_tool_update_timer()

        # Connect ToolsView signals — deferred because ToolsView is created lazily
        window.tools_view_created.connect(self._connect_tools_view)

    def _build_menu(self, app: QApplication, window: MainWindow) -> None:
        """Build the tray context menu."""
        self.menu = QMenu()

        self.open_action = QAction('Open', self.menu)
        self.menu.addAction(self.open_action)
        self.open_action.triggered.connect(window.show)

        self.menu.addSeparator()

        self.settings_action = QAction('Settings\u2026', self.menu)
        self.settings_action.triggered.connect(self._show_settings)
        self.menu.addAction(self.settings_action)

        self.menu.addSeparator()

        self.quit_action = QAction('Quit', self.menu)
        self.quit_action.triggered.connect(app.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)

    # -- Deferred ToolsView wiring --

    def _connect_tools_view(self, tools_view: ToolsView) -> None:
        """Wire ToolsView signals once the view is lazily created."""
        tools_view.update_all_requested.connect(self._on_tool_update)
        tools_view.plugin_update_requested.connect(self._on_single_plugin_update)
        tools_view.package_update_requested.connect(self._on_single_package_update)
        tools_view.package_remove_requested.connect(self._on_single_package_remove)

    # -- Config helpers --

    def _resolve_config(self) -> ResolvedConfig:
        """Return the injected config or resolve from disk."""
        if self._config is not None:
            return self._config
        return resolve_config()

    @staticmethod
    def _restart_timer(
        current: QTimer | None,
        interval_minutes: int,
        slot: Callable[[], None],
        label: str,
    ) -> QTimer | None:
        """Stop *current* and return a new periodic timer, or ``None``.

        Args:
            current: The existing timer to stop (may be ``None``).
            interval_minutes: Interval in minutes.  ``0`` disables.
            slot: The callable to invoke on each tick.
            label: Human-readable name for log messages.

        Returns:
            A running ``QTimer``, or ``None`` when disabled.
        """
        if current is not None:
            current.stop()

        if interval_minutes <= 0:
            logger.info('%s is disabled', label)
            return None

        timer = QTimer()
        timer.setInterval(interval_minutes * 60 * 1000)
        timer.timeout.connect(slot)
        timer.start()
        logger.info('%s enabled (every %d minute(s))', label, interval_minutes)
        return timer

    def _restart_tool_update_timer(self) -> None:
        """Start (or restart) the periodic tool update timer from config."""
        config = resolve_update_config(self._resolve_config())
        self._tool_update_timer = self._restart_timer(
            self._tool_update_timer,
            config.tool_update_interval_minutes,
            self._on_tool_update,
            'Automatic tool updating',
        )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (e.g. double-click)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _show_settings(self) -> None:
        """Show the settings window."""
        self._settings_window.show()

    def _on_settings_changed(self, config: ResolvedConfig) -> None:
        """React to a change made in the settings window."""
        self._config = config
        # Delegate updater reinit + immediate check to the controller
        self._update_controller.on_settings_changed(config)
        # Restart tool-update timer with new config
        self._restart_tool_update_timer()

    # -- Tool update helpers --

    def _on_tool_update(self) -> None:
        """Trigger a background re-sync of manifest-declared tools."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Tool update skipped: porringer not available')
            return

        logger.info('Starting periodic tool update check')
        self._tool_task = asyncio.create_task(self._do_tool_update(porringer))

    async def _do_tool_update(self, porringer: API) -> None:
        """Resolve enabled plugins off-thread, then run the tool update."""
        config = self._resolve_config()
        coordinator = self._window.coordinator

        if coordinator is not None:
            snapshot = await coordinator.refresh()
            all_plugins = snapshot.plugins
            discovered = snapshot.discovered
        else:
            all_plugins = await porringer.plugin.list()
            discovered = None

        all_names = [p.name for p in all_plugins if p.installed]
        enabled_plugins, include_packages = resolve_auto_update_scope(
            config,
            all_names,
        )

        try:
            result = await run_tool_updates(
                porringer,
                plugins=enabled_plugins,
                include_packages=include_packages,
                discovered_plugins=discovered,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_tool_update_finished(result)
        except Exception as exc:
            logger.exception('Tool update failed')
            self._on_tool_update_error(str(exc))

    def _on_single_plugin_update(self, plugin_name: str) -> None:
        """Upgrade a single plugin across all cached projects."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Single plugin update skipped: porringer not available')
            return

        logger.info('Starting update for plugin: %s', plugin_name)
        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_plugin_updating(plugin_name, True)
        self._tool_task = asyncio.create_task(
            self._async_single_plugin_update(porringer, plugin_name),
        )

    async def _async_single_plugin_update(self, porringer: API, plugin_name: str) -> None:
        """Run a single-plugin tool update and route results."""
        config = self._resolve_config()
        mapping = config.plugin_auto_update or {}
        pkg_entry = mapping.get(plugin_name)
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None

        # Resolve per-package filtering for this plugin
        include_packages: set[str] | None = None
        if isinstance(pkg_entry, dict):
            enabled_pkgs = {name for name, enabled in pkg_entry.items() if enabled}
            if enabled_pkgs:
                include_packages = enabled_pkgs

        try:
            result = await run_tool_updates(
                porringer,
                plugins={plugin_name},
                include_packages=include_packages,
                discovered_plugins=discovered,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_tool_update_finished(result, updating_plugin=plugin_name, manual=True)
        except Exception as exc:
            logger.exception('Tool update failed')
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_plugin_updating(plugin_name, False)
                tools_view.set_plugin_error(plugin_name, f'Update failed: {exc}')

    def _on_single_package_update(self, plugin_name: str, package_name: str) -> None:
        """Upgrade a single package managed by *plugin_name*."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Single package update skipped: porringer not available')
            return

        logger.info('Starting update for %s/%s', plugin_name, package_name)
        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_package_updating(plugin_name, package_name, True)
        self._tool_task = asyncio.create_task(
            self._async_single_package_update(porringer, plugin_name, package_name),
        )

    async def _async_single_package_update(
        self,
        porringer: API,
        plugin_name: str,
        package_name: str,
    ) -> None:
        """Run a single-package tool update and route results."""
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None
        try:
            result = await run_tool_updates(
                porringer,
                plugins={plugin_name},
                include_packages={package_name},
                discovered_plugins=discovered,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_tool_update_finished(
                result,
                updating_package=(plugin_name, package_name),
                manual=True,
            )
        except Exception as exc:
            logger.exception('Package update failed')
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_package_updating(plugin_name, package_name, False)
                tools_view.set_package_error(plugin_name, package_name, f'Update failed: {exc}')

    def _on_tool_update_finished(
        self,
        result: ToolUpdateResult,
        *,
        updating_plugin: str | None = None,
        updating_package: tuple[str, str] | None = None,
        manual: bool = False,
    ) -> None:
        """Handle tool update completion."""
        logger.info(
            'Tool update completed: %d manifest(s), %d updated, %d already latest, %d failed',
            result.manifests_processed,
            result.updated,
            result.already_latest,
            result.failed,
        )

        # Clear updating state on widgets
        tools_view = self._window.tools_view
        if tools_view is not None:
            if updating_plugin is not None:
                tools_view.set_plugin_updating(updating_plugin, False)
            if updating_package is not None:
                tools_view.set_package_updating(*updating_package, False)
            # Refresh to pick up version changes and re-detect updates
            tools_view._updates_checked = False
            tools_view.refresh()

        if manual:
            self._window.show()

    def _on_tool_update_error(self, error: str) -> None:
        """Handle tool update error."""
        logger.error('Tool update failed: %s', error)
        self.tray.showMessage(
            'Tool Update Error',
            f'An error occurred during tool update: {error}',
            QSystemTrayIcon.MessageIcon.Warning,
        )

    # -- Package removal --

    def _on_single_package_remove(self, plugin_name: str, package_name: str) -> None:
        """Remove a single global package managed by *plugin_name*."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Package remove skipped: porringer not available')
            return

        logger.info('Starting removal for %s/%s', plugin_name, package_name)
        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_package_removing(plugin_name, package_name, True)
        self._tool_task = asyncio.create_task(
            self._async_single_package_remove(porringer, plugin_name, package_name),
        )

    async def _async_single_package_remove(
        self,
        porringer: API,
        plugin_name: str,
        package_name: str,
    ) -> None:
        """Run a single-package removal and route results."""
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None
        try:
            result = await run_package_remove(
                porringer,
                plugin_name,
                package_name,
                discovered_plugins=discovered,
            )
            logger.info(
                'Removal result for %s/%s: success=%s, skipped=%s, skip_reason=%s, message=%s',
                plugin_name,
                package_name,
                result.success,
                result.skipped,
                result.skip_reason,
                result.message,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_package_remove_finished(result, plugin_name, package_name)
        except Exception as exc:
            logger.exception('Package removal failed')
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_package_removing(plugin_name, package_name, False)
                tools_view.set_package_error(plugin_name, package_name, f'Failed to remove {package_name}: {exc}')

    def _on_package_remove_finished(
        self,
        result: SetupActionResult,
        plugin_name: str,
        package_name: str,
    ) -> None:
        """Handle package removal completion."""
        tools_view = self._window.tools_view

        if not result.success or result.skipped:
            detail = result.message or 'Unknown error'
            logger.warning('Package removal failed for %s/%s: %s', plugin_name, package_name, detail)
            if tools_view is not None:
                tools_view.set_package_removing(plugin_name, package_name, False)
                tools_view.set_package_error(plugin_name, package_name, f'Could not remove {package_name}: {detail}')
            return

        logger.info('Package removal completed for %s/%s', plugin_name, package_name)

        if tools_view is not None:
            tools_view.set_package_removing(plugin_name, package_name, False)
            tools_view._updates_checked = False
            tools_view.refresh()

        self._window.show()
