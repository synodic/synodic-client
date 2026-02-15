"""Register example manifest directories with porringer.

A one-time dev setup helper that discovers all subdirectories under the
repository ``examples/`` folder and registers them with porringer's
directory cache.  Already-registered directories are silently skipped.

Runs automatically as a ``post_install`` hook via PDM.
"""

import logging
import sys
from pathlib import Path

from porringer.api import API
from porringer.schema import LocalConfiguration
from rich.console import Console

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / 'examples'

console = Console(highlight=False)


def main() -> None:
    """Register every example subdirectory with porringer's directory cache."""
    # Silence porringer's internal logging so our output stays clean
    logging.basicConfig(level=logging.WARNING)

    if not _EXAMPLES_DIR.is_dir():
        console.print(f'  [red]x[/red] examples/ directory not found at {_EXAMPLES_DIR}')
        sys.exit(1)

    local_config = LocalConfiguration()
    porringer = API(local_config)

    cached = porringer.cache.list_directories()
    registered = {d.path.resolve(): d for d in cached}
    example_dirs = {child.resolve() for child in _EXAMPLES_DIR.iterdir() if child.is_dir()}

    # --- Prune stale entries whose directories no longer exist under examples/ ---
    pruned = 0
    for resolved, entry in registered.items():
        if _EXAMPLES_DIR.resolve() in resolved.parents and resolved not in example_dirs:
            try:
                porringer.cache.remove_directory(entry.path)
                name = entry.name or resolved.name
                console.print(f'  [yellow]-[/yellow] [bold]{name}[/bold] [dim](removed)[/dim]')
                pruned += 1
            except ValueError:
                pass

    # --- Register new example directories ---
    added = 0
    skipped = 0

    for child in sorted(example_dirs):
        if child in registered:
            skipped += 1
            continue

        try:
            porringer.cache.add_directory(child, name=child.name)
            console.print(f'  [green]+[/green] [bold]{child.name}[/bold] [dim]({child})[/dim]')
            added += 1
        except ValueError:
            skipped += 1

    if pruned:
        noun = 'entry' if pruned == 1 else 'entries'
        console.print(f'  [yellow]{pruned} stale {noun} removed[/yellow]')
    if added:
        noun = 'directory' if added == 1 else 'directories'
        console.print(f'  [green]{added} example {noun} registered[/green]')
    elif skipped and not pruned:
        noun = 'directory' if skipped == 1 else 'directories'
        console.print(f'  [dim]{skipped} example {noun} already registered[/dim]')


if __name__ == '__main__':
    main()
