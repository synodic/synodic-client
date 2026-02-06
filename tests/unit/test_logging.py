"""Tests for the centralised logging module."""

import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

from synodic_client.logging import (
    EagerRotatingFileHandler,
    configure_logging,
    log_path,
    open_log,
)


class TestLogPath:
    """Tests for log_path()."""

    @staticmethod
    def test_returns_path_in_temp_dir() -> None:
        """log_path() should resolve inside the system temp directory."""
        path = log_path()
        assert path.parent == Path(tempfile.gettempdir())

    @staticmethod
    def test_filename() -> None:
        """log_path() should use the expected filename."""
        assert log_path().name == 'synodic.log'


class TestEagerRotatingFileHandler:
    """Tests for the eager-flush handler subclass."""

    @staticmethod
    def test_flush_called_on_emit(tmp_path: Path) -> None:
        """Handler should flush the stream after every emit."""
        handler = EagerRotatingFileHandler(str(tmp_path / 'test.log'))
        try:
            record = logging.LogRecord(
                name='test',
                level=logging.INFO,
                pathname='',
                lineno=0,
                msg='hello',
                args=(),
                exc_info=None,
            )
            handler.emit(record)

            # The record should be visible on disk immediately
            content = (tmp_path / 'test.log').read_text(encoding='utf-8')
            assert 'hello' in content
        finally:
            handler.close()


class TestConfigureLogging:
    """Tests for configure_logging()."""

    @staticmethod
    def test_attaches_file_handler(tmp_path: Path) -> None:
        """configure_logging() should attach a file handler to the synodic_client logger."""
        with patch('synodic_client.logging.log_path', return_value=tmp_path / 'synodic.log'):
            app_logger = logging.getLogger('synodic_client')
            initial_count = len(app_logger.handlers)

            configure_logging()

            assert len(app_logger.handlers) > initial_count

            # Clean up the handler we added so it doesn't leak into other tests
            for handler in list(app_logger.handlers):
                if isinstance(handler, EagerRotatingFileHandler):
                    app_logger.removeHandler(handler)
                    handler.close()

    @staticmethod
    def test_writes_to_file(tmp_path: Path) -> None:
        """Log records should be written eagerly to the log file."""
        log_file = tmp_path / 'synodic.log'
        app_logger = logging.getLogger('synodic_client')

        handler = EagerRotatingFileHandler(str(log_file), encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        app_logger.addHandler(handler)
        try:
            test_logger = logging.getLogger('synodic_client.test_writes')
            test_logger.setLevel(logging.INFO)
            test_logger.info('eager-flush-test')

            content = log_file.read_text(encoding='utf-8')
            assert 'eager-flush-test' in content
        finally:
            app_logger.removeHandler(handler)
            handler.close()


class TestOpenLog:
    """Tests for open_log()."""

    @staticmethod
    def test_creates_file_if_missing(tmp_path: Path) -> None:
        """open_log() should create the log file when it does not exist."""
        log_file = tmp_path / 'synodic.log'
        assert not log_file.exists()

        with (
            patch('synodic_client.logging.log_path', return_value=log_file),
            patch('synodic_client.logging.QDesktopServices') as mock_ds,
        ):
            open_log()
            assert log_file.exists()
            mock_ds.openUrl.assert_called_once()

    @staticmethod
    def test_opens_existing_file(tmp_path: Path) -> None:
        """open_log() should open an existing log file without error."""
        log_file = tmp_path / 'synodic.log'
        log_file.write_text('existing content', encoding='utf-8')

        with (
            patch('synodic_client.logging.log_path', return_value=log_file),
            patch('synodic_client.logging.QDesktopServices') as mock_ds,
        ):
            open_log()
            mock_ds.openUrl.assert_called_once()
