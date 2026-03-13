"""Configuration commands.

synodic-c config get <key>
synodic-c config set <key> <value>
synodic-c config list
"""

from __future__ import annotations

from typing import Annotated

import typer

from synodic_client.cli.output import render

config_app = typer.Typer(
    help='Read and write Synodic Client configuration.',
    add_completion=False,
)


@config_app.command('get')
def config_get(
    key: Annotated[
        str,
        typer.Argument(help='Configuration key to read.'),
    ],
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Print the current value of a config key."""
    import dataclasses

    from synodic_client.operations.config import get_config

    config = get_config()
    fields = {f.name for f in dataclasses.fields(config)}
    if key not in fields:
        typer.echo(f'Unknown key: {key!r}. Valid keys: {sorted(fields)}', err=True)
        raise typer.Exit(code=1)

    value = getattr(config, key)
    render({key: value}, as_json=json_output)


@config_app.command('set')
def config_set(
    key: Annotated[
        str,
        typer.Argument(help='Configuration key to update.'),
    ],
    value: Annotated[
        str,
        typer.Argument(help='New value for the key.'),
    ],
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Update a single configuration key."""
    from synodic_client.operations.config import set_config

    try:
        updated = set_config(key, value)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    render(updated, as_json=json_output)


@config_app.command('list')
def config_list(
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """List all configuration keys and their current values."""
    from synodic_client.operations.config import list_config_keys

    keys = list_config_keys()
    if json_output:
        render(keys, as_json=True)
    else:
        for name, info in keys.items():
            typer.echo(f'{name} = {info.current_value!r}  ({info.type_hint})')
