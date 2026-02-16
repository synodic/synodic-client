"""Centralised application icon.

Loads the icon once from package resources and caches the ``QIcon``
so every caller shares the same instance.
"""

from PySide6.QtGui import QIcon, QPixmap

from synodic_client.client import Client

_cached_icon: QIcon | None = None


def app_icon() -> QIcon:
    """Return the shared application ``QIcon``, loading it on first call.

    The icon is loaded eagerly via ``QPixmap`` so it survives the
    ``importlib.resources`` context-manager cleanup.

    Returns:
        A ``QIcon`` backed by the application logo.
    """
    global _cached_icon  # noqa: PLW0603
    if _cached_icon is None:
        with Client.resource(Client.icon) as icon_path:
            _cached_icon = QIcon(QPixmap(str(icon_path)))
    return _cached_icon
