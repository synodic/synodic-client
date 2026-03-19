"""Async worker coroutines for install and preview operations.

Contains ``run_install``, ``run_preview``, ``run_post_sync``, and
supporting helpers that stream porringer events back to the GUI via
callbacks.  All execution delegates to the operations layer to
avoid direct porringer API coupling.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from porringer.api import API
from porringer.backend.command.core.discovery import DiscoveredPlugins
from porringer.schema import (
    ActionCompletedEvent,
    ActionStartedEvent,
    SetupResults,
    SubActionProgressEvent,
)

from synodic_client.application.screen.schema import (
    InstallCallbacks,
    InstallConfig,
    PreviewConfig,
)
from synodic_client.application.uri import safe_rmtree
from synodic_client.operations.install import collect_install, collect_post_sync, preview_manifest_stream
from synodic_client.operations.schema import (
    PreviewEvent,
    PreviewManifestParsed,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# run_install — execute setup actions via operations layer
# ---------------------------------------------------------------------------


async def run_install(
    porringer: API,
    manifest_path: Path,
    config: InstallConfig | None = None,
    callbacks: InstallCallbacks | None = None,
    *,
    plugins: DiscoveredPlugins | None = None,
    exclude_post_sync: bool = False,
) -> SetupResults:
    """Execute setup actions via the operations layer and stream progress.

    Delegates to :func:`~synodic_client.operations.install.collect_install`
    and routes progress events to GUI callbacks.
    """
    cfg = config or InstallConfig()
    cb = callbacks or InstallCallbacks()

    def _on_progress(stage: str, event: object) -> None:
        if stage == 'action_started' and isinstance(event, ActionStartedEvent) and cb.on_action_started is not None:
            cb.on_action_started(event.action)
        elif stage == 'sub_progress' and isinstance(event, SubActionProgressEvent) and cb.on_sub_progress is not None:
            cb.on_sub_progress(event.action, event.sub_action)
        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent) and cb.on_progress is not None:
            cb.on_progress(event.action, event.result)

    return await collect_install(
        porringer,
        manifest_path,
        project_directory=cfg.project_directory,
        strategy=cfg.strategy,
        prerelease_packages=cfg.prerelease_packages,
        discovered=plugins,
        exclude_post_sync=exclude_post_sync,
        on_progress=_on_progress,
    )


# ---------------------------------------------------------------------------
# run_post_sync — execute only post-sync commands via operations layer
# ---------------------------------------------------------------------------


async def run_post_sync(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    callbacks: InstallCallbacks | None = None,
    plugins: DiscoveredPlugins | None = None,
) -> SetupResults:
    """Execute only the post-sync commands from a manifest.

    Delegates to :func:`~synodic_client.operations.install.collect_post_sync`
    and routes progress events to GUI callbacks.
    """
    cb = callbacks or InstallCallbacks()

    def _on_progress(stage: str, event: object) -> None:
        if stage == 'action_started' and isinstance(event, ActionStartedEvent) and cb.on_action_started is not None:
            cb.on_action_started(event.action)
        elif stage == 'sub_progress' and isinstance(event, SubActionProgressEvent) and cb.on_sub_progress is not None:
            cb.on_sub_progress(event.action, event.sub_action)
        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent) and cb.on_progress is not None:
            cb.on_progress(event.action, event.result)

    return await collect_post_sync(
        porringer,
        manifest_path,
        project_directory=project_directory,
        discovered=plugins,
        on_progress=_on_progress,
    )


# ---------------------------------------------------------------------------
# run_preview — dry-run preview of a manifest
# ---------------------------------------------------------------------------


async def run_preview(
    porringer: API,
    url: str,
    *,
    config: PreviewConfig | None = None,
    on_event: Callable[[PreviewEvent], object] | None = None,
    plugins: DiscoveredPlugins | None = None,
) -> None:
    """Download a manifest and perform a dry-run preview.

    Delegates to :func:`preview_manifest_stream` in the operations
    layer, then yields each :data:`PreviewEvent` to *on_event*.
    """
    logger.info('run_preview starting for: %s', url)
    cfg = config or PreviewConfig()
    temp_dir: str | None = None
    try:
        async for event in preview_manifest_stream(
            porringer,
            url,
            project_directory=cfg.project_directory,
            prerelease_packages=cfg.prerelease_packages,
            discovered=plugins,
        ):
            if isinstance(event, PreviewManifestParsed):
                temp_dir = event.temp_dir or None

            if on_event is not None:
                on_event(event)

    except asyncio.CancelledError:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise
    except Exception:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise
