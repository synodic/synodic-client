"""Install / preview operations.

Pure async functions for previewing and executing manifest installs.
No Qt, no signals — progress is reported via streaming async iterators.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING

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
    SyncStrategy,
)

from synodic_client.application.uri import resolve_local_path, safe_rmtree
from synodic_client.operations.schema import (
    ActionInfo,
    PreviewActionChecked,
    PreviewEvent,
    PreviewManifestParsed,
    PreviewPluginsQueried,
    PreviewReady,
    PreviewResult,
    resolve_action_status,
)

if TYPE_CHECKING:
    from porringer.api import API
    from porringer.backend.command.core.discovery import DiscoveredPlugins

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Manifest resolution
# ---------------------------------------------------------------------------


async def resolve_manifest_path(url: str) -> tuple[Path, str | None]:
    """Resolve *url* to a local manifest path, downloading if remote.

    Returns:
        ``(manifest_path, temp_dir)`` — *temp_dir* is ``None`` for local
        manifests and a temporary directory string for downloads.

    Raises:
        FileNotFoundError: If a local path does not exist.
        RuntimeError: If the download fails.
    """
    from porringer.api import API as _API

    local_path = resolve_local_path(url)

    if local_path is not None:
        if not local_path.exists():
            msg = f'Manifest not found:\n{local_path}'
            raise FileNotFoundError(msg)
        return local_path, None

    temp_dir = tempfile.mkdtemp(prefix='synodic_install_')
    dest = Path(temp_dir) / 'porringer.json'

    params = DownloadParameters(url=url, destination=dest, timeout=3)
    result = await _API.download(params)

    if not result.success:
        safe_rmtree(temp_dir)
        msg = f'Failed to download manifest:\n{result.message}'
        raise RuntimeError(msg)

    return dest, temp_dir


# ---------------------------------------------------------------------------
# Streaming preview
# ---------------------------------------------------------------------------


async def preview_manifest_stream(
    porringer: API,
    url: str,
    *,
    project_directory: Path | None = None,
    prerelease_packages: set[str] | None = None,
    discovered: DiscoveredPlugins | None = None,
    resolve: bool = True,
) -> AsyncIterator[PreviewEvent]:
    """Stream dry-run preview events for a manifest.

    Resolves the manifest (downloading if remote), then runs
    ``execute_stream`` with ``dry_run=True``.  Each porringer event
    is translated into a :data:`PreviewEvent` and yielded.

    Per-action results include a pre-resolved ``status`` string
    via :func:`resolve_action_status`.

    Args:
        porringer: The porringer API instance.
        url: Manifest URL or local path.
        project_directory: Optional project directory for the preview.
        prerelease_packages: Optional prerelease overrides.
        discovered: Pre-discovered plugins.
        resolve: Whether to resolve the URL to a local path first
            (downloading if remote).  When ``False`` the raw *url*
            is passed directly to porringer.

    Yields:
        :data:`PreviewEvent` instances as they arrive.
    """
    temp_dir: str | None = None
    if resolve:
        manifest_path, temp_dir = await resolve_manifest_path(url)
    else:
        manifest_path = Path(url) if resolve_local_path(url) is not None else None  # type: ignore[assignment]

    manifest_path_str = str(manifest_path) if manifest_path is not None else url
    temp_dir_str = temp_dir or ''

    try:
        params = SetupParameters(
            paths=[manifest_path or url],
            dry_run=True,
            project_directory=project_directory,
            prerelease_packages=prerelease_packages,
        )

        async for event in porringer.sync.execute_stream(params, plugins=discovered):
            if isinstance(event, ManifestParsedEvent):
                yield PreviewManifestParsed(
                    manifest=event.manifest,
                    manifest_path=manifest_path_str,
                    temp_dir=temp_dir_str,
                )

            elif isinstance(event, PluginsDiscoveredEvent):
                availability = {entry.name: entry.available for entry in event.discovered_plugins}
                capabilities = {entry.name: entry.capabilities for entry in event.discovered_plugins}
                yield PreviewPluginsQueried(
                    availability=availability,
                    capabilities=capabilities,
                )

            elif isinstance(event, ManifestLoadedEvent):
                yield PreviewReady(
                    manifest=event.manifest,
                    manifest_path=manifest_path_str,
                    temp_dir=temp_dir_str,
                )

            elif isinstance(event, ActionCompletedEvent) and event.action_index is not None:
                status = resolve_action_status(event.result, event.action)
                yield PreviewActionChecked(
                    index=event.action_index,
                    result=event.result,
                    status=status,
                )

    except BaseException:
        if temp_dir:
            safe_rmtree(temp_dir)
        raise


# ---------------------------------------------------------------------------
# Batch preview (convenience wrapper)
# ---------------------------------------------------------------------------


async def preview_manifest(
    porringer: API,
    url: str,
    *,
    project_directory: Path | None = None,
    prerelease_packages: set[str] | None = None,
    discovered: DiscoveredPlugins | None = None,
) -> PreviewResult:
    """Perform a dry-run preview of a manifest.

    Consumes :func:`preview_manifest_stream` and returns a single
    :class:`PreviewResult` with all resolved actions.
    """
    actions: list[ActionInfo] = []
    project_name = ''
    description = ''
    manifest_key = url

    async for event in preview_manifest_stream(
        porringer,
        url,
        project_directory=project_directory,
        prerelease_packages=prerelease_packages,
        discovered=discovered,
        resolve=False,
    ):
        if isinstance(event, PreviewManifestParsed):
            meta = event.manifest.metadata
            if meta:
                project_name = meta.name or ''
                description = meta.description or ''
            manifest_key = str(event.manifest.manifest_path or url)

        elif isinstance(event, PreviewReady):
            for act in event.manifest.actions:
                actions.append(
                    ActionInfo(
                        description=act.description,
                        kind=act.kind.name if act.kind else None,
                        package=str(act.package.name) if act.package else None,
                        constraint=act.package.constraint if act.package else None,
                        installer=act.installer,
                    )
                )

    return PreviewResult(
        manifest_key=manifest_key,
        project_name=project_name,
        description=description,
        actions=actions,
    )


# ---------------------------------------------------------------------------
# Execute install
# ---------------------------------------------------------------------------


async def execute_install(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    strategy: SyncStrategy = SyncStrategy.MINIMAL,
    prerelease_packages: set[str] | None = None,
    discovered: DiscoveredPlugins | None = None,
    exclude_post_sync: bool = False,
) -> AsyncIterator[tuple[str, ProgressEvent]]:
    """Execute setup actions and yield ``(stage, event)`` tuples.

    Yields ``("action_started", event)``, ``("sub_progress", event)``,
    ``("action_completed", event)``, etc. so callers can wire up
    progress tracking without coupling to porringer event kinds.

    Args:
        porringer: The porringer API instance.
        manifest_path: Path to the manifest file.
        project_directory: Optional project directory override.
        strategy: Sync strategy (MINIMAL, LATEST, EXACT).
        prerelease_packages: Optional prerelease overrides.
        discovered: Pre-discovered plugins.
        exclude_post_sync: When ``True``, post-sync commands are
            stripped from the manifest before execution.  Use this
            when post-sync is handled separately via
            :func:`execute_post_sync`.
    """
    effective_path = manifest_path

    if exclude_post_sync:
        effective_path = _strip_post_sync(manifest_path)

    try:
        params = SetupParameters(
            paths=[effective_path],
            project_directory=project_directory,
            strategy=strategy,
            prerelease_packages=prerelease_packages,
        )

        async for event in porringer.sync.execute_stream(params, plugins=discovered):
            if isinstance(event, ManifestLoadedEvent):
                yield ('manifest_loaded', event)
            elif isinstance(event, ActionStartedEvent):
                yield ('action_started', event)
            elif isinstance(event, SubActionProgressEvent):
                yield ('sub_progress', event)
            elif isinstance(event, ActionCompletedEvent):
                yield ('action_completed', event)
            else:
                yield ('other', event)
    finally:
        if exclude_post_sync and effective_path != manifest_path:
            effective_path.unlink(missing_ok=True)


async def execute_post_sync(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    discovered: DiscoveredPlugins | None = None,
) -> AsyncIterator[tuple[str, ProgressEvent]]:
    """Execute only the post-sync commands from a manifest.

    Builds a temporary manifest containing only the ``post_sync``
    entries from the original, then streams execution events.

    Args:
        porringer: The porringer API instance.
        manifest_path: Path to the original manifest file.
        project_directory: Optional project directory override.
        discovered: Pre-discovered plugins.

    Yields:
        ``(stage, event)`` tuples identical to :func:`execute_install`.
    """
    post_sync_path = _extract_post_sync(manifest_path)
    if post_sync_path is None:
        return

    try:
        params = SetupParameters(
            paths=[post_sync_path],
            project_directory=project_directory,
        )

        async for event in porringer.sync.execute_stream(params, plugins=discovered):
            if isinstance(event, ManifestLoadedEvent):
                yield ('manifest_loaded', event)
            elif isinstance(event, ActionStartedEvent):
                yield ('action_started', event)
            elif isinstance(event, SubActionProgressEvent):
                yield ('sub_progress', event)
            elif isinstance(event, ActionCompletedEvent):
                yield ('action_completed', event)
            else:
                yield ('other', event)
    finally:
        post_sync_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Batch collect helpers — consume a stream and return SetupResults
# ---------------------------------------------------------------------------

InstallProgressCallback = Callable[[str, ProgressEvent], None]


async def collect_install(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    strategy: SyncStrategy = SyncStrategy.MINIMAL,
    prerelease_packages: set[str] | None = None,
    discovered: DiscoveredPlugins | None = None,
    exclude_post_sync: bool = False,
    on_progress: InstallProgressCallback | None = None,
) -> SetupResults:
    """Execute install actions and return collected results.

    Consumes :func:`execute_install` internally, collecting action
    results and optionally forwarding each ``(stage, event)`` to
    *on_progress* for UI updates.
    """
    actions: list[SetupAction] = []
    collected: list[SetupActionResult] = []
    manifest_result: SetupResults | None = None

    async for stage, event in execute_install(
        porringer,
        manifest_path,
        project_directory=project_directory,
        strategy=strategy,
        prerelease_packages=prerelease_packages,
        discovered=discovered,
        exclude_post_sync=exclude_post_sync,
    ):
        if stage == 'manifest_loaded' and isinstance(event, ManifestLoadedEvent):
            manifest_result = event.manifest
            actions = list(event.manifest.actions)
        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent):
            collected.append(event.result)

        if on_progress is not None:
            on_progress(stage, event)

    return SetupResults(
        actions=actions,
        results=collected,
        manifest_path=manifest_result.manifest_path if manifest_result else None,
        metadata=manifest_result.metadata if manifest_result else None,
    )


async def collect_post_sync(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    discovered: DiscoveredPlugins | None = None,
    on_progress: InstallProgressCallback | None = None,
) -> SetupResults:
    """Execute post-sync commands and return collected results.

    Consumes :func:`execute_post_sync` internally, collecting action
    results and optionally forwarding each ``(stage, event)`` to
    *on_progress* for UI updates.
    """
    actions: list[SetupAction] = []
    collected: list[SetupActionResult] = []
    manifest_result: SetupResults | None = None

    async for stage, event in execute_post_sync(
        porringer,
        manifest_path,
        project_directory=project_directory,
        discovered=discovered,
    ):
        if stage == 'manifest_loaded' and isinstance(event, ManifestLoadedEvent):
            manifest_result = event.manifest
            actions = list(event.manifest.actions)
        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent):
            collected.append(event.result)

        if on_progress is not None:
            on_progress(stage, event)

    return SetupResults(
        actions=actions,
        results=collected,
        manifest_path=manifest_result.manifest_path if manifest_result else None,
        metadata=manifest_result.metadata if manifest_result else None,
    )


def _strip_post_sync(manifest_path: Path) -> Path:
    """Return a temp manifest copy with ``post_sync`` cleared.

    If the manifest has no ``post_sync`` entries, returns the
    original path unchanged.
    """
    import json

    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not data.get('post_sync'):
        return manifest_path

    data['post_sync'] = []
    fd, tmp_str = tempfile.mkstemp(prefix='synodic_nosync_', suffix='.json')
    tmp = Path(tmp_str)
    tmp.write_text(json.dumps(data), encoding='utf-8')
    os.close(fd)
    return tmp


def _extract_post_sync(manifest_path: Path) -> Path | None:
    """Return a temp manifest containing only ``post_sync`` entries.

    Returns ``None`` if the manifest has no ``post_sync`` entries.
    """
    import json

    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    post_sync = data.get('post_sync', [])
    if not post_sync:
        return None

    minimal = {'version': data.get('version', '1'), 'post_sync': post_sync}
    fd, tmp_str = tempfile.mkstemp(prefix='synodic_postsync_', suffix='.json')
    tmp = Path(tmp_str)
    tmp.write_text(json.dumps(minimal), encoding='utf-8')
    os.close(fd)
    return tmp


# ---------------------------------------------------------------------------
# Manifest action loading (lightweight, no dry-run checking)
# ---------------------------------------------------------------------------


async def load_manifest_actions(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    discovered: DiscoveredPlugins | None = None,
) -> list[SetupAction]:
    """Load the action list from a manifest without dry-run checking.

    When *discovered* plugins are provided, uses the efficient
    ``async_load_manifest`` single-shot path.  Otherwise falls back
    to streaming ``execute_stream`` with ``dry_run=True`` and
    extracting actions from the first parse event.

    Args:
        porringer: The porringer API instance.
        manifest_path: Path to the manifest file.
        project_directory: Optional project directory override.
        discovered: Pre-discovered plugins for the fast path.

    Returns:
        The list of :class:`SetupAction` entries from the manifest.
    """
    if discovered is not None:
        result = await porringer.sync.async_load_manifest(
            manifest_path,
            SyncStrategy.MINIMAL,
            plugins=discovered,
        )
        return list(result.actions)

    # Legacy streaming fallback
    params = SetupParameters(
        paths=[str(manifest_path)],
        dry_run=True,
        project_directory=project_directory,
    )
    actions: list[SetupAction] = []
    async for event in porringer.sync.execute_stream(params):
        if isinstance(event, ManifestParsedEvent):
            actions.extend(event.manifest.actions)
            break
    return actions
