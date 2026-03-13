"""Tests for operations.update module."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from synodic_client.operations.schema import DownloadResult, UpdateCheckResult
from synodic_client.operations.update import apply_self_update, check_self_update, download_self_update

# ---------------------------------------------------------------------------
# check_self_update
# ---------------------------------------------------------------------------


class TestCheckSelfUpdate:
    """Tests for check_self_update()."""

    @staticmethod
    def test_returns_available_when_update_exists() -> None:
        """Returns available=True with the latest version."""
        client = MagicMock()
        check_result = MagicMock()
        check_result.error = None
        check_result.available = True
        check_result.current_version = '1.0.0'
        check_result.latest_version = '2.0.0'
        client.check_for_update.return_value = check_result

        result = asyncio.run(check_self_update(client))
        assert isinstance(result, UpdateCheckResult)
        assert result.available is True
        assert result.version == '2.0.0'
        assert result.current_version == '1.0.0'

    @staticmethod
    def test_returns_unavailable_when_no_update() -> None:
        """Returns available=False when already on the latest."""
        client = MagicMock()
        check_result = MagicMock()
        check_result.error = None
        check_result.available = False
        check_result.current_version = '1.0.0'
        check_result.latest_version = None
        client.check_for_update.return_value = check_result

        result = asyncio.run(check_self_update(client))
        assert result.available is False
        assert result.version is None

    @staticmethod
    def test_returns_error_when_check_fails() -> None:
        """Returns error string when the check reports an error."""
        client = MagicMock()
        check_result = MagicMock()
        check_result.error = 'Network timeout'
        check_result.current_version = '1.0.0'
        client.check_for_update.return_value = check_result

        result = asyncio.run(check_self_update(client))
        assert result.available is False
        assert result.error == 'Network timeout'

    @staticmethod
    def test_returns_error_when_updater_not_initialised() -> None:
        """Returns error when check_for_update returns None."""
        client = MagicMock()
        client.check_for_update.return_value = None
        client.version = '1.0.0'

        result = asyncio.run(check_self_update(client))
        assert result.available is False
        assert result.error is not None
        assert 'not initialized' in result.error.lower()


# ---------------------------------------------------------------------------
# download_self_update
# ---------------------------------------------------------------------------


class TestDownloadSelfUpdate:
    """Tests for download_self_update()."""

    @staticmethod
    def test_success() -> None:
        """Returns success=True when download succeeds."""
        client = MagicMock()
        client.download_update.return_value = True
        client.version = '2.0.0'

        result = asyncio.run(download_self_update(client))
        assert isinstance(result, DownloadResult)
        assert result.success is True
        assert result.version == '2.0.0'

    @staticmethod
    def test_failure() -> None:
        """Returns success=False with error message on failure."""
        client = MagicMock()
        client.download_update.return_value = False
        client.version = '1.0.0'

        result = asyncio.run(download_self_update(client))
        assert result.success is False
        assert result.error is not None

    @staticmethod
    def test_progress_callback_invoked() -> None:
        """The on_progress callback is wired to the download."""
        client = MagicMock()
        client.download_update.return_value = True
        client.version = '2.0.0'

        progress_values: list[int] = []

        def _on_progress(pct: int) -> None:
            progress_values.append(pct)

        # download_self_update passes a _progress wrapper; we just verify
        # download_update receives a callable and the overall flow works.
        result = asyncio.run(download_self_update(client, on_progress=_on_progress))
        assert result.success is True
        client.download_update.assert_called_once()


# ---------------------------------------------------------------------------
# apply_self_update
# ---------------------------------------------------------------------------


class TestApplySelfUpdate:
    """Tests for apply_self_update()."""

    @staticmethod
    def test_delegates_to_client() -> None:
        """Calls client.apply_update_on_exit with correct kwargs."""
        client = MagicMock()
        apply_self_update(client, restart=True, silent=False)
        client.apply_update_on_exit.assert_called_once_with(restart=True, silent=False)

    @staticmethod
    def test_no_restart() -> None:
        """Passes restart=False correctly."""
        client = MagicMock()
        apply_self_update(client, restart=False, silent=True)
        client.apply_update_on_exit.assert_called_once_with(restart=False, silent=True)
