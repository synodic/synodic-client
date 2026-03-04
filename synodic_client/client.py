"""The client type"""

import importlib.metadata
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from importlib.resources import as_file, files
from pathlib import Path
from typing import LiteralString

from packaging.version import Version

from synodic_client.schema import UpdateConfig, UpdateInfo
from synodic_client.updater import Updater

logger = logging.getLogger(__name__)


class Client:
    """The client"""

    distribution: LiteralString = 'synodic_client'
    icon: LiteralString = 'icon.png'
    icon_ico: LiteralString = 'icon.ico'
    _updater: Updater | None = None

    @property
    def version(self) -> Version:
        """Return the best-known application version.

        When a Velopack-installed updater is available the authoritative
        version comes from the native binary manifest.  Otherwise, the
        Python package metadata version (``importlib.metadata``) is used.

        Returns:
            The resolved version.
        """
        if self._updater is not None:
            try:
                if self._updater.is_installed:
                    return self._updater.current_version
            except Exception:
                logger.debug('Failed to query Velopack version, falling back', exc_info=True)
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

    def apply_update_on_exit(self, restart: bool = True, *, silent: bool = False) -> None:
        """Schedule the update to apply when the application exits.

        Args:
            restart: Whether to restart after applying.
            silent: When ``True``, suppress the Velopack splash window.
        """
        if self._updater is None:
            logger.warning('Updater not initialized')
            return

        self._updater.apply_update_on_exit(restart=restart, silent=silent)
