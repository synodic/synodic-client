"""Packaging script for Synodic Client.

Orchestrates PyInstaller + Velopack ``vpk pack`` to produce a complete
release from source.  Invoked via ``pdm run package``.

Usage examples:
    pdm run package
    pdm run package -- --channel stable
    pdm run package -- --local-source D:/releases
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from synodic_client import __version__
from tool.scripts.common import MAIN_EXE, OUTPUT_DIR, PACK_DIR, PACK_ID, build, kill_running_instances, run


def main() -> None:
    """Entry point for the packaging script."""
    parser = argparse.ArgumentParser(description='Package Synodic Client with PyInstaller and Velopack.')
    parser.add_argument(
        '--channel',
        default='dev',
        choices=['dev', 'stable'],
        help='Velopack release channel (default: dev)',
    )
    parser.add_argument(
        '--local-source',
        type=str,
        default=None,
        help='Path to copy releases to (for local dev update testing)',
    )
    parser.add_argument(
        '--skip-pyinstaller',
        action='store_true',
        help='Skip the PyInstaller step (use existing dist/synodic)',
    )

    args = parser.parse_args()
    print(f'Packaging Synodic Client v{__version__} (channel: {args.channel})')

    # Step 1: PyInstaller
    if not args.skip_pyinstaller:
        build()
    else:
        kill_running_instances()
        print('Skipping PyInstaller (--skip-pyinstaller)')
        if not PACK_DIR.exists():
            print(f'ERROR: Pack directory not found: {PACK_DIR}', file=sys.stderr)
            print('Run without --skip-pyinstaller first.', file=sys.stderr)
            sys.exit(1)

    # Step 1b: Write portable config for dev builds
    if args.local_source:
        portable_config = {
            'update_source': str(Path(args.local_source).resolve()),
            'update_channel': args.channel,
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
            __version__,
            '--packDir',
            str(PACK_DIR),
            '--mainExe',
            MAIN_EXE,
            '--channel',
            args.channel,
            '-o',
            str(OUTPUT_DIR),
        ],
        description='Packing with Velopack',
    )

    # Step 3: Optionally copy to a local source directory
    if args.local_source:
        local_path = Path(args.local_source)
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
                args.channel,
            ],
            description=f'Uploading to local source: {local_path}',
        )

    print(f'\nDone! Releases written to: {OUTPUT_DIR}')
    if args.local_source:
        print(f'Local update source: {args.local_source}')


if __name__ == '__main__':
    main()
