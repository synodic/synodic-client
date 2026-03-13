"""Self-update commands.

synodic-c update check
synodic-c update download
synodic-c update apply
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from synodic_client.cli.output import render

update_app = typer.Typer(
    help='Check, download, and apply synodic-client self-updates.',
    add_completion=False,
)


@update_app.command('check')
def update_check(
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Check whether a newer version of synodic-client is available."""
    from synodic_client.cli.context import get_services  # noqa: PLC0415
    from synodic_client.operations.update import check_self_update  # noqa: PLC0415

    client, _, _ = get_services()
    result = asyncio.run(check_self_update(client))
    render(result, as_json=json_output)


@update_app.command('download')
def update_download(
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Download a self-update."""
    from synodic_client.cli.context import get_services  # noqa: PLC0415
    from synodic_client.operations.update import download_self_update  # noqa: PLC0415

    client, _, _ = get_services()

    def _progress(pct: int) -> None:
        typer.echo(f'\rDownloading… {pct}%', nl=False)

    result = asyncio.run(download_self_update(client, on_progress=None if json_output else _progress))
    if not json_output:
        typer.echo()  # newline after progress
    render(result, as_json=json_output)


@update_app.command('apply')
def update_apply(
    *,
    no_restart: Annotated[
        bool,
        typer.Option('--no-restart', help='Apply without restarting.'),
    ] = False,
    silent: Annotated[
        bool,
        typer.Option('--silent', help='Suppress the Velopack splash window.'),
    ] = False,
) -> None:
    """Apply a downloaded self-update."""
    from synodic_client.cli.context import get_services  # noqa: PLC0415
    from synodic_client.operations.update import apply_self_update  # noqa: PLC0415

    client, _, _ = get_services()
    apply_self_update(client, restart=not no_restart, silent=silent)
    typer.echo('Update applied.')
