"""Register example manifest directories with porringer.

A one-time dev setup helper that discovers all subdirectories under the
repository ``examples/`` folder and registers them with porringer's
directory cache.  Already-registered directories are silently skipped.

Runs automatically as a ``post_install`` hook via PDM.
"""

import logging
import sys
from pathlib import Path

from porringer.api import API, APIParameters
from porringer.schema import LocalConfiguration
from rich.console import Console

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / 'examples'

console = Console(highlight=False)


def main() -> None:
    """Register every example subdirectory with porringer's directory cache."""
    # Silence porringer's internal logging so our output stays clean
    logger = logging.getLogger('synodic_client.setup_dev')
    logging.basicConfig(level=logging.WARNING)

    if not _EXAMPLES_DIR.is_dir():
        console.print(f'  [red]✗[/red] examples/ directory not found at {_EXAMPLES_DIR}')
        sys.exit(1)

    local_config = LocalConfiguration()
    api_params = APIParameters(logger)
    porringer = API(local_config, api_params)

    registered = {d.path.resolve() for d in porringer.cache.list_directories()}
    added = 0
    skipped = 0

    for child in sorted(_EXAMPLES_DIR.iterdir()):
        if not child.is_dir():
            continue

        resolved = child.resolve()
        if resolved in registered:
            skipped += 1
            continue

        try:
            porringer.cache.add_directory(resolved, name=child.name)
            console.print(f'  [green]✓[/green] [bold]{child.name}[/bold] [dim]({resolved})[/dim]')
            added += 1
        except ValueError:
            skipped += 1

    if added:
        noun = 'directory' if added == 1 else 'directories'
        console.print(f'  [green]{added} example {noun} registered[/green]')
    elif skipped:
        noun = 'directory' if skipped == 1 else 'directories'
        console.print(f'  [dim]{skipped} example {noun} already registered[/dim]')


if __name__ == '__main__':
    main()
