"""Centralised application icon.

Loads the icon once from package resources and caches the ``QIcon``
so every caller shares the same instance.
"""

import functools

from PySide6.QtGui import QIcon, QPixmap

from synodic_client.client import Client


@functools.cache
def app_icon() -> QIcon:
    """Return the shared application ``QIcon``, loading it on first call.

    The icon is loaded eagerly via ``QPixmap`` so it survives the
    ``importlib.resources`` context-manager cleanup.

    Returns:
        A ``QIcon`` backed by the application logo.
    """
    with Client.resource(Client.icon) as icon_path:
        return QIcon(QPixmap(str(icon_path)))
