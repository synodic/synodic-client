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
from porringer.schema import SetupParameters, SyncStrategy

from synodic_client.client import Client

logger = logging.getLogger(__name__)


async def check_for_update(client: Client) -> object:
    """Check for application updates off the main thread.

    Args:
        client: The Synodic Client service.

    Returns:
        An ``UpdateInfo`` result.
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


async def run_tool_updates(
    porringer: API,
    plugins: list[str] | None = None,
) -> int:
    """Re-sync all cached project manifests.

    Args:
        porringer: The porringer API instance.
        plugins: Optional include-list of plugin names.  When set, only
            actions handled by these plugins are executed.  ``None``
            means all plugins.

    Returns:
        Number of manifests processed.
    """
    loop = asyncio.get_running_loop()
    directories = await loop.run_in_executor(None, porringer.cache.list_directories)

    # Check all directories for manifests in parallel
    paths = [Path(d.path) for d in directories]
    has_results = await asyncio.gather(
        *(loop.run_in_executor(None, porringer.sync.has_manifest, p) for p in paths),
    )

    count = 0
    for path, has in zip(paths, has_results, strict=True):
        if not has:
            logger.debug('Skipping path without manifest: %s', path)
            continue
        params = SetupParameters(
            paths=[path],
            project_directory=path if path.is_dir() else None,
            strategy=SyncStrategy.LATEST,
            plugins=plugins,
        )
        async for _event in porringer.sync.execute_stream(params):
            pass  # consume events to completion
        count += 1
    return count
