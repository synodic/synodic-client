"""The client type"""

import importlib.metadata
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from importlib.resources import as_file, files
from pathlib import Path
from typing import LiteralString

from packaging.version import Version
from porringer.api import API

from synodic_client.updater import UpdateConfig, UpdateInfo, Updater

logger = logging.getLogger(__name__)


class Client:
    """The client"""

    distribution: LiteralString = 'synodic_client'
    icon: LiteralString = 'icon.png'
    _updater: Updater | None = None

    @property
    def version(self) -> Version:
        """Extracts the version from the installed client.

        Returns:
            The version data
        """
        try:
            return Version(importlib.metadata.version(self.distribution))
        except importlib.metadata.PackageNotFoundError:
            return Version('0.0.0.dev0')

    @property
    def package(self) -> str:
        """Returns the client package

        Returns:
            The package name
        """
        return self.distribution

    @staticmethod
    def resource(resource: str) -> AbstractContextManager[Path]:
        """_summary_

        Args:
            resource: _description_

        Returns:
            A context manager for the expected resource file
        """
        source = files('data').joinpath(resource)
        return as_file(source)

    def initialize_updater(self, porringer_api: API, config: UpdateConfig | None = None) -> Updater:
        """Initialize the updater with the porringer API.

        Args:
            porringer_api: The porringer API instance
            config: Optional update configuration

        Returns:
            The initialized Updater instance
        """
        self._updater = Updater(self.version, porringer_api, config)
        return self._updater

    @property
    def updater(self) -> Updater | None:
        """Get the updater instance.

        Returns:
            The Updater instance if initialized, None otherwise
        """
        return self._updater

    def check_for_update(self) -> UpdateInfo | None:
        """Check for available updates.

        Returns:
            UpdateInfo if updater is initialized, None otherwise
        """
        if self._updater is None:
            logger.warning('Updater not initialized, call initialize_updater first')
            return None

        return self._updater.check_for_update()

    def download_update(self, progress_callback: Callable | None = None) -> Path | None:
        """Download an available update.

        Args:
            progress_callback: Optional callback for progress updates

        Returns:
            Path to downloaded file if successful, None otherwise
        """
        if self._updater is None:
            logger.warning('Updater not initialized')
            return None

        return self._updater.download_update(progress_callback)

    def apply_update(self) -> bool:
        """Apply a downloaded update.

        Returns:
            True if update was applied successfully
        """
        if self._updater is None:
            logger.warning('Updater not initialized')
            return False

        return self._updater.apply_update()

    def restart_for_update(self) -> None:
        """Restart the application to complete the update."""
        if self._updater is None:
            logger.warning('Updater not initialized')
            return

        self._updater.restart_application()
