"""Async background workers for the Synodic Client application.

Each coroutine runs on the caller's event loop (typically the qasync
main-thread loop) and communicates results via return values or
callbacks.  Blocking calls are wrapped in ``loop.run_in_executor``
to avoid stalling the GUI.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from porringer.api import API
from porringer.core.schema import PackageRef
from porringer.schema import ProgressEventKind, SetupParameters, SkipReason, SyncStrategy
from porringer.schema.execution import SetupActionResult

from synodic_client.client import Client
from synodic_client.updater import UpdateInfo

logger = logging.getLogger(__name__)


async def check_for_update(client: Client) -> UpdateInfo | None:
    """Check for application updates off the main thread.

    Args:
        client: The Synodic Client service.

    Returns:
        An ``UpdateInfo`` result, or ``None`` when no updater is initialised.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, client.check_for_update)


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

    return await loop.run_in_executor(None, _run)


@dataclass(slots=True)
class ToolUpdateResult:
    """Summary of a tool-update run across cached manifests."""

    manifests_processed: int = 0
    updated: int = 0
    already_latest: int = 0
    failed: int = 0
    updated_packages: set[str] = field(default_factory=set)
    """Package names that were successfully upgraded."""


async def run_tool_updates(
    porringer: API,
    plugins: set[str] | None = None,
    include_packages: set[str] | None = None,
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

    Returns:
        A :class:`ToolUpdateResult` summarising the run.
    """
    loop = asyncio.get_running_loop()
    directories = await loop.run_in_executor(None, porringer.cache.list_directories)

    # Check all directories for manifests in parallel
    paths = [Path(d.path) for d in directories]
    has_map: dict[Path, bool] = {}

    async def _check_manifest(p: Path) -> None:
        has_map[p] = await loop.run_in_executor(None, porringer.sync.has_manifest, p)

    async with asyncio.TaskGroup() as tg:
        for p in paths:
            tg.create_task(_check_manifest(p))

    result = ToolUpdateResult()
    for path in paths:
        has = has_map[path]
        if not has:
            logger.debug('Skipping path without manifest: %s', path)
            continue
        params = SetupParameters(
            paths=[path],
            project_directory=path if path.is_dir() else None,
            strategy=SyncStrategy.LATEST,
            plugins=plugins,
            include_packages=include_packages,
        )
        async for event in porringer.sync.execute_stream(params):
            if event.kind == ProgressEventKind.ACTION_COMPLETED and event.result is not None:
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
        result.manifests_processed += 1
    return result


async def run_package_remove(
    porringer: API,
    plugin_name: str,
    package_name: str,
) -> SetupActionResult:
    """Uninstall a single package via the porringer API.

    Args:
        porringer: The porringer API instance.
        plugin_name: The installer plugin name (e.g. ``"pipx"``).
        package_name: The package to remove.

    Returns:
        A :class:`SetupActionResult` describing the outcome.
    """
    package_ref = PackageRef(name=package_name)
    return await porringer.uninstall(plugin_name, package_ref)
