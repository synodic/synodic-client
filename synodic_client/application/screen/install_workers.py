"""Async worker coroutines for install and preview operations.

Contains ``run_install``, ``run_preview``, and supporting helpers that
stream porringer events back to the GUI via callbacks.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from porringer.api import API
from porringer.backend.command.core.discovery import DiscoveredPlugins
from porringer.schema import (
    ActionCompletedEvent,
    ActionStartedEvent,
    DownloadParameters,
    ManifestLoadedEvent,
    ManifestParsedEvent,
    PluginsDiscoveredEvent,
    ProgressEvent,
    SetupAction,
    SetupActionResult,
    SetupParameters,
    SetupResults,
    SubActionProgressEvent,
)

from synodic_client.application.screen.schema import (
    InstallCallbacks,
    InstallConfig,
    PreviewCallbacks,
    PreviewConfig,
    _DispatchState,
)
from synodic_client.application.uri import resolve_local_path, safe_rmtree

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# run_install — execute setup actions via porringer
# ---------------------------------------------------------------------------


async def run_install(
    porringer: API,
    manifest_path: Path,
    config: InstallConfig | None = None,
    callbacks: InstallCallbacks | None = None,
    *,
    plugins: DiscoveredPlugins | None = None,
) -> SetupResults:
    """Execute setup actions via porringer and stream progress.

    Runs on the caller's event loop (typically the qasync main-thread
    loop).  Callbacks are invoked between ``await`` points so the GUI
    stays responsive without cross-thread signalling.

    Args:
        porringer: The porringer API instance.
        manifest_path: Path to the manifest file to execute.
        config: Optional execution parameters (directory, strategy,
            prerelease overrides).
        callbacks: Optional progress callbacks.
        plugins: Pre-discovered plugins to pass through to porringer,
            avoiding redundant discovery.

    Returns:
        Aggregated :class:`SetupResults`.
    """
    cfg = config or InstallConfig()
    cb = callbacks or InstallCallbacks()
    params = SetupParameters(
        paths=[manifest_path],
        project_directory=cfg.project_directory,
        strategy=cfg.strategy,
        prerelease_packages=cfg.prerelease_packages,
    )
    actions: list[SetupAction] = []
    collected: list[SetupActionResult] = []
    manifest_result: SetupResults | None = None

    async for event in porringer.sync.execute_stream(params, plugins=plugins):
        if isinstance(event, ManifestLoadedEvent):
            manifest_result = event.manifest
            actions = list(event.manifest.actions)

        elif isinstance(event, ActionStartedEvent) and cb.on_action_started is not None:
            cb.on_action_started(event.action)

        elif isinstance(event, SubActionProgressEvent) and cb.on_sub_progress is not None:
            cb.on_sub_progress(event.action, event.sub_action)

        elif isinstance(event, ActionCompletedEvent):
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
# _resolve_manifest_path — local or download
# ---------------------------------------------------------------------------


async def _resolve_manifest_path(url: str) -> tuple[Path, str | None]:
    """Resolve *url* to a local manifest path, downloading if remote.

    Returns:
        ``(manifest_path, temp_dir)`` — *temp_dir* is ``None`` for local
        manifests and a temporary directory string for downloads.

    Raises:
        FileNotFoundError: If a local path does not exist.
        RuntimeError: If the download fails.
    """
    local_path = resolve_local_path(url)

    if local_path is not None:
        if not local_path.exists():
            msg = f'Manifest not found:\n{local_path}'
            raise FileNotFoundError(msg)
        return local_path, None

    temp_dir = tempfile.mkdtemp(prefix='synodic_install_')
    dest = Path(temp_dir) / 'porringer.json'

    params = DownloadParameters(url=url, destination=dest, timeout=3)
    result = await API.download(params)

    if not result.success:
        safe_rmtree(temp_dir)
        msg = f'Failed to download manifest:\n{result.message}'
        raise RuntimeError(msg)

    return dest, temp_dir


# ---------------------------------------------------------------------------
# _dispatch_preview_event — route stream events to callbacks
# ---------------------------------------------------------------------------


def _dispatch_preview_event(
    event: ProgressEvent,
    manifest_path: str,
    temp_dir_str: str,
    state: _DispatchState,
    cb: PreviewCallbacks,
) -> None:
    """Route a single preview stream event to the appropriate callback.

    Mutates *state* in-place (``got_parsed`` flag).
    """
    if isinstance(event, ManifestParsedEvent):
        if cb.on_manifest_parsed is not None:
            cb.on_manifest_parsed(event.manifest, manifest_path, temp_dir_str)
        state.got_parsed = True
        return

    if isinstance(event, PluginsDiscoveredEvent) and cb.on_plugins_queried is not None:
        availability = {entry.name: entry.available for entry in event.discovered_plugins}
        capabilities = {entry.name: entry.capabilities for entry in event.discovered_plugins}
        cb.on_plugins_queried(availability, capabilities)
        return

    if isinstance(event, ManifestLoadedEvent):
        if cb.on_preview_ready is not None:
            cb.on_preview_ready(event.manifest, manifest_path, temp_dir_str)
        return

    if isinstance(event, ActionCompletedEvent) and event.action_index is not None and cb.on_action_checked is not None:
        cb.on_action_checked(event.action_index, event.result)


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

    Runs on the caller's event loop (typically the qasync main-thread
    loop).  Callbacks fire between ``await`` points so the GUI remains
    responsive without cross-thread signalling.

    Combines two stages:

    1. Download the manifest (if remote) — runs in a thread-pool executor.
    2. Run ``execute_stream`` with ``dry_run=True`` to stream events.

    Args:
        porringer: The porringer API instance.
        url: Manifest URL or local path.
        config: Optional preview configuration.
        callbacks: Optional preview callbacks.
        plugins: Pre-discovered plugins to pass through to porringer,
            avoiding redundant discovery.
    """
    logger.info('run_preview starting for: %s', url)
    temp_dir: str | None = None
    cb = callbacks or PreviewCallbacks()
    cfg = config or PreviewConfig()
    try:
        manifest_path, temp_dir = await _resolve_manifest_path(url)

        # Dry-run: parses manifest, resolves actions, and checks status
        setup_params = SetupParameters(
            paths=[manifest_path],
            dry_run=True,
            project_directory=cfg.project_directory,
            prerelease_packages=cfg.prerelease_packages,
        )
        state = _DispatchState()
        temp_dir_str = temp_dir or ''
        manifest_path_str = str(manifest_path)

        async for event in porringer.sync.execute_stream(setup_params, plugins=plugins):
            _dispatch_preview_event(
                event,
                manifest_path_str,
                temp_dir_str,
                state,
                cb,
            )

    except asyncio.CancelledError:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise
    except Exception:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise
