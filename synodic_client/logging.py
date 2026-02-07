"""Centralised logging configuration for the Synodic Client.

Provides a rotating file handler with eager flushing and a helper to open
the current log file in the system's default editor.
"""

import logging
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

_LOG_FILENAME = 'synodic.log'
_MAX_BYTES = 5_242_880  # 5 MB
_BACKUP_COUNT = 3
_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'


def log_path() -> Path:
    """Return the path to the application log file.

    The file lives in the system temp directory so it is cleaned up
    automatically by the OS and avoids permission issues.

    Returns:
        Path to the log file.
    """
    return Path(tempfile.gettempdir()) / _LOG_FILENAME


class EagerRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that flushes after every record.

    This ensures log entries are visible immediately when the file is
    opened in an external editor.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a record and flush the stream."""
        super().emit(record)
        self.flush()


def configure_logging() -> None:
    """Set up application-wide logging.

    Attaches a :class:`EagerRotatingFileHandler` to the ``synodic_client``
    and ``porringer`` loggers and configures :func:`logging.basicConfig`
    for ``INFO`` level output on *stderr*.
    """
    logging.basicConfig(level=logging.INFO)

    handler = EagerRotatingFileHandler(
        str(log_path()),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(_FORMAT))

    app_logger = logging.getLogger('synodic_client')
    app_logger.addHandler(handler)

    porringer_logger = logging.getLogger('porringer')
    porringer_logger.addHandler(handler)
    porringer_logger.setLevel(logging.INFO)


def open_log() -> None:
    """Open the log file in the system's default editor.

    Creates an empty file if one does not yet exist so that the OS always
    has something to open.
    """
    path = log_path()
    if not path.exists():
        path.touch()

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
