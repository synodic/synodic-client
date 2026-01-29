"""The `synodic_client` package provides the core functionality for the Synodic Client application."""

from synodic_client.client import Client
from synodic_client.schema import (
    UpdateChannel,
    UpdateCheckResult,
    UpdateProgress,
    UpdateStatus,
    VersionInformation,
)
from synodic_client.updater import (
    UpdateConfig,
    UpdateInfo,
    Updater,
    UpdateState,
)

# Version is generated at build time by pdm-backend, not committed to repo
try:
    from synodic_client._version import __version__
except ImportError:
    __version__ = '0.0.0.dev0'

__all__ = [
    '__version__',
    'Client',
    'UpdateChannel',
    'UpdateCheckResult',
    'UpdateConfig',
    'UpdateInfo',
    'UpdateProgress',
    'UpdateState',
    'UpdateStatus',
    'Updater',
    'VersionInformation',
]
