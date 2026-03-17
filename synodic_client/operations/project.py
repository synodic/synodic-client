"""Project directory operations.

Pure functions for listing, adding, removing, and querying status of
cached project directories.  No Qt, no signals — just porringer API
calls in → typed results out.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from porringer.schema import SkipReason

from synodic_client.operations.schema import (
    ActionInfo,
    ProjectInfo,
    ProjectStatus,
    StatusSummary,
)

if TYPE_CHECKING:
    from porringer.api import API
    from porringer.backend.command.core.discovery import DiscoveredPlugins

logger = logging.getLogger(__name__)


def find_manifest(porringer: API, directory: str | Path) -> Path | None:
    """Locate the manifest file inside a project directory.

    Iterates the recognised manifest filenames from porringer and
    returns the first candidate that exists on disk, or ``None``.
    """
    path = Path(directory)
    for fname in porringer.sync.manifest_filenames():
        candidate = path / fname
        if candidate.exists():
            return candidate
    return None


def list_projects(porringer: API) -> list[ProjectInfo]:
    """List all cached project directories with validation status.

    Args:
        porringer: The porringer API instance.

    Returns:
        A list of :class:`ProjectInfo` for every cached directory.
    """
    results = porringer.cache.list_directories(validate=True, check_manifest=True)
    return [
        ProjectInfo(
            path=str(r.directory.path),
            name=r.directory.name or '',
            exists=r.exists or False,
            has_manifest=r.has_manifest or False,
        )
        for r in results
    ]


def add_project(porringer: API, path: str | Path) -> ProjectInfo:
    """Add a directory to the porringer project cache.

    Args:
        porringer: The porringer API instance.
        path: Filesystem path to add.

    Returns:
        A :class:`ProjectInfo` for the newly added directory.

    Raises:
        NotADirectoryError: If *path* is not an existing directory.
        ValueError: If porringer rejects the directory (e.g. duplicate).
    """
    directory = Path(path)
    if not directory.is_dir():
        msg = f'Not a directory: {directory}'
        raise NotADirectoryError(msg)

    porringer.cache.add_directory(directory)

    # Re-query to get validation status for the returned info.
    for r in porringer.cache.list_directories(validate=True, check_manifest=True):
        if Path(r.directory.path) == directory:
            return ProjectInfo(
                path=str(r.directory.path),
                name=r.directory.name or '',
                exists=r.exists or False,
                has_manifest=r.has_manifest or False,
            )

    # Shouldn't happen, but satisfy the return type.
    return ProjectInfo(
        path=str(directory),
        name=directory.stem,
        exists=directory.exists(),
        has_manifest=False,
    )


def remove_project(porringer: API, path: str | Path) -> None:
    """Remove a directory from the porringer project cache.

    Args:
        porringer: The porringer API instance.
        path: Filesystem path to remove.
    """
    porringer.cache.remove_directory(Path(path))


def _run_add_project(arg: str | None, porringer: API) -> dict:
    if not arg:
        return {'error': 'add_project requires a path argument'}
    try:
        add_project(porringer, arg)
    except (NotADirectoryError, ValueError) as exc:
        return {'error': str(exc)}
    return {'ok': True, 'action': 'add_project', 'path': arg}


def _run_remove_project(arg: str | None, porringer: API) -> dict:
    if not arg:
        return {'error': 'remove_project requires a path argument'}
    remove_project(porringer, arg)
    return {'ok': True, 'action': 'remove_project', 'path': arg}


def _run_project_status(arg: str | None, porringer: API) -> dict:
    import asyncio
    import dataclasses

    if not arg:
        return {'error': 'project_status requires a path argument in headless mode'}
    status = asyncio.run(project_status(porringer, arg))
    return dataclasses.asdict(status)


def run_project_action(
    name: str,
    arg: str | None,
    porringer: API,
) -> dict:
    """Execute a project-management debug action headlessly.

    Returns a plain dict suitable for JSON serialization.
    Handles ``list_projects``, ``add_project``, ``remove_project``, and
    ``project_status``.  Unknown actions return ``{'error': …}``.
    """
    import dataclasses

    if name == 'list_projects':
        projects = list_projects(porringer)
        return {'projects': [dataclasses.asdict(p) for p in projects]}

    handlers: dict[str, Callable[[str | None, API], dict]] = {
        'add_project': _run_add_project,
        'remove_project': _run_remove_project,
        'project_status': _run_project_status,
    }
    handler = handlers.get(name)
    if handler is not None:
        return handler(arg, porringer)

    return {'error': f'unknown project action: {name}'}


async def project_status(
    porringer: API,
    path: str | Path,
    *,
    discovered: DiscoveredPlugins | None = None,
    fast: bool = False,
) -> ProjectStatus:
    """Compute the requirement status for a project directory.

    Discovers the manifest, runs a dry-run preview via
    :func:`~synodic_client.operations.install.preview_manifest_stream`,
    and returns a :class:`ProjectStatus` with resolved action statuses.

    Args:
        porringer: The porringer API instance.
        path: Filesystem path of the project directory.
        discovered: Pre-discovered plugins (speeds up resolution).
        fast: When ``True``, return actions from the manifest parse
            without waiting for per-action dry-run checks.
    """
    from synodic_client.operations.install import preview_manifest_stream
    from synodic_client.operations.schema import (
        PreviewActionChecked,
        PreviewManifestParsed,
        PreviewReady,
        classify_status,
    )

    directory = Path(path)
    manifest_path = find_manifest(porringer, directory)

    if manifest_path is None:
        return ProjectStatus(path=str(directory), phase='no_manifest')

    actions: list[ActionInfo] = []
    checked_count = 0
    needed = 0
    satisfied = 0
    pending = 0
    upgradable = 0

    async for event in preview_manifest_stream(
        porringer,
        str(manifest_path),
        project_directory=directory,
        discovered=discovered,
        resolve=False,
    ):
        if isinstance(event, (PreviewManifestParsed, PreviewReady)):
            if not actions:
                actions = [
                    ActionInfo(
                        description=a.description,
                        kind=a.kind.name if a.kind else None,
                        package=str(a.package.name) if a.package else None,
                        constraint=a.package.constraint if a.package else None,
                        installer=a.installer,
                    )
                    for a in event.manifest.actions
                ]

        elif isinstance(event, PreviewActionChecked):
            if event.index < len(actions):
                old = actions[event.index]
                actions[event.index] = ActionInfo(
                    description=old.description,
                    kind=old.kind,
                    status=event.status,
                    package=old.package,
                    constraint=old.constraint,
                    installer=old.installer,
                )
            checked_count += 1

            bucket = classify_status(event.status)
            if bucket == 'needed':
                needed += 1
            elif bucket == 'satisfied':
                satisfied += 1
            elif bucket == 'pending':
                pending += 1
            if event.result.skip_reason == SkipReason.UPDATE_AVAILABLE:
                upgradable += 1

    phase = 'ready' if not fast or checked_count > 0 else 'parsed'

    return ProjectStatus(
        path=str(directory),
        phase=phase,
        action_count=len(actions),
        checked_count=checked_count,
        actions=actions,
        summary=StatusSummary(
            needed=needed,
            satisfied=satisfied,
            pending=pending,
            upgradable=upgradable,
        ),
    )
