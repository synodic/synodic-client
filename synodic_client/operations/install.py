"""Install / preview operations.

Pure async functions for previewing and executing manifest installs.
No Qt, no signals — progress is reported via optional async callbacks.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from porringer.schema import (
    ActionCompletedEvent,
    ActionStartedEvent,
    ManifestLoadedEvent,
    ManifestParsedEvent,
    ProgressEvent,
    SetupParameters,
    SubActionProgressEvent,
    SyncStrategy,
)

from synodic_client.operations.schema import ActionInfo, PreviewResult

if TYPE_CHECKING:
    from porringer.api import API
    from porringer.backend.command.core.discovery import DiscoveredPlugins

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preview
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

    Downloads the manifest if *url* is remote, then runs
    ``execute_stream`` with ``dry_run=True`` to resolve actions.

    Args:
        porringer: The porringer API instance.
        url: Manifest URL or local path.
        project_directory: Optional project directory for the preview.
        prerelease_packages: Optional prerelease overrides.
        discovered: Pre-discovered plugins.

    Returns:
        A :class:`PreviewResult` with the resolved actions.
    """
    params = SetupParameters(
        paths=[url],
        dry_run=True,
        project_directory=project_directory,
        prerelease_packages=prerelease_packages,
    )

    actions: list[ActionInfo] = []
    project_name = ''
    description = ''
    manifest_key = url

    async for event in porringer.sync.execute_stream(params, plugins=discovered):
        if isinstance(event, ManifestParsedEvent):
            meta = event.manifest.metadata
            if meta:
                project_name = meta.name or ''
                description = meta.description or ''
            manifest_key = str(event.manifest.manifest_path or url)

        elif isinstance(event, ManifestLoadedEvent):
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


async def execute_install(  # noqa: PLR0913
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None = None,
    strategy: SyncStrategy = SyncStrategy.MINIMAL,
    prerelease_packages: set[str] | None = None,
    discovered: DiscoveredPlugins | None = None,
) -> AsyncIterator[tuple[str, ProgressEvent]]:
    """Execute setup actions and yield ``(stage, event)`` tuples.

    Yields ``("action_started", event)``, ``("sub_progress", event)``,
    ``("action_completed", event)``, etc. so callers can wire up
    progress tracking without coupling to porringer event kinds.

    Args:
        porringer: The porringer API instance.
        manifest_path: Path to the manifest file to execute.
        project_directory: Optional project directory scope.
        strategy: Sync strategy (MINIMAL or LATEST).
        prerelease_packages: Optional prerelease overrides.
        discovered: Pre-discovered plugins.

    Yields:
        ``(stage_name, event)`` tuples for progress tracking.
    """
    params = SetupParameters(
        paths=[manifest_path],
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
