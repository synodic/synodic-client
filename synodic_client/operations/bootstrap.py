"""Porringer API initialisation without Qt.

Extracts the service-creation logic from ``qt.py`` so that CLI commands
and tests can obtain a configured ``(Client, API, ResolvedConfig)``
tuple without importing PySide6 or qasync.
"""

from __future__ import annotations

import logging

from porringer.api import API
from porringer.schema import LocalConfiguration

from synodic_client.client import Client
from synodic_client.resolution import resolve_config, resolve_update_config
from synodic_client.schema import ResolvedConfig

logger = logging.getLogger(__name__)


def init_services() -> tuple[Client, API, ResolvedConfig]:
    """Create and configure core services without Qt.

    Returns:
        A ``(Client, porringer API, resolved config)`` tuple ready for
        use by CLI commands or headless operations.
    """
    config = resolve_config()
    client = Client()

    local_config = LocalConfiguration()
    porringer = API(local_config)

    update_config = resolve_update_config(config)
    client.initialize_updater(update_config)

    cached_dirs = porringer.cache.list_directories()

    logger.info(
        'Synodic Client v%s started (channel: %s, source: %s, cached_projects: %d)',
        client.version,
        update_config.channel.name,
        update_config.repo_url,
        len(cached_dirs),
    )

    return client, porringer, config
