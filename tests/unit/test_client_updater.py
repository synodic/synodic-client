"""Tests for the Client update integration."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from synodic_client.client import Client
from synodic_client.updater import UpdateConfig


class TestClientUpdater:
    """Tests for Client update methods."""

    @pytest.fixture
    def mock_porringer_api(self) -> MagicMock:
        """Create a mock porringer API."""
        api = MagicMock()
        api.update = MagicMock()
        return api

    @pytest.fixture
    def client_with_updater(self, mock_porringer_api: MagicMock, tmp_path: Path) -> Client:
        """Create a Client with initialized updater."""
        client = Client()
        config = UpdateConfig(
            metadata_dir=tmp_path / 'metadata',
            download_dir=tmp_path / 'downloads',
            backup_dir=tmp_path / 'backup',
        )
        client.initialize_updater(mock_porringer_api, config)
        return client

    def test_updater_not_initialized(self) -> None:
        """Verify updater is None before initialization."""
        client = Client()
        assert client.updater is None

    def test_initialize_updater(self, mock_porringer_api: MagicMock, tmp_path: Path) -> None:
        """Verify updater can be initialized."""
        client = Client()
        config = UpdateConfig(
            metadata_dir=tmp_path / 'metadata',
            download_dir=tmp_path / 'downloads',
            backup_dir=tmp_path / 'backup',
        )

        updater = client.initialize_updater(mock_porringer_api, config)

        assert client.updater is not None
        assert updater is client.updater

    def test_check_for_update_without_init(self) -> None:
        """Verify check_for_update returns None when updater not initialized."""
        client = Client()
        result = client.check_for_update()
        assert result is None

    def test_check_for_update_with_init(self, client_with_updater: Client, mock_porringer_api: MagicMock) -> None:
        """Verify check_for_update delegates to updater."""
        mock_result = MagicMock()
        mock_result.available = False
        mock_result.latest_version = None
        mock_porringer_api.update.check.return_value = mock_result

        result = client_with_updater.check_for_update()

        assert result is not None
        assert result.available is False

    def test_download_update_without_init(self) -> None:
        """Verify download_update returns None when updater not initialized."""
        client = Client()
        result = client.download_update()
        assert result is None

    def test_apply_update_without_init(self) -> None:
        """Verify apply_update returns False when updater not initialized."""
        client = Client()
        result = client.apply_update()
        assert result is False

    def test_restart_for_update_without_init(self) -> None:
        """Verify restart_for_update does nothing when updater not initialized."""
        client = Client()
        # Should not raise
        client.restart_for_update()
