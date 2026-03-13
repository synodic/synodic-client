"""CLI entry point for the Synodic Client application.

Restructured as a package with resource-verb subcommands:

    synodic-c                    → launch GUI
    synodic-c project list       → list cached projects
    synodic-c tool check         → check for tool updates
    synodic-c config get <key>   → read a config value
    synodic-c update check       → check for self-update
    synodic-c debug state        → dump running instance state (IPC)
"""

from typing import Annotated

import typer

from synodic_client import __version__
from synodic_client.cli.config import config_app
from synodic_client.cli.debug import debug_app
from synodic_client.cli.project import project_app
from synodic_client.cli.tool import tool_app
from synodic_client.cli.update import update_app

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


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    *,
    uri: Annotated[
        str | None,
        typer.Option('--uri', help='A synodic:// URI to process on launch.'),
    ] = None,
    version: Annotated[
        bool | None,
        typer.Option('--version', callback=_version_callback, is_eager=True, help='Show version and exit.'),
    ] = None,
    dev: Annotated[
        bool,
        typer.Option('--dev', help='Run in dev mode with isolated config, logs, and instance lock.'),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option('--debug', help='Enable DEBUG-level file logging for this session.'),
    ] = False,
) -> None:
    """Launch the Synodic Client GUI application."""
    if ctx.invoked_subcommand is not None:
        return

    from synodic_client.application.qt import application  # noqa: PLC0415

    application(uri=uri, dev_mode=dev, debug=debug)


# -- Register sub-typers --------------------------------------------------

app.add_typer(project_app, name='project')
app.add_typer(tool_app, name='tool')
app.add_typer(config_app, name='config')
app.add_typer(update_app, name='update')
app.add_typer(debug_app, name='debug')
