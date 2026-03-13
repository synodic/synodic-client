"""Debug IPC commands for inspecting a running GUI instance.

    synodic-c debug state
    synodic-c debug actions
    synodic-c debug action <name> [arg]

These commands send commands over the local-socket IPC channel and
require a running Synodic Client GUI instance.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

debug_app = typer.Typer(
    help='Inspect and control the running Synodic Client instance.',
    add_completion=False,
)


def _send_debug(command: str, *, dev: bool) -> None:
    """Send a debug command to the running instance and print the response."""
    from synodic_client.application.instance import SingleInstance  # noqa: PLC0415
    from synodic_client.config import set_dev_mode  # noqa: PLC0415

    set_dev_mode(dev)
    response = SingleInstance.send_debug_command(command)

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        typer.echo(response)
        raise typer.Exit(code=1)  # noqa: B904

    typer.echo(json.dumps(data, indent=2))
    if 'error' in data:
        raise typer.Exit(code=1)


@debug_app.command('state')
def debug_state(
    *,
    dev: Annotated[
        bool,
        typer.Option('--dev', help='Target the dev-mode instance.'),
    ] = False,
) -> None:
    """Dump the running application's domain state as JSON."""
    _send_debug('state', dev=dev)


@debug_app.command('actions')
def debug_actions(
    *,
    dev: Annotated[
        bool,
        typer.Option('--dev', help='Target the dev-mode instance.'),
    ] = False,
) -> None:
    """List available debug actions."""
    _send_debug('actions', dev=dev)


@debug_app.command('action')
def debug_action(
    name: Annotated[
        str,
        typer.Argument(help='The action to trigger (e.g. check_update, show_main).'),
    ],
    arg: Annotated[
        str | None,
        typer.Argument(help='Optional argument for the action (e.g. a project path).'),
    ] = None,
    *,
    dev: Annotated[
        bool,
        typer.Option('--dev', help='Target the dev-mode instance.'),
    ] = False,
) -> None:
    """Trigger a deterministic action on the running instance."""
    command = f'action:{name}:{arg}' if arg else f'action:{name}'
    _send_debug(command, dev=dev)
