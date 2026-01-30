"""The client type"""

import importlib.metadata
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from importlib.resources import as_file, files
from pathlib import Path
from typing import LiteralString

from packaging.version import Version

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

    def initialize_updater(self, config: UpdateConfig | None = None) -> Updater:
        """Initialize the updater.

        Args:
            config: Optional update configuration

        Returns:
            The initialized Updater instance
        """
        self._updater = Updater(self.version, config)
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

    def download_update(self, progress_callback: Callable[[int], None] | None = None) -> bool:
        """Download an available update.

        Args:
            progress_callback: Optional callback for progress updates (0-100)

        Returns:
            True if download succeeded, False otherwise
        """
        if self._updater is None:
            logger.warning('Updater not initialized')
            return False

        return self._updater.download_update(progress_callback)

    def apply_update_and_restart(self) -> None:
        """Apply a downloaded update and restart the application.

        This method will not return - it exits and relaunches the app.
        """
        if self._updater is None:
            logger.warning('Updater not initialized')
            return

        self._updater.apply_update_and_restart()

    def apply_update_on_exit(self, restart: bool = True) -> None:
        """Schedule the update to apply when the application exits.

        Args:
            restart: Whether to restart after applying
        """
        if self._updater is None:
            logger.warning('Updater not initialized')
            return

        self._updater.apply_update_on_exit(restart=restart)
