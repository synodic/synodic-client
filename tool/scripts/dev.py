"""Dev build-and-run script for Synodic Client.

Builds the application with PyInstaller and launches the resulting EXE.
Skips Velopack packaging entirely for fast iteration.

Invoked via ``pdm run dev`` or ``pdm run dev-uri``.
"""

import subprocess
import sys

from tool.scripts.common import MAIN_EXE, PACK_DIR, REPO_ROOT, build

_DEFAULT_URI = (
    'synodic://install?manifest=https://raw.githubusercontent.com/synodic'
    '/porringer/development/examples/python-dev/porringer.json'
)


def main(*, uri: str | None = None) -> None:
    """Build with PyInstaller and launch the EXE.

    Args:
        uri: Optional ``synodic://`` URI to pass as a command-line argument.
    """
    build()

    exe_path = PACK_DIR / MAIN_EXE
    if not exe_path.exists():
        print(f'ERROR: EXE not found: {exe_path}', file=sys.stderr)
        sys.exit(1)

    cmd = [str(exe_path)]
    if uri:
        cmd.append(uri)
        print(f'\nLaunching {exe_path} with URI:\n  {uri}\n')
    else:
        print(f'\nLaunching {exe_path} ...\n')

    subprocess.Popen(cmd, cwd=str(REPO_ROOT))


def main_uri() -> None:
    """Build and launch with the default install URI."""
    main(uri=_DEFAULT_URI)


if __name__ == '__main__':
    main()
