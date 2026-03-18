"""Async worker coroutines for install and preview operations.

Contains ``run_install``, ``run_preview``, ``run_post_sync``, and
supporting helpers that stream porringer events back to the GUI via
callbacks.  All execution delegates to the operations layer to
avoid direct porringer API coupling.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from porringer.api import API
from porringer.backend.command.core.discovery import DiscoveredPlugins
from porringer.schema import (
    ActionCompletedEvent,
    ActionStartedEvent,
    ManifestLoadedEvent,
    SetupAction,
    SetupActionResult,
    SetupResults,
    SubActionProgressEvent,
)

from synodic_client.application.screen.schema import (
    InstallCallbacks,
    InstallConfig,
    PreviewCallbacks,
    PreviewConfig,
)
from synodic_client.application.uri import safe_rmtree
from synodic_client.operations.install import execute_install, execute_post_sync, preview_manifest_stream
from synodic_client.operations.schema import (
    PreviewActionChecked,
    PreviewManifestParsed,
    PreviewPluginsQueried,
    PreviewReady,
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

    Delegates to :func:`~synodic_client.operations.install.execute_install`
    and routes the tagged ``(stage, event)`` stream to GUI callbacks.
    """
    cfg = config or InstallConfig()
    cb = callbacks or InstallCallbacks()
    actions: list[SetupAction] = []
    collected: list[SetupActionResult] = []
    manifest_result: SetupResults | None = None

    async for stage, event in execute_install(
        porringer,
        manifest_path,
        project_directory=cfg.project_directory,
        strategy=cfg.strategy,
        prerelease_packages=cfg.prerelease_packages,
        discovered=plugins,
        exclude_post_sync=exclude_post_sync,
    ):
        if stage == 'manifest_loaded' and isinstance(event, ManifestLoadedEvent):
            manifest_result = event.manifest
            actions = list(event.manifest.actions)

        elif stage == 'action_started' and isinstance(event, ActionStartedEvent) and cb.on_action_started is not None:
            cb.on_action_started(event.action)

        elif stage == 'sub_progress' and isinstance(event, SubActionProgressEvent) and cb.on_sub_progress is not None:
            cb.on_sub_progress(event.action, event.sub_action)

        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent):
            collected.append(event.result)
            if cb.on_progress is not None:
                cb.on_progress(event.action, event.result)

    return SetupResults(
        actions=actions,
        results=collected,
        manifest_path=manifest_result.manifest_path if manifest_result else None,
        metadata=manifest_result.metadata if manifest_result else None,
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

    Delegates to :func:`~synodic_client.operations.install.execute_post_sync`
    and routes events to GUI callbacks.
    """
    cb = callbacks or InstallCallbacks()
    actions: list[SetupAction] = []
    collected: list[SetupActionResult] = []
    manifest_result: SetupResults | None = None

    async for stage, event in execute_post_sync(
        porringer,
        manifest_path,
        project_directory=project_directory,
        discovered=plugins,
    ):
        if stage == 'manifest_loaded' and isinstance(event, ManifestLoadedEvent):
            manifest_result = event.manifest
            actions = list(event.manifest.actions)

        elif stage == 'action_started' and isinstance(event, ActionStartedEvent) and cb.on_action_started is not None:
            cb.on_action_started(event.action)

        elif stage == 'sub_progress' and isinstance(event, SubActionProgressEvent) and cb.on_sub_progress is not None:
            cb.on_sub_progress(event.action, event.sub_action)

        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent):
            collected.append(event.result)
            if cb.on_progress is not None:
                cb.on_progress(event.action, event.result)

    return SetupResults(
        actions=actions,
        results=collected,
        manifest_path=manifest_result.manifest_path if manifest_result else None,
        metadata=manifest_result.metadata if manifest_result else None,
    )


# ---------------------------------------------------------------------------
# run_preview — dry-run preview of a manifest
# ---------------------------------------------------------------------------


async def run_preview(
    porringer: API,
    url: str,
    *,
    config: PreviewConfig | None = None,
    callbacks: PreviewCallbacks | None = None,
    plugins: DiscoveredPlugins | None = None,
) -> None:
    """Download a manifest and perform a dry-run preview.

    Delegates to :func:`preview_manifest_stream` in the operations
    layer, then routes each :data:`PreviewEvent` to the appropriate
    callback.
    """
    logger.info('run_preview starting for: %s', url)
    cb = callbacks or PreviewCallbacks()
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
                if cb.on_manifest_parsed is not None:
                    cb.on_manifest_parsed(event.manifest, event.manifest_path, event.temp_dir)

            elif isinstance(event, PreviewPluginsQueried) and cb.on_plugins_queried is not None:
                cb.on_plugins_queried(event.availability, event.capabilities)

            elif isinstance(event, PreviewReady):
                if cb.on_preview_ready is not None:
                    cb.on_preview_ready(event.manifest, event.manifest_path, event.temp_dir)

            elif isinstance(event, PreviewActionChecked) and cb.on_action_checked is not None:
                cb.on_action_checked(event.index, event.result, event.status)

    except asyncio.CancelledError:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise
    except Exception:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise
