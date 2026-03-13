"""Centralised logging configuration for the Synodic Client.

Provides a rotating file handler with eager flushing and runtime
log-level switching via :func:`set_debug_level`.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from synodic_client.config import config_dir, is_dev_mode

_LOG_FILENAME = 'synodic.log'
_LOG_FILENAME_DEV = 'synodic-dev.log'
_MAX_BYTES = 1_048_576  # 1 MB
_BACKUP_COUNT = 3
_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'


def log_path() -> Path:
    """Return the path to the application log file.

    The file lives under ``config_dir() / 'logs'`` so that agents and
    developers can find it at a deterministic, well-known location.

    Returns:
        Path to the log file.
    """
    return config_dir() / 'logs' / (_LOG_FILENAME_DEV if is_dev_mode() else _LOG_FILENAME)


class EagerRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that flushes after every record.

    This ensures log entries are visible immediately when the file is
    opened in an external editor.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a record and flush the stream."""
        super().emit(record)
        self.flush()


def configure_logging(*, debug: bool = False) -> None:
    """Set up application-wide logging.

    Attaches a :class:`EagerRotatingFileHandler` to the ``synodic_client``
    and ``porringer`` loggers and configures :func:`logging.basicConfig`
    for ``INFO`` level output on *stderr*.

    Args:
        debug: When ``True``, set the file handler and app logger to
            ``DEBUG`` level immediately.  Equivalent to calling
            :func:`set_debug_level` after configuration.

    Safe to call more than once — subsequent calls are no-ops.
    """
    app_logger = logging.getLogger('synodic_client')

    # Guard: skip if already configured (e.g. by bootstrap.py)
    if any(isinstance(h, EagerRotatingFileHandler) for h in app_logger.handlers):
        return

    logging.basicConfig(level=logging.INFO)

    log_path().parent.mkdir(parents=True, exist_ok=True)

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

    if debug:
        set_debug_level(enabled=True)


def set_debug_level(*, enabled: bool) -> None:
    """Switch the app logger and file handler between DEBUG and INFO at runtime.

    Safe to call at any time.  Has no effect if logging has not been
    configured yet.

    Args:
        enabled: ``True`` for DEBUG, ``False`` for INFO.
    """
    level = logging.DEBUG if enabled else logging.INFO

    app_logger = logging.getLogger('synodic_client')
    app_logger.setLevel(level)
    for h in app_logger.handlers:
        if isinstance(h, EagerRotatingFileHandler):
            h.setLevel(level)
