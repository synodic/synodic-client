"""Debug commands for inspecting and controlling the Synodic Client.

    synodic-c debug state [--live]
    synodic-c debug actions [--live]
    synodic-c debug action <name> [arg] [--live]

By default commands run headlessly — no running GUI instance is
required.  Pass ``--live`` to route the command over the IPC socket
to a running GUI instance (which has cached data and can control
windows).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Annotated

import typer

from synodic_client.operations.schema import DEBUG_ACTIONS, GUI_ONLY_ACTIONS

debug_app = typer.Typer(
    help='Inspect and control the Synodic Client (headless by default, --live for IPC).',
    add_completion=False,
)


# ---------------------------------------------------------------------------
# IPC path (--live)
# ---------------------------------------------------------------------------


def _send_debug(command: str, *, dev: bool) -> None:
    """Send a debug command to the running instance and print the response."""
    from synodic_client.application.instance import SingleInstance
    from synodic_client.config import set_dev_mode

    set_dev_mode(dev)
    response = SingleInstance.send_debug_command(command)

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        typer.echo(response)
        raise typer.Exit(code=1) from None

    typer.echo(json.dumps(data, indent=2))
    if 'error' in data:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Headless path (default)
# ---------------------------------------------------------------------------


def _headless_dispatch(command: str, *, dev: bool) -> None:
    """Execute a debug command headlessly and print JSON output."""
    from synodic_client.config import set_dev_mode

    set_dev_mode(dev)

    if command == 'state':
        data = _headless_state()
    elif command == 'actions':
        data = {'actions': DEBUG_ACTIONS}
    elif command.startswith('action:'):
        remainder = command[len('action:') :]
        name, _, arg = remainder.partition(':')
        data = _headless_action(name, arg or None)
    else:
        data = {'error': f'unknown command: {command}'}

    typer.echo(json.dumps(data, indent=2, default=str))
    if 'error' in data:
        raise typer.Exit(code=1)


def _headless_state() -> dict:
    """Build a state dict without Qt."""
    from synodic_client.cli.context import get_services
    from synodic_client.config import is_dev_mode

    client, porringer, config = get_services()
    cached_dirs = porringer.cache.list_directories()

    return {
        'app': {
            'version': str(client.version),
            'dev_mode': is_dev_mode(),
            'frozen': getattr(sys, 'frozen', False),
            'platform': sys.platform,
            'headless': True,
        },
        'config': dataclasses.asdict(config),
        'data': {
            'directory_count': len(cached_dirs),
        },
    }


def _headless_action(name: str, arg: str | None) -> dict:
    """Dispatch a single debug action headlessly."""
    if name not in DEBUG_ACTIONS:
        return {'error': f'unknown action: {name}', 'available': list(DEBUG_ACTIONS)}

    if name in GUI_ONLY_ACTIONS:
        return {'error': f'{name} requires --live (targets a running GUI instance)'}

    from synodic_client.cli.context import get_services
    from synodic_client.operations.project import run_project_action

    _, porringer, _ = get_services()
    return run_project_action(name, arg, porringer)


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------


@debug_app.command('state')
def debug_state(
    *,
    dev: Annotated[
        bool,
        typer.Option('--dev', help='Target the dev-mode instance.'),
    ] = False,
    live: Annotated[
        bool,
        typer.Option('--live', help='Route via IPC to a running GUI instance.'),
    ] = False,
) -> None:
    """Dump application domain state as JSON."""
    if live:
        _send_debug('state', dev=dev)
    else:
        _headless_dispatch('state', dev=dev)


@debug_app.command('actions')
def debug_actions(
    *,
    dev: Annotated[
        bool,
        typer.Option('--dev', help='Target the dev-mode instance.'),
    ] = False,
    live: Annotated[
        bool,
        typer.Option('--live', help='Route via IPC to a running GUI instance.'),
    ] = False,
) -> None:
    """List available debug actions."""
    if live:
        _send_debug('actions', dev=dev)
    else:
        _headless_dispatch('actions', dev=dev)


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
    live: Annotated[
        bool,
        typer.Option('--live', help='Route via IPC to a running GUI instance.'),
    ] = False,
) -> None:
    """Trigger a deterministic action on the application."""
    command = f'action:{name}:{arg}' if arg else f'action:{name}'
    if live:
        _send_debug(command, dev=dev)
    else:
        _headless_dispatch(command, dev=dev)
