"""Packaging script for Synodic Client.

Orchestrates PyInstaller + Velopack ``vpk pack`` to produce a complete
release from source.  Invoked via ``pdm run package``.

Usage examples:
    pdm run package
    pdm run package -- --channel stable
    pdm run package -- --local-source D:/releases
"""

import json
import shutil
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from synodic_client import __version__
from synodic_client.schema import platform_suffix
from synodic_client.updater import pep440_to_semver
from tool.scripts.common import ICON_FILE, MAIN_EXE, OUTPUT_DIR, PACK_DIR, PACK_ID, build, kill_running_instances, run

app = typer.Typer(help='Package Synodic Client with PyInstaller and Velopack.')


class Channel(StrEnum):
    """Velopack release channels."""

    dev = 'dev'
    stable = 'stable'


@app.command()
def main(
    *,
    channel: Annotated[Channel, typer.Option(help='Velopack release channel.')] = Channel.dev,
    local_source: Annotated[
        str | None, typer.Option(help='Path to copy releases to (for local dev update testing).')
    ] = None,
    skip_pyinstaller: Annotated[
        bool, typer.Option('--skip-pyinstaller', help='Skip the PyInstaller step (use existing dist/synodic).')
    ] = False,
) -> None:
    """Entry point for the packaging script."""
    velopack_channel = f'{channel.value}-{platform_suffix()}'
    pack_version = pep440_to_semver(__version__)
    print(f'Packaging Synodic Client v{__version__} (pack version: {pack_version}, channel: {velopack_channel})')

    # Step 1: PyInstaller
    if not skip_pyinstaller:
        build()
    else:
        kill_running_instances()
        print('Skipping PyInstaller (--skip-pyinstaller)')
        if not PACK_DIR.exists():
            print(f'ERROR: Pack directory not found: {PACK_DIR}', file=sys.stderr)
            print('Run without --skip-pyinstaller first.', file=sys.stderr)
            sys.exit(1)

    # Step 1b: Write portable config for dev builds
    if local_source:
        portable_config = {
            'update_source': str(Path(local_source).resolve()),
            'update_channel': channel.value,
        }
        config_path = PACK_DIR / 'config.json'
        config_path.write_text(json.dumps(portable_config, indent=2), encoding='utf-8')
        print(f'Wrote portable config to {config_path}')

    # Step 2: vpk pack
    vpk_cmd = shutil.which('vpk')
    if vpk_cmd is None:
        print('ERROR: vpk not found. Install with: dotnet tool install -g vpk', file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run(
        [
            vpk_cmd,
            'pack',
            '--packId',
            PACK_ID,
            '--packVersion',
            pack_version,
            '--packDir',
            str(PACK_DIR),
            '--mainExe',
            MAIN_EXE,
            '--icon',
            str(ICON_FILE),
            '--channel',
            velopack_channel,
            '--shortcutLocations',
            'StartMenuRoot',
            '-o',
            str(OUTPUT_DIR),
        ],
        description='Packing with Velopack',
    )

    # Step 3: Optionally copy to a local source directory
    if local_source:
        local_path = Path(local_source)
        local_path.mkdir(parents=True, exist_ok=True)

        run(
            [
                vpk_cmd,
                'upload',
                'local',
                '--path',
                str(local_path),
                '-o',
                str(OUTPUT_DIR),
                '--channel',
                velopack_channel,
            ],
            description=f'Uploading to local source: {local_path}',
        )

    print(f'\nDone! Releases written to: {OUTPUT_DIR}')
    if local_source:
        print(f'Local update source: {local_source}')


if __name__ == '__main__':
    main()
