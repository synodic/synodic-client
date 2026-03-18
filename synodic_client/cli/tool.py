"""Tool and package management commands.

synodic-c tool check
synodic-c tool update [plugin] [--package <name>]
synodic-c tool remove <plugin> <package>
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from synodic_client.cli.output import render

tool_app = typer.Typer(
    help='Inspect and manage installed tools and packages.',
    add_completion=False,
)


@tool_app.command('check')
def tool_check(
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Check for available tool/package updates."""
    from synodic_client.cli.context import get_services
    from synodic_client.operations.tool import check_tool_updates

    _, porringer, _ = get_services()
    available = asyncio.run(check_tool_updates(porringer))
    render(available, as_json=json_output)


@tool_app.command('update')
def tool_update(
    plugin: Annotated[
        str,
        typer.Argument(help='Installer plugin name to update.'),
    ],
    *,
    package: Annotated[
        str | None,
        typer.Option('--package', help='Update a specific package only.'),
    ] = None,
    runtime_tag: Annotated[
        str | None,
        typer.Option('--runtime', help='Scope to a runtime tag.'),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Update a tool plugin or a specific package within it."""
    from synodic_client.cli.context import get_services
    from synodic_client.operations.tool import update_tool as _update_tool

    _, porringer, _ = get_services()
    result = asyncio.run(_update_tool(porringer, plugin, package, runtime_tag=runtime_tag))

    from synodic_client.operations.tool import log_update_result

    log_update_result(result)
    render(result, as_json=json_output)


@tool_app.command('remove')
def tool_remove(
    plugin: Annotated[
        str,
        typer.Argument(help='Installer plugin name.'),
    ],
    package: Annotated[
        str,
        typer.Argument(help='Package name to remove.'),
    ],
    *,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output as JSON.'),
    ] = False,
) -> None:
    """Remove a single installed package."""
    from synodic_client.cli.context import get_services
    from synodic_client.operations.tool import remove_package as _remove_package

    _, porringer, _ = get_services()
    success = asyncio.run(_remove_package(porringer, plugin, package))
    render({'success': success, 'plugin': plugin, 'package': package}, as_json=json_output)
