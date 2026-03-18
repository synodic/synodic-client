"""Shared output formatting for CLI commands.

Provides human-readable table output by default and machine-readable
JSON when ``--json`` is requested.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import typer


def render(data: Any, *, as_json: bool = False) -> None:
    """Render *data* to stdout.

    Args:
        data: A dataclass, list of dataclasses, dict, or primitive.
        as_json: If ``True``, emit JSON; otherwise human-readable text.
    """
    if as_json:
        typer.echo(json.dumps(_serialise(data), indent=2))
    elif isinstance(data, list):
        for item in data:
            _print_record(item)
    elif dataclasses.is_dataclass(data) and not isinstance(data, type):
        _print_record(data)
    elif isinstance(data, dict):
        for key, value in data.items():
            typer.echo(f'{key}: {value}')
    else:
        typer.echo(str(data))


def _serialise(obj: Any) -> Any:
    """Recursively convert dataclass instances to dicts."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialise(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return sorted(_serialise(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_serialise(item) for item in obj]
    return obj


def _print_record(item: Any) -> None:
    """Print a single record (dataclass or dict) as key: value lines."""
    if dataclasses.is_dataclass(item) and not isinstance(item, type):
        fields = dataclasses.asdict(item)
    elif isinstance(item, dict):
        fields = item
    else:
        typer.echo(str(item))
        return

    for key, value in fields.items():
        typer.echo(f'  {key}: {value}')
    typer.echo()
