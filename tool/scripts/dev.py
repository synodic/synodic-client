"""Dev launch script for Synodic Client.

Runs the application directly from source with ``--dev`` mode enabled,
skipping the PyInstaller build for fast iteration.  Dev mode isolates
configuration, logs, and the single-instance lock from the user-installed
application.

Invoked via ``pdm run dev`` or ``pdm run dev -- --uri <URI>``.
"""

from typing import Annotated

import typer

from synodic_client.application.qt import application

app = typer.Typer(help='Launch Synodic Client from source in dev mode.')


@app.command()
def main(
    *,
    uri: Annotated[
        str | None,
        typer.Option(help='A synodic:// URI to pass as a command-line argument.'),
    ] = None,
) -> None:
    """Launch the application from source with dev-mode isolation.

    Args:
        uri: Optional ``synodic://`` URI to pass as a command-line argument.
    """
    application(uri=uri, dev_mode=True)


if __name__ == '__main__':
    app()
