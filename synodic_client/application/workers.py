"""Background worker threads for the Synodic Client application.

Each worker wraps an off-main-thread operation and communicates results
back via Qt signals so that callers remain responsive.
"""

import asyncio
import logging
from pathlib import Path

from porringer.api import API
from porringer.schema import SetupParameters, SyncStrategy
from PySide6.QtCore import QThread, Signal

from synodic_client.client import Client

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """Worker for checking updates in a background thread."""

    finished = Signal(object)  # UpdateInfo
    error = Signal(str)

    def __init__(self, client: Client) -> None:
        """Initialize the worker."""
        super().__init__()
        self._client = client

    def run(self) -> None:
        """Run the update check."""
        try:
            result = self._client.check_for_update()
            self.finished.emit(result)
        except Exception as e:
            logger.exception('Update check failed')
            self.error.emit(str(e))


class UpdateDownloadWorker(QThread):
    """Worker for downloading updates in a background thread."""

    finished = Signal(bool)  # success status
    progress = Signal(int)  # percentage (0-100)
    error = Signal(str)

    def __init__(self, client: Client) -> None:
        """Initialize the worker."""
        super().__init__()
        self._client = client

    def run(self) -> None:
        """Run the update download."""
        try:

            def progress_callback(percentage: int) -> None:
                self.progress.emit(percentage)

            success = self._client.download_update(progress_callback)
            self.finished.emit(success)
        except Exception as e:
            logger.exception('Update download failed')
            self.error.emit(str(e))


class ToolUpdateWorker(QThread):
    """Worker for re-syncing manifest-declared tools in a background thread."""

    finished = Signal(int)  # number of manifests processed
    error = Signal(str)

    def __init__(self, porringer: API, plugins: list[str] | None = None) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            plugins: Optional include-list of plugin names.  When set, only
                actions handled by these plugins are executed.  ``None``
                means all plugins.
        """
        super().__init__()
        self._porringer = porringer
        self._plugins = plugins

    def run(self) -> None:
        """Re-sync all cached project manifests."""
        try:
            directories = self._porringer.cache.list_directories()
            count = 0
            for directory in directories:
                path = Path(directory.path)
                if not self._porringer.sync.has_manifest(path):
                    logger.debug('Skipping path without manifest: %s', path)
                    continue
                params = SetupParameters(
                    paths=[path],
                    project_directory=path if path.is_dir() else None,
                    strategy=SyncStrategy.LATEST,
                    plugins=self._plugins,
                )
                asyncio.run(self._sync(params))
                count += 1
            self.finished.emit(count)
        except Exception as e:
            logger.exception('Tool update failed')
            self.error.emit(str(e))

    async def _sync(self, params: SetupParameters) -> None:
        """Execute a sync stream for the given parameters."""
        async for _event in self._porringer.sync.execute_stream(params):
            pass  # consume events to completion
