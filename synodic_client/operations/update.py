"""Self-update operations.

Pure functions for checking, downloading, and applying synodic-client
self-updates.  No Qt, no signals — the controller layer handles UI
concerns.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from synodic_client.operations.schema import DownloadResult, UpdateCheckResult

if TYPE_CHECKING:
    from synodic_client.client import Client

logger = logging.getLogger(__name__)


async def check_self_update(client: Client) -> UpdateCheckResult:
    """Check whether a newer version of synodic-client is available.

    Runs the blocking Velopack check in a thread-pool executor.

    Args:
        client: The Synodic Client service facade.

    Returns:
        An :class:`UpdateCheckResult` describing availability.
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, client.check_for_update)
    except asyncio.CancelledError:
        logger.debug('check_self_update cancelled')
        raise

    if result is None:
        return UpdateCheckResult(
            available=False,
            current_version=str(client.version),
            error='Updater is not initialized.',
        )

    if result.error:
        return UpdateCheckResult(
            available=False,
            current_version=str(result.current_version),
            error=result.error,
        )

    return UpdateCheckResult(
        available=result.available,
        current_version=str(result.current_version),
        version=str(result.latest_version) if result.latest_version else None,
    )


async def download_self_update(
    client: Client,
    on_progress: Callable[[int], None] | None = None,
) -> DownloadResult:
    """Download a self-update, reporting progress via *on_progress*.

    Args:
        client: The Synodic Client service facade.
        on_progress: Optional callback for percentage progress (0–100).

    Returns:
        A :class:`DownloadResult` describing success/failure.
    """
    loop = asyncio.get_running_loop()

    def _run() -> bool:
        def _progress(percentage: int) -> None:
            if on_progress is not None:
                loop.call_soon_threadsafe(on_progress, percentage)

        return client.download_update(_progress)

    try:
        success = await loop.run_in_executor(None, _run)
    except asyncio.CancelledError:
        logger.debug('download_self_update cancelled')
        raise

    version = str(client.version)
    if success:
        return DownloadResult(success=True, version=version)
    return DownloadResult(success=False, version=version, error='Download failed.')


def apply_self_update(client: Client, *, restart: bool = True, silent: bool = False) -> None:
    """Schedule the downloaded update to apply on exit.

    Args:
        client: The Synodic Client service facade.
        restart: Whether to restart after applying.
        silent: Whether to suppress the Velopack splash window.
    """
    client.apply_update_on_exit(restart=restart, silent=silent)
