"""Tool update orchestration extracted from TrayScreen.

:class:`ToolUpdateOrchestrator` owns the background tool update
lifecycle — periodic polling, single-plugin / single-package updates,
and package removal — delegating actual work to the operations layer
(``synodic_client.operations.tool``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from porringer.api import API
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from synodic_client.application.screen.schema import UpdateTarget
from synodic_client.application.screen.screen import MainWindow, ToolsView
from synodic_client.operations.schema import UpdateResult
from synodic_client.operations.tool import (
    log_update_result,
    parse_plugin_key,
    remove_package,
    resolve_auto_update_scope,
    update_all_tools,
    update_tool,
)
from synodic_client.resolution import resolve_update_config

if TYPE_CHECKING:
    from synodic_client.application.config_store import ConfigStore

logger = logging.getLogger(__name__)


class ToolUpdateOrchestrator:
    """Background tool update lifecycle manager.

    Handles periodic tool-update polling, per-plugin and per-package
    update requests, and package removal.  All async work is scheduled
    on the qasync event loop.

    Args:
        window: The main application window (provides porringer / coordinator).
        store: The centralised :class:`ConfigStore`.
        tray: System tray icon for displaying notification messages.
    """

    def __init__(
        self,
        window: MainWindow,
        store: ConfigStore,
        tray: QSystemTrayIcon,
        is_user_active: Callable[[], bool] | None = None,
    ) -> None:
        """Set up the controller.

        Args:
            window: The main application window.
            store: The centralised :class:`ConfigStore`.
            tray: System tray icon for notification messages.
            is_user_active: Predicate returning ``True`` when the user
                has a visible window.  Periodic tool updates are
                deferred while active.
        """
        self._window = window
        self._store = store
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

    def _set_task(self, coro: Coroutine[Any, Any, None]) -> None:
        """Cancel any in-flight task and start *coro* as the active task."""
        if self._tool_task is not None and not self._tool_task.done():
            self._tool_task.cancel()
        self._tool_task = asyncio.create_task(coro)

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
        config = resolve_update_config(self._store.config)
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
        tools_view.plugin_check_requested.connect(self.on_single_plugin_update)
        tools_view.plugin_update_requested.connect(self.on_single_plugin_update)
        tools_view.package_update_requested.connect(self.on_single_package_update)
        tools_view.package_remove_requested.connect(self.on_single_package_remove)

    # -- Per-package progress callbacks --

    def _make_package_starting_cb(self, signal_key: str) -> Callable[[str], None]:
        """Return a callback that transitions a package row to *Updating*."""

        def _on_starting(package_name: str) -> None:
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_package_active(signal_key, package_name)

        return _on_starting

    def _make_package_completed_cb(
        self,
        signal_key: str,
    ) -> Callable[[str, bool, bool], None]:
        """Return a callback that clears a package row's updating state."""

        def _on_completed(package_name: str, _success: bool, _skipped: bool) -> None:
            tools_view = self._window.tools_view
            if tools_view is not None:
                tools_view.set_package_updating(signal_key, package_name, False)

        return _on_completed

    # -- ToolsView error helpers --

    def _fail_plugin_update(self, plugin_name: str, error: str) -> None:
        """Reset plugin updating state and show an inline error."""
        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_plugin_updating(plugin_name, False)
            tools_view.clear_plugin_row_states(plugin_name)
            tools_view.set_plugin_error(plugin_name, error)

    def _fail_package_update(
        self,
        plugin_name: str,
        package_name: str,
        error: str,
        *,
        removing: bool = False,
    ) -> None:
        """Reset package updating/removing state and show an inline error."""
        tools_view = self._window.tools_view
        if tools_view is not None:
            if removing:
                tools_view.set_package_removing(plugin_name, package_name, False)
            else:
                tools_view.set_package_updating(plugin_name, package_name, False)
            tools_view.set_package_error(plugin_name, package_name, error)

    # -- Full tool update --

    def on_tool_update(self) -> None:
        """Trigger a background re-sync of manifest-declared tools."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Tool update skipped: porringer not available')
            return

        logger.info('Starting periodic tool update check')
        self._set_task(self._do_tool_update(porringer))

    async def _do_tool_update(self, porringer: API) -> None:
        """Resolve enabled plugins off-thread, then run the tool update."""
        config = self._store.config
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
            config.plugin_auto_update,
            all_names,
        )

        try:
            result = await update_all_tools(
                porringer,
                plugins=enabled_plugins,
                include_packages=include_packages,
                discovered=discovered,
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
            pending = tools_view.get_plugin_update_packages(plugin_name)
            if pending:
                tools_view.set_packages_pending(plugin_name, pending)

        bare_plugin, runtime_tag = parse_plugin_key(plugin_name)
        include_packages = self._resolve_include_packages(plugin_name, bare_plugin, runtime_tag)
        self._set_task(
            self._async_plugin_update(porringer, plugin_name, bare_plugin, runtime_tag, include_packages),
        )

    def _resolve_include_packages(
        self,
        signal_key: str,
        bare_plugin: str,
        runtime_tag: str | None,
    ) -> set[str] | None:
        """Derive the include-set of package names for a plugin update.

        Only runtime-scoped updates consult the per-package auto-update
        config; manifest-scoped updates include everything.
        """
        if runtime_tag is None:
            return None
        mapping = self._store.config.plugin_auto_update or {}
        pkg_entry = mapping.get(signal_key) or mapping.get(bare_plugin)
        if isinstance(pkg_entry, dict):
            enabled_pkgs = {name for name, enabled in pkg_entry.items() if enabled}
            if enabled_pkgs:
                return enabled_pkgs
        return None

    async def _async_plugin_update(
        self,
        porringer: API,
        signal_key: str,
        plugin_name: str,
        runtime_tag: str | None,
        include_packages: set[str] | None,
    ) -> None:
        """Run a plugin update through the shared operations layer."""
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None

        try:
            result = await update_tool(
                porringer,
                plugin_name,
                runtime_tag=runtime_tag,
                include_packages=include_packages,
                discovered=discovered,
                on_package_starting=self._make_package_starting_cb(signal_key),
                on_package_completed=self._make_package_completed_cb(signal_key),
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_tool_update_finished(result, UpdateTarget(plugin=signal_key))
        except asyncio.CancelledError:
            logger.debug('Plugin update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Tool update failed')
            self._fail_plugin_update(signal_key, f'Update failed: {exc}')

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
        self._set_task(
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
        ``update_tool(runtime_tag=...)``.
        """
        coordinator = self._window.coordinator
        discovered = coordinator.discovered_plugins if coordinator is not None else None

        target = UpdateTarget(plugin=plugin_name, package=package_name)
        bare_plugin, runtime_tag = parse_plugin_key(plugin_name)

        try:
            result = await update_tool(
                porringer,
                bare_plugin,
                package_name,
                runtime_tag=runtime_tag,
                discovered=discovered,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_tool_update_finished(result, target)
        except asyncio.CancelledError:
            logger.debug('Package update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Package update failed')
            self._fail_package_update(plugin_name, package_name, f'Update failed: {exc}')

    # -- Shared completion handler --

    def _on_tool_update_finished(
        self,
        result: UpdateResult,
        target: UpdateTarget | None = None,
    ) -> None:
        """Handle tool update completion.

        Args:
            result: Summary of the update run.
            target: Which plugin/package was updated.  ``None`` for
                periodic (automatic) updates.
        """
        # Log summary + per-package version transitions (shared with CLI)
        log_update_result(result)

        # Persist timestamps for updated packages
        if result.updated_packages:
            now = datetime.now(UTC).isoformat()
            existing = dict(self._store.config.last_tool_updates or {})
            plugin_name = target.plugin if target else ''
            for pkg_name in result.updated_packages:
                key = f'{plugin_name}/{pkg_name}' if plugin_name else pkg_name
                existing[key] = now
            self._store.update(last_tool_updates=existing)

        # Clear updating state and refresh the tools view.  When the
        # window is hidden we skip the refresh() cycle because
        # MainWindow.show() already triggers a full refresh the next
        # time the user opens the window.  Manual updates (target is
        # not None) call show() below which triggers the refresh.
        tools_view = self._window.tools_view
        if tools_view is not None:
            # Clear stale "update available" badges for packages that were just updated
            if result.version_map:
                signal_key = target.plugin if target else result.plugin
                tools_view.record_updates_completed(signal_key, result.version_map)
            # Clear pending / updating spinners left on child rows
            if target is not None and not target.package:
                tools_view.set_plugin_updating(target.plugin, False)
                tools_view.clear_plugin_row_states(target.plugin)
            tools_view.invalidate_update_data()
            if self._window.isVisible() and target is None:
                tools_view.refresh()

        if target is not None:
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
        self._set_task(
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

        bare_plugin, runtime_tag = parse_plugin_key(plugin_name)

        try:
            success = await remove_package(
                porringer,
                bare_plugin,
                package_name,
                runtime_tag=runtime_tag,
                discovered=discovered,
            )
            logger.info(
                'Removal result for %s/%s: success=%s',
                plugin_name,
                package_name,
                success,
            )
            if coordinator is not None:
                coordinator.invalidate()
            self._on_package_remove_finished(success, plugin_name, package_name)
        except asyncio.CancelledError:
            logger.debug('Package removal cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Package removal failed')
            self._fail_package_update(
                plugin_name,
                package_name,
                f'Failed to remove {package_name}: {exc}',
                removing=True,
            )

    def _on_package_remove_finished(
        self,
        success: bool,
        plugin_name: str,
        package_name: str,
    ) -> None:
        """Handle package removal completion."""
        if not success:
            logger.warning('Package removal failed for %s/%s', plugin_name, package_name)
            self._fail_package_update(
                plugin_name,
                package_name,
                f'Could not remove {package_name}',
                removing=True,
            )
            return

        logger.info('Package removal completed for %s/%s', plugin_name, package_name)

        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_package_removing(plugin_name, package_name, False)
            tools_view.invalidate_update_data()
            tools_view.refresh()
