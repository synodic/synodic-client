"""Shared utilities for tool scripts."""

import subprocess
import sys
import time
from pathlib import Path

# Paths relative to the repository root
REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = REPO_ROOT / 'tool' / 'pyinstaller' / 'synodic.spec'
PACK_DIR = REPO_ROOT / 'dist' / 'synodic'
OUTPUT_DIR = REPO_ROOT / 'Releases'
MAIN_EXE = 'synodic.exe'
ICON_FILE = REPO_ROOT / 'data' / 'icon.ico'
PACK_ID = 'Synodic.SynodicClient'


def run(cmd: list[str], *, description: str) -> None:
    """Run a subprocess command, raising on failure.

    Args:
        cmd: Command and arguments to run.
        description: Human-readable description for error messages.
    """
    print(f'\n{"=" * 60}')
    print(f'  {description}')
    print(f'  > {" ".join(cmd)}')
    print(f'{"=" * 60}\n')

    result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    if result.returncode != 0:
        print(f'\nERROR: {description} failed with exit code {result.returncode}', file=sys.stderr)
        sys.exit(result.returncode)


def kill_running_instances() -> None:
    """Terminate any running synodic.exe processes to release locked files."""
    if sys.platform != 'win32':
        return

    result = subprocess.run(
        ['taskkill', '/F', '/T', '/IM', MAIN_EXE],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print(f'Terminated running {MAIN_EXE} process(es)')
        # Brief delay so the OS fully releases file handles before PyInstaller
        # starts overwriting the same directory.
        time.sleep(1)
    elif 'not found' not in result.stderr.lower():
        print(f'Note: taskkill returned {result.returncode}: {result.stderr.strip()}')


def build() -> None:
    """Run PyInstaller to produce dist/synodic/.

    Kills any running instances first, then invokes PyInstaller with the
    project spec file.
    """
    kill_running_instances()
    run(
        [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(SPEC_FILE)],
        description='Building with PyInstaller',
    )

    if not PACK_DIR.exists():
        print(f'ERROR: Pack directory not found: {PACK_DIR}', file=sys.stderr)
        sys.exit(1)
