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
from typing import TYPE_CHECKING

from porringer.api import API
from porringer.core.schema import PackageRef
from porringer.schema.execution import SetupActionResult
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSystemTrayIcon

from synodic_client.application.schema import ToolUpdateResult, UpdateTarget
from synodic_client.application.screen.screen import MainWindow, ToolsView
from synodic_client.application.workers import (
    run_runtime_package_updates,
    run_tool_updates,
)
from synodic_client.resolution import (
    resolve_auto_update_scope,
    resolve_update_config,
)

if TYPE_CHECKING:
    from synodic_client.application.config_store import ConfigStore

logger = logging.getLogger(__name__)


def _parse_plugin_key(name: str) -> tuple[str, str | None]:
    """Split a composite ``'plugin:tag'`` key into ``(bare_name, tag)``.

    Returns ``(name, None)`` when there is no tag component.
    """
    if ':' in name:
        bare, tag = name.split(':', 1)
        return bare, tag
    return name, None


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
        tools_view.plugin_update_requested.connect(self.on_single_plugin_update)
        tools_view.package_update_requested.connect(self.on_single_package_update)
        tools_view.package_remove_requested.connect(self.on_single_package_remove)

    # -- ToolsView error helpers --

    def _fail_plugin_update(self, plugin_name: str, error: str) -> None:
        """Reset plugin updating state and show an inline error."""
        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_plugin_updating(plugin_name, False)
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
        self._tool_task = asyncio.create_task(self._do_tool_update(porringer))

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

        bare_plugin, runtime_tag = _parse_plugin_key(plugin_name)
        if runtime_tag is not None:
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
        config = self._store.config
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
            self._on_tool_update_finished(result, UpdateTarget(plugin=signal_key))
        except asyncio.CancelledError:
            logger.debug('Runtime plugin update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Runtime tool update failed')
            self._fail_plugin_update(signal_key, f'Update failed: {exc}')

    async def _async_single_plugin_update(self, porringer: API, plugin_name: str) -> None:
        """Run a single-plugin tool update and route results."""
        config = self._store.config
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
            self._on_tool_update_finished(result, UpdateTarget(plugin=plugin_name))
        except asyncio.CancelledError:
            logger.debug('Single plugin update cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Tool update failed')
            self._fail_plugin_update(plugin_name, f'Update failed: {exc}')

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

        target = UpdateTarget(plugin=plugin_name, package=package_name)
        bare_plugin, runtime_tag = _parse_plugin_key(plugin_name)
        if runtime_tag is not None:
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
                self._on_tool_update_finished(result, target)
            except asyncio.CancelledError:
                logger.debug('Runtime package update cancelled (shutdown)')
                raise
            except Exception as exc:
                logger.exception('Runtime package update failed')
                self._fail_package_update(plugin_name, package_name, f'Update failed: {exc}')
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
        result: ToolUpdateResult,
        target: UpdateTarget | None = None,
    ) -> None:
        """Handle tool update completion.

        Args:
            result: Summary of the update run.
            target: Which plugin/package was updated.  ``None`` for
                periodic (automatic) updates.
        """
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
            tools_view._updates_checked = False
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

        bare_plugin, runtime_tag = _parse_plugin_key(plugin_name)

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
            self._fail_package_update(
                plugin_name,
                package_name,
                f'Failed to remove {package_name}: {exc}',
                removing=True,
            )

    def _on_package_remove_finished(
        self,
        result: SetupActionResult,
        plugin_name: str,
        package_name: str,
    ) -> None:
        """Handle package removal completion."""
        if not result.success or result.skipped:
            detail = result.message or 'Unknown error'
            logger.warning('Package removal failed for %s/%s: %s', plugin_name, package_name, detail)
            self._fail_package_update(
                plugin_name,
                package_name,
                f'Could not remove {package_name}: {detail}',
                removing=True,
            )
            return

        logger.info('Package removal completed for %s/%s', plugin_name, package_name)

        tools_view = self._window.tools_view
        if tools_view is not None:
            tools_view.set_package_removing(plugin_name, package_name, False)
            tools_view._updates_checked = False
            tools_view.refresh()
