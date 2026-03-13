"""Project directory commands.

synodic-c project list
synodic-c project add <path>
synodic-c project remove <path>
"""

from __future__ import annotations

from typing import Annotated

import typer

from synodic_client.cli.output import render

project_app = typer.Typer(
    help='Manage cached project directories.',
    add_completion=False,
)


@project_app.command('list')
def project_list(
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """List all cached project directories."""
    from synodic_client.cli.context import get_services
    from synodic_client.operations.project import list_projects

    _, porringer, _ = get_services()
    projects = list_projects(porringer)
    render(projects, as_json=json_output)


@project_app.command('add')
def project_add(
    path: Annotated[
        str,
        typer.Argument(help='Filesystem path of the directory to add.'),
    ],
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Add a directory to the porringer project cache."""
    from synodic_client.cli.context import get_services
    from synodic_client.operations.project import add_project

    _, porringer, _ = get_services()
    try:
        info = add_project(porringer, path)
    except (NotADirectoryError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    render(info, as_json=json_output)


@project_app.command('remove')
def project_remove(
    path: Annotated[
        str,
        typer.Argument(help='Filesystem path of the directory to remove.'),
    ],
) -> None:
    """Remove a directory from the porringer project cache."""
    from synodic_client.cli.context import get_services
    from synodic_client.operations.project import remove_project

    _, porringer, _ = get_services()
    remove_project(porringer, path)
    typer.echo(f'Removed: {path}')
