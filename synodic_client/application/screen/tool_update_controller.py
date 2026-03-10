"""Tool update orchestration extracted from TrayScreen.

:class:`ToolUpdateOrchestrator` owns the background tool update
lifecycle — periodic polling, single-plugin / single-package updates,
and package removal — delegating actual work to
:func:`~synodic_client.application.workers.run_tool_updates` and
:func:`~synodic_client.application.workers.run_package_remove`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from porringer.api import API
from porringer.core.schema import PackageRef
from porringer.schema.execution import SetupActionResult
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from synodic_client.application.schema import ToolUpdateResult
from synodic_client.application.screen.screen import MainWindow, ToolsView
from synodic_client.application.workers import (
    run_runtime_package_updates,
    run_tool_updates,
)
from synodic_client.config import load_user_config
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_auto_update_scope,
    resolve_update_config,
    update_user_config,
)

logger = logging.getLogger(__name__)


class ToolUpdateOrchestrator:
    """Background tool update lifecycle manager.

    Handles periodic tool-update polling, per-plugin and per-package
    update requests, and package removal.  All async work is scheduled
    on the qasync event loop.

    Args:
        window: The main application window (provides porringer / coordinator).
        config_resolver: Callable returning the current resolved config.
        tray: System tray icon for displaying notification messages.
    """

    def __init__(
        self,
        window: MainWindow,
        config_resolver: Callable[[], ResolvedConfig],
        tray: QSystemTrayIcon,
        is_user_active: Callable[[], bool] | None = None,
    ) -> None:
        """Set up the controller.

        Args:
            window: The main application window.
            config_resolver: Callable returning the current resolved config.
            tray: System tray icon for notification messages.
            is_user_active: Predicate returning ``True`` when the user
                has a visible window.  Periodic tool updates are
                deferred while active.
        """
        self._window = window
        self._resolve_config = config_resolver
        self._tray = tray
        self._is_user_active = is_user_active or (lambda: False)
        self._tool_task: asyncio.Task[None] | None = None
        self._tool_update_timer: QTimer | None = None

    def shutdown(self) -> None:
        """Stop timers and cancel in-flight tasks for a clean exit."""
        if self._tool_update_timer is not None:
            self._tool_update_timer.stop()
            self._tool_update_timer = None
        if self._tool_task is not None and not self._tool_task.done():
            self._tool_task.cancel()
            self._tool_task = None
        logger.info('ToolUpdateOrchestrator shut down')

    # -- Timer management --

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

    def restart_tool_update_timer(self) -> None:
        """Start (or restart) the periodic tool update timer from config."""
        config = resolve_update_config(self._resolve_config())
        self._tool_update_timer = self._restart_timer(
            self._tool_update_timer,
            config.tool_update_interval_minutes,
            self._on_periodic_tool_update,
            'Automatic tool updating',
        )

    def _on_periodic_tool_update(self) -> None:
        """Timer callback — deferred when the user has a visible window."""
        if self._is_user_active():
            logger.debug('Periodic tool update deferred — user is active')
            return
        self.on_tool_update()

    # -- ToolsView signal wiring --

    def connect_tools_view(self, tools_view: ToolsView) -> None:
        """Wire ToolsView signals once the view is lazily created."""
        tools_view.update_all_requested.connect(self.on_tool_update)
        tools_view.plugin_update_requested.connect(self.on_single_plugin_update)
        tools_view.package_update_requested.connect(self.on_single_package_update)
        tools_view.package_remove_requested.connect(self.on_single_package_remove)

    # -- Full tool update --

    def on_tool_update(self) -> None:
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
        except asyncio.CancelledError:
            logger.debug('Tool update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Tool update failed')
            self._on_tool_update_error(str(exc))

    # -- Single plugin update --

    def on_single_plugin_update(self, plugin_name: str) -> None:
        """Upgrade a single plugin across all cached projects.

        Composite keys ``"plugin:tag"`` trigger a per-runtime update
        scoped to the given runtime tag.
        """
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Single plugin update skipped: porringer not available')
            return

        logger.info('Starting update for plugin: %s', plugin_name)
        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_plugin_updating(plugin_name, True)

        if ':' in plugin_name:
            bare_plugin, runtime_tag = plugin_name.split(':', 1)
            self._tool_task = asyncio.create_task(
                self._async_runtime_plugin_update(porringer, plugin_name, bare_plugin, runtime_tag),
            )
        else:
            self._tool_task = asyncio.create_task(
                self._async_single_plugin_update(porringer, plugin_name),
            )

    async def _async_runtime_plugin_update(
        self,
        porringer: API,
        signal_key: str,
        plugin_name: str,
        runtime_tag: str,
    ) -> None:
        """Run a runtime-scoped plugin update and route results."""
        config = self._resolve_config()
        mapping = config.plugin_auto_update or {}
        pkg_entry = mapping.get(signal_key) or mapping.get(plugin_name)
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None

        include_packages: set[str] | None = None
        if isinstance(pkg_entry, dict):
            enabled_pkgs = {name for name, enabled in pkg_entry.items() if enabled}
            if enabled_pkgs:
                include_packages = enabled_pkgs

        try:
            result = await run_runtime_package_updates(
                porringer,
                plugin_name,
                runtime_tag,
                include_packages=include_packages,
                discovered_plugins=discovered,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_tool_update_finished(result, updating_plugin=signal_key, manual=True)
        except asyncio.CancelledError:
            logger.debug('Runtime plugin update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Runtime tool update failed')
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_plugin_updating(signal_key, False)
                tools_view.set_plugin_error(signal_key, f'Update failed: {exc}')

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
        except asyncio.CancelledError:
            logger.debug('Single plugin update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Tool update failed')
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_plugin_updating(plugin_name, False)
                tools_view.set_plugin_error(plugin_name, f'Update failed: {exc}')

    # -- Single package update --

    def on_single_package_update(self, plugin_name: str, package_name: str) -> None:
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
        """Run a single-package tool update and route results.

        When *plugin_name* is a composite ``"plugin:tag"`` key the
        upgrade is scoped to that runtime tag via
        ``porringer.package.upgrade(runtime_tag=...)``.
        """
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None

        if ':' in plugin_name:
            bare_plugin, runtime_tag = plugin_name.split(':', 1)
            try:
                result = await run_runtime_package_updates(
                    porringer,
                    bare_plugin,
                    runtime_tag,
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
            except asyncio.CancelledError:
                logger.debug('Runtime package update cancelled (shutdown)')
                raise
            except Exception as exc:
                logger.exception('Runtime package update failed')
                tools_view = self._window.tools_view
                if tools_view is not None:
                    tools_view.set_package_updating(plugin_name, package_name, False)
                    tools_view.set_package_error(plugin_name, package_name, f'Update failed: {exc}')
            return

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
        except asyncio.CancelledError:
            logger.debug('Package update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Package update failed')
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_package_updating(plugin_name, package_name, False)
                tools_view.set_package_error(plugin_name, package_name, f'Update failed: {exc}')

    # -- Shared completion handler --

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

        # Persist timestamps for updated packages
        if result.updated_packages:
            now = datetime.now(UTC).isoformat()
            existing = dict(load_user_config().last_tool_updates or {})
            plugin_name = updating_plugin or (updating_package[0] if updating_package else '')
            for pkg_name in result.updated_packages:
                key = f'{plugin_name}/{pkg_name}' if plugin_name else pkg_name
                existing[key] = now
            resolved = update_user_config(last_tool_updates=existing)
            # Refresh the config on the tools view so the next rebuild
            # picks up the updated timestamps instead of stale data.
            tools_view_ref = self._window.tools_view
            if tools_view_ref is not None:
                tools_view_ref._config = resolved

        # Clear updating state on widgets
        tools_view = self._window.tools_view
        logger.info(
            '[DIAG] _on_tool_update_finished: manual=%s, tools_view_exists=%s, window_visible=%s',
            manual,
            tools_view is not None,
            self._window.isVisible(),
        )
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
        self._tray.showMessage(
            'Tool Update Error',
            f'An error occurred during tool update: {error}',
            QSystemTrayIcon.MessageIcon.Warning,
        )

    # -- Package removal --

    def on_single_package_remove(self, plugin_name: str, package_name: str) -> None:
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

        bare_plugin = plugin_name
        runtime_tag: str | None = None
        if ':' in plugin_name:
            bare_plugin, runtime_tag = plugin_name.split(':', 1)

        try:
            package_ref = PackageRef(name=package_name)
            result = await porringer.package.uninstall(
                bare_plugin,
                package_ref,
                runtime_tag=runtime_tag,
                plugins=discovered,
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
        except asyncio.CancelledError:
            logger.debug('Package removal cancelled (shutdown)')
            raise
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
