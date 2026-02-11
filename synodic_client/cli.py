"""CLI entry point for the Synodic Client application."""

from typing import Annotated

import typer

from synodic_client import __version__
from synodic_client.application.qt import application

app = typer.Typer(
    name='synodic-c',
    help='Synodic Client — a system tray frontend for porringer.',
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the version and exit."""
    if value:
        typer.echo(f'synodic-client {__version__}')
        raise typer.Exit


@app.command()
def main(
    uri: Annotated[
        str | None,
        typer.Argument(help='A synodic:// URI to process on launch.'),
    ] = None,
    *,
    version: Annotated[
        bool | None,
        typer.Option('--version', callback=_version_callback, is_eager=True, help='Show version and exit.'),
    ] = None,
) -> None:
    """Launch the Synodic Client GUI application."""
    application(uri=uri)
