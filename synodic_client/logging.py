"""Centralised logging configuration for the Synodic Client.

Provides a rotating file handler with eager flushing.
"""

import logging
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from synodic_client.config import is_dev_mode

_LOG_FILENAME = 'synodic.log'
_LOG_FILENAME_DEV = 'synodic-dev.log'
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
    return Path(tempfile.gettempdir()) / (_LOG_FILENAME_DEV if is_dev_mode() else _LOG_FILENAME)


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

    Safe to call more than once — subsequent calls are no-ops.
    """
    app_logger = logging.getLogger('synodic_client')

    # Guard: skip if already configured (e.g. by bootstrap.py)
    if any(isinstance(h, EagerRotatingFileHandler) for h in app_logger.handlers):
        return

    logging.basicConfig(level=logging.INFO)

    handler = EagerRotatingFileHandler(
        str(log_path()),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(_FORMAT))

    app_logger.addHandler(handler)

    porringer_logger = logging.getLogger('porringer')
    porringer_logger.addHandler(handler)

    # In frozen (PyInstaller) builds, capture porringer DEBUG output so
    # that plugin discovery details appear in the log file for post-mortem
    # diagnostics.  In dev mode, keep INFO to reduce noise.
    if getattr(sys, 'frozen', False):
        porringer_logger.setLevel(logging.DEBUG)
    else:
        porringer_logger.setLevel(logging.INFO)
