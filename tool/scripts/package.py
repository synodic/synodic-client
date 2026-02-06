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
import subprocess
import sys
from pathlib import Path

from synodic_client import __version__

# Paths relative to the repository root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_FILE = _REPO_ROOT / 'tool' / 'pyinstaller' / 'synodic.spec'
_PACK_DIR = _REPO_ROOT / 'dist' / 'synodic'
_OUTPUT_DIR = _REPO_ROOT / 'Releases'
_MAIN_EXE = 'synodic.exe'
_PACK_ID = 'Synodic.SynodicClient'


def _run(cmd: list[str], *, description: str) -> None:
    """Run a subprocess command, raising on failure.

    Args:
        cmd: Command and arguments to run.
        description: Human-readable description for error messages.
    """
    print(f'\n{"=" * 60}')
    print(f'  {description}')
    print(f'  > {" ".join(cmd)}')
    print(f'{"=" * 60}\n')

    result = subprocess.run(cmd, cwd=str(_REPO_ROOT), check=False)
    if result.returncode != 0:
        print(f'\nERROR: {description} failed with exit code {result.returncode}', file=sys.stderr)
        sys.exit(result.returncode)


def _kill_running_instances() -> None:
    """Terminate any running synodic.exe processes to release locked files."""
    if sys.platform != 'win32':
        return

    result = subprocess.run(
        ['taskkill', '/F', '/IM', _MAIN_EXE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print(f'Terminated running {_MAIN_EXE} process(es)')
    elif 'not found' not in result.stderr.lower():
        print(f'Note: taskkill returned {result.returncode}: {result.stderr.strip()}')


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

    # Step 0: Kill any running instances to release locked files
    _kill_running_instances()

    # Step 1: PyInstaller
    if not args.skip_pyinstaller:
        _run(
            [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(_SPEC_FILE)],
            description='Building with PyInstaller',
        )
    else:
        print('Skipping PyInstaller (--skip-pyinstaller)')

    if not _PACK_DIR.exists():
        print(f'ERROR: Pack directory not found: {_PACK_DIR}', file=sys.stderr)
        print('Run without --skip-pyinstaller first.', file=sys.stderr)
        sys.exit(1)

    # Step 1b: Write portable config for dev builds
    if args.local_source:
        portable_config = {
            'update_source': str(Path(args.local_source).resolve()),
            'update_channel': args.channel,
        }
        config_path = _PACK_DIR / 'config.json'
        config_path.write_text(json.dumps(portable_config, indent=2), encoding='utf-8')
        print(f'Wrote portable config to {config_path}')

    # Step 2: vpk pack
    vpk_cmd = shutil.which('vpk')
    if vpk_cmd is None:
        print('ERROR: vpk not found. Install with: dotnet tool install -g vpk', file=sys.stderr)
        sys.exit(1)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _run(
        [
            vpk_cmd,
            'pack',
            '--packId',
            _PACK_ID,
            '--packVersion',
            __version__,
            '--packDir',
            str(_PACK_DIR),
            '--mainExe',
            _MAIN_EXE,
            '--channel',
            args.channel,
            '-o',
            str(_OUTPUT_DIR),
        ],
        description='Packing with Velopack',
    )

    # Step 3: Optionally copy to a local source directory
    if args.local_source:
        local_path = Path(args.local_source)
        local_path.mkdir(parents=True, exist_ok=True)

        _run(
            [
                vpk_cmd,
                'upload',
                'local',
                '--path',
                str(local_path),
                '-o',
                str(_OUTPUT_DIR),
                '--channel',
                args.channel,
            ],
            description=f'Uploading to local source: {local_path}',
        )

    print(f'\nDone! Releases written to: {_OUTPUT_DIR}')
    if args.local_source:
        print(f'Local update source: {args.local_source}')


if __name__ == '__main__':
    main()
