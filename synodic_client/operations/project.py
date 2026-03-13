"""Project directory operations.

Pure functions for listing, adding, removing, and querying status of
cached project directories.  No Qt, no signals — just porringer API
calls in → typed results out.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from synodic_client.operations.schema import ProjectInfo

if TYPE_CHECKING:
    from porringer.api import API


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
