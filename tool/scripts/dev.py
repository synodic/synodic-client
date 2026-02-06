"""Dev build-and-run script for Synodic Client.

Builds the application with PyInstaller and launches the resulting EXE.
Skips Velopack packaging entirely for fast iteration.

Invoked via ``pdm run dev``.
"""

import subprocess
import sys

from tool.scripts.common import MAIN_EXE, PACK_DIR, REPO_ROOT, build


def main() -> None:
    """Build with PyInstaller and launch the EXE."""
    build()

    exe_path = PACK_DIR / MAIN_EXE
    if not exe_path.exists():
        print(f'ERROR: EXE not found: {exe_path}', file=sys.stderr)
        sys.exit(1)

    print(f'\nLaunching {exe_path} ...\n')
    subprocess.Popen([str(exe_path)], cwd=str(REPO_ROOT))


if __name__ == '__main__':
    main()
