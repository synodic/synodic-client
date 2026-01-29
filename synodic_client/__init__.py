"""The `synodic_client` package provides the core functionality for the Synodic Client application."""

import importlib.metadata

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

try:
    __version__ = importlib.metadata.version('synodic_client')
except importlib.metadata.PackageNotFoundError:
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
