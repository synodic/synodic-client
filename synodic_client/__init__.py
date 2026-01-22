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

__all__ = [
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
