"""The client type"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING, LiteralString

from packaging.version import Version

from synodic_client.updater import UpdateConfig, UpdateInfo, Updater

if TYPE_CHECKING:
    from porringer.api import API

logger = logging.getLogger(__name__)


class Client:
    """The client"""

    distribution: LiteralString = 'synodic_client'
    _updater: Updater | None = None

    @property
    def version(self) -> Version:
        """Extracts the version from the installed client.

        Priority:
        1. importlib.metadata
        2. _version.py

        Returns:
            The version data
        """
        try:
            return Version(importlib.metadata.version(self.distribution))
        except importlib.metadata.PackageNotFoundError:
            # Frozen executable or missing metadata - use bundled version from SCM
            # Import lazily since _version.py is generated at build time and not committed
            try:
                from synodic_client._version import __version__ as bundled_version  # noqa: PLC0415

                return Version(bundled_version)
            except ImportError:
                # Development without build - no version file exists
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
