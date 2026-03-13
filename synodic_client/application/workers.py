"""Async background workers for the Synodic Client application.

Each coroutine runs on the caller's event loop (typically the qasync
main-thread loop) and communicates results via return values or
callbacks.  Blocking calls are wrapped in ``loop.run_in_executor``
to avoid stalling the GUI.
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from porringer.api import API
from porringer.backend.command.core.discovery import DiscoveredPlugins
from porringer.core.schema import PackageRef
from porringer.schema import ActionCompletedEvent, SetupParameters, SkipReason, SyncStrategy
from porringer.schema.execution import SetupActionResult

from synodic_client.application.schema import ToolUpdateResult
from synodic_client.client import Client
from synodic_client.schema import UpdateInfo

logger = logging.getLogger(__name__)


async def check_for_update(client: Client) -> UpdateInfo | None:
    """Check for application updates off the main thread.

    Args:
        client: The Synodic Client service.

    Returns:
        An ``UpdateInfo`` result, or ``None`` when no updater is initialised.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, client.check_for_update)
    except asyncio.CancelledError:
        logger.debug('check_for_update cancelled')
        raise


async def download_update(
    client: Client,
    on_progress: Callable[[int], None] | None = None,
) -> bool:
    """Download an application update off the main thread.

    Args:
        client: The Synodic Client service.
        on_progress: Optional callback for download progress (0-100).
            Invoked on the event loop thread via
            ``call_soon_threadsafe``.

    Returns:
        ``True`` if the download succeeded.
    """
    loop = asyncio.get_running_loop()

    def _run() -> bool:
        def progress_callback(percentage: int) -> None:
            if on_progress is not None:
                loop.call_soon_threadsafe(on_progress, percentage)

        return client.download_update(progress_callback)

    try:
        return await loop.run_in_executor(None, _run)
    except asyncio.CancelledError:
        logger.debug('download_update cancelled')
        raise


async def run_tool_updates(
    porringer: API,
    plugins: set[str] | None = None,
    include_packages: set[str] | None = None,
    *,
    discovered_plugins: DiscoveredPlugins | None = None,
) -> ToolUpdateResult:
    """Re-sync all cached project manifests.

    Args:
        porringer: The porringer API instance.
        plugins: Optional include-set of plugin names.  When set, only
            actions handled by these plugins are executed.  ``None``
            means all plugins.
        include_packages: Optional include-set of package names.  When
            set, only actions whose package name is in this set are
            executed.  ``None`` means all packages.
        discovered_plugins: Pre-discovered plugins to pass through to
            porringer, avoiding redundant discovery on each
            ``execute_stream`` call.

    Returns:
        A :class:`ToolUpdateResult` summarising the run.
    """
    loop = asyncio.get_running_loop()
    dir_results = await loop.run_in_executor(
        None,
        lambda: porringer.cache.list_directories(validate=True, check_manifest=True),
    )

    result = ToolUpdateResult()
    for dr in dir_results:
        if not dr.has_manifest:
            logger.debug('Skipping path without manifest: %s', dr.directory.path)
            continue
        path = Path(dr.directory.path)
        params = SetupParameters(
            paths=[path],
            project_directory=path if path.is_dir() else None,
            strategy=SyncStrategy.LATEST,
            plugins=plugins,
            include_packages=include_packages,
        )
        try:
            async for event in porringer.sync.execute_stream(
                params,
                plugins=discovered_plugins,
            ):
                if not isinstance(event, ActionCompletedEvent):
                    continue
                action_result = event.result
                if action_result.skipped:
                    if action_result.skip_reason in {
                        SkipReason.ALREADY_LATEST,
                        SkipReason.ALREADY_INSTALLED,
                    }:
                        result.already_latest += 1
                elif action_result.success:
                    result.updated += 1
                    if action_result.action.package:
                        result.updated_packages.add(str(action_result.action.package.name))
                else:
                    result.failed += 1
        except asyncio.CancelledError:
            logger.debug('run_tool_updates cancelled during manifest processing')
            raise
        result.manifests_processed += 1
    return result


async def run_package_remove(
    porringer: API,
    plugin_name: str,
    package_name: str,
    *,
    discovered_plugins: DiscoveredPlugins | None = None,
) -> SetupActionResult:
    """Uninstall a single package via the porringer API.

    Args:
        porringer: The porringer API instance.
        plugin_name: The installer plugin name (e.g. ``"pipx"``).
        package_name: The package to remove.
        discovered_plugins: Pre-discovered plugins to pass through to
            porringer, avoiding redundant discovery.

    Returns:
        A :class:`SetupActionResult` describing the outcome.
    """
    package_ref = PackageRef(name=package_name)
    return await porringer.package.uninstall(plugin_name, package_ref, plugins=discovered_plugins)


async def run_runtime_package_updates(
    porringer: API,
    plugin_name: str,
    runtime_tag: str,
    include_packages: set[str] | None = None,
    *,
    discovered_plugins: DiscoveredPlugins | None = None,
) -> ToolUpdateResult:
    """Upgrade packages for a single plugin scoped to a specific runtime tag.

    Args:
        porringer: The porringer API instance.
        plugin_name: The installer plugin name (e.g. ``"pipx"``).
        runtime_tag: The runtime version tag (e.g. ``"3.12"``).
        include_packages: Optional include-set of package names.
        discovered_plugins: Pre-discovered plugins to pass through.

    Returns:
        A :class:`ToolUpdateResult` summarising the run.
    """
    result = ToolUpdateResult()
    packages = await porringer.package.list_by_runtime(plugin_name, plugins=discovered_plugins)
    if packages is None:
        return result
    for rt in packages:
        if rt.tag != runtime_tag:
            continue
        for pkg in rt.packages:
            pkg_name = str(pkg.name)
            if include_packages is not None and pkg_name not in include_packages:
                continue
            package_ref = PackageRef(name=pkg_name)
            action_result = await porringer.package.upgrade(
                plugin_name,
                package_ref,
                runtime_tag=runtime_tag,
                plugins=discovered_plugins,
            )
            if action_result.skipped:
                result.already_latest += 1
            elif action_result.success:
                result.updated += 1
                result.updated_packages.add(pkg_name)
            else:
                result.failed += 1
        break
    return result
