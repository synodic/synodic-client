"""Manifest install command."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from porringer.api import API
    from porringer.schema import SetupActionResult, SyncStrategy


def install(
    manifest: Annotated[
        str,
        typer.Argument(help='Path or URL to a porringer manifest file.'),
    ],
    *,
    project_dir: Annotated[
        Path | None,
        typer.Option('--project-dir', help='Project directory override.'),
    ] = None,
    strategy: Annotated[
        str,
        typer.Option('--strategy', help='Sync strategy: MINIMAL, LATEST, or EXACT.'),
    ] = 'MINIMAL',
    prerelease: Annotated[
        list[str] | None,
        typer.Option('--prerelease', help='Package names to allow prerelease versions.'),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Output results as JSON.'),
    ] = False,
) -> None:
    """Install packages and run commands from a porringer manifest."""
    from synodic_client.cli.context import get_services
    from synodic_client.cli.output import render

    _, porringer, _ = get_services()

    # Resolve strategy enum
    from porringer.schema import SyncStrategy

    try:
        sync_strategy = SyncStrategy[strategy.upper()]
    except KeyError:
        typer.echo(f'Unknown strategy: {strategy!r}. Use MINIMAL, LATEST, or EXACT.', err=True)
        raise typer.Exit(code=1) from None

    prerelease_packages = set(prerelease) if prerelease else None

    try:
        result = asyncio.run(
            _run(
                porringer,
                manifest,
                project_directory=project_dir,
                strategy=sync_strategy,
                prerelease_packages=prerelease_packages,
                json_output=json_output,
            ),
        )
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    render(result, as_json=json_output)


async def _process_install_stream(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None,
    strategy: SyncStrategy,
    prerelease_packages: set[str] | None,
    json_output: bool,
) -> tuple[list[SetupActionResult], int]:
    """Run the install stream and collect results."""
    from porringer.schema import ActionCompletedEvent, ActionStartedEvent, ManifestLoadedEvent

    from synodic_client.operations.install import collect_install

    action_count = 0

    def _on_progress(stage: str, event: object) -> None:
        nonlocal action_count
        if stage == 'manifest_loaded' and isinstance(event, ManifestLoadedEvent):
            action_count = len(event.manifest.actions)
            if not json_output:
                typer.echo(f'Manifest loaded: {action_count} action(s)')
        elif stage == 'action_started' and isinstance(event, ActionStartedEvent):
            if not json_output:
                typer.echo(f'  Starting: {event.action.description}')
        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent):
            if not json_output:
                status = 'OK' if event.result.success else 'FAILED'
                if event.result.skipped:
                    status = 'SKIPPED'
                typer.echo(f'  {status}: {event.action.description}')

    results = await collect_install(
        porringer,
        manifest_path,
        project_directory=project_directory,
        strategy=strategy,
        prerelease_packages=prerelease_packages,
        on_progress=_on_progress,
    )

    return list(results.results), action_count


async def _process_post_sync_stream(
    porringer: API,
    manifest_path: Path,
    *,
    project_directory: Path | None,
    json_output: bool,
) -> list[SetupActionResult]:
    """Run the post-sync stream and collect results."""
    from porringer.schema import ActionCompletedEvent, ActionStartedEvent

    from synodic_client.operations.install import collect_post_sync

    if not json_output:
        typer.echo('Running post-sync commands...')

    def _on_progress(stage: str, event: object) -> None:
        if stage == 'action_started' and isinstance(event, ActionStartedEvent):
            if not json_output:
                typer.echo(f'  Running: {event.action.description}')
        elif stage == 'action_completed' and isinstance(event, ActionCompletedEvent) and not json_output:
            status = 'OK' if event.result.success else 'FAILED'
            typer.echo(f'  {status}: {event.action.description}')

    results = await collect_post_sync(
        porringer,
        manifest_path,
        project_directory=project_directory,
        on_progress=_on_progress,
    )

    return list(results.results)


async def _run(
    porringer: API,
    manifest_url: str,
    *,
    project_directory: Path | None,
    strategy: SyncStrategy,
    prerelease_packages: set[str] | None,
    json_output: bool,
) -> dict[str, object]:
    """Execute the install pipeline and return a summary dict."""
    from synodic_client.operations.install import resolve_manifest_path
    from synodic_client.operations.schema import format_install_summary

    manifest_path, temp_dir = await resolve_manifest_path(manifest_url)

    try:
        install_results, action_count = await _process_install_stream(
            porringer,
            manifest_path,
            project_directory=project_directory,
            strategy=strategy,
            prerelease_packages=prerelease_packages,
            json_output=json_output,
        )

        # Post-sync phase — execute_post_sync no-ops when the manifest
        # has no post_sync block, so we always call it.
        post_sync_results = await _process_post_sync_stream(
            porringer,
            manifest_path,
            project_directory=project_directory,
            json_output=json_output,
        )

        summary = format_install_summary(
            install_results=install_results or None,
            post_sync_results=post_sync_results or None,
        )

        if not json_output:
            typer.echo(summary)

        return {
            'manifest': manifest_url,
            'action_count': action_count,
            'install_succeeded': sum(1 for r in install_results if r.success and not r.skipped),
            'install_skipped': sum(1 for r in install_results if r.skipped),
            'install_failed': sum(1 for r in install_results if not r.success),
            'post_sync_succeeded': sum(1 for r in post_sync_results if r.success),
            'post_sync_failed': sum(1 for r in post_sync_results if not r.success),
            'summary': summary,
        }
    finally:
        if temp_dir:
            from synodic_client.application.uri import safe_rmtree

            safe_rmtree(temp_dir)
