"""Tests for the Client update integration."""

from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

from synodic_client.client import Client
from synodic_client.updater import UpdateConfig, UpdateInfo


@pytest.fixture
def client_with_updater() -> Client:
    """Create a Client with initialized updater."""
    client = Client()
    client.initialize_updater()
    return client


class TestClientUpdater:
    """Tests for Client update methods."""

    @staticmethod
    def test_updater_not_initialized() -> None:
        """Verify updater is None before initialization."""
        client = Client()
        assert client.updater is None

    @staticmethod
    def test_initialize_updater() -> None:
        """Verify updater can be initialized."""
        client = Client()
        updater = client.initialize_updater()

        assert client.updater is not None
        assert updater is client.updater

    @staticmethod
    def test_initialize_updater_with_config() -> None:
        """Verify updater can be initialized with custom config."""
        client = Client()
        config = UpdateConfig(repo_url='https://github.com/custom/repo')

        updater = client.initialize_updater(config)

        assert updater._config.repo_url == 'https://github.com/custom/repo'

    @staticmethod
    def test_check_for_update_without_init() -> None:
        """Verify check_for_update returns None when updater not initialized."""
        client = Client()
        result = client.check_for_update()
        assert result is None

    @staticmethod
    def test_check_for_update_with_init(client_with_updater: Client) -> None:
        """Verify check_for_update delegates to updater."""
        mock_info = UpdateInfo(
            available=False,
            current_version=Version('1.0.0'),
        )

        with patch.object(client_with_updater._updater, 'check_for_update', return_value=mock_info):
            result = client_with_updater.check_for_update()

        assert result is not None
        assert result.available is False

    @staticmethod
    def test_download_update_without_init() -> None:
        """Verify download_update returns False when updater not initialized."""
        client = Client()
        result = client.download_update()
        assert result is False

    @staticmethod
    def test_download_update_with_init(client_with_updater: Client) -> None:
        """Verify download_update delegates to updater."""
        with patch.object(client_with_updater._updater, 'download_update', return_value=True):
            result = client_with_updater.download_update()

        assert result is True

    @staticmethod
    def test_download_update_with_progress(client_with_updater: Client) -> None:
        """Verify download_update passes progress callback."""
        progress_cb = MagicMock()

        with patch.object(client_with_updater._updater, 'download_update', return_value=True) as mock_download:
            result = client_with_updater.download_update(progress_callback=progress_cb)

        assert result is True
        mock_download.assert_called_once_with(progress_cb)

    @staticmethod
    def test_apply_update_and_restart_without_init() -> None:
        """Verify apply_update_and_restart does nothing when updater not initialized."""
        client = Client()
        # Should not raise
        client.apply_update_and_restart()

    @staticmethod
    def test_apply_update_on_exit_without_init() -> None:
        """Verify apply_update_on_exit does nothing when updater not initialized."""
        client = Client()
        # Should not raise
        client.apply_update_on_exit()

    @staticmethod
    def test_apply_update_on_exit_with_init(client_with_updater: Client) -> None:
        """Verify apply_update_on_exit delegates to updater."""
        with patch.object(client_with_updater._updater, 'apply_update_on_exit') as mock_apply:
            client_with_updater.apply_update_on_exit(restart=False)

        mock_apply.assert_called_once_with(restart=False)
