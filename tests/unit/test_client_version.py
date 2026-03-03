"""Tests for Client.version property behavior."""

import importlib.metadata
from unittest.mock import MagicMock, PropertyMock, patch

from packaging.version import Version

from synodic_client.client import Client


class TestClientVersion:
    """Tests for Client.version property."""

    @staticmethod
    def test_version_from_metadata() -> None:
        """Verify version is retrieved from importlib.metadata when available."""
        client = Client()

        with patch.object(importlib.metadata, 'version', return_value='1.2.3'):
            version = client.version

        assert version == Version('1.2.3')

    @staticmethod
    def test_version_is_version_object() -> None:
        """Verify version property returns a Version object."""
        client = Client()
        version = client.version

        assert isinstance(version, Version)

    @staticmethod
    def test_version_dev_format() -> None:
        """Verify dev versions are parsed correctly."""
        client = Client()
        dev_version = '1.0.0.dev5+gabcdef1'
        expected = Version(dev_version)

        with patch.object(importlib.metadata, 'version', return_value=dev_version):
            version = client.version

        assert version == expected
        assert version.dev == expected.dev
        assert version.local == expected.local


class TestClientVersionResolution:
    """Verify Client.version prefers Velopack when available."""

    @staticmethod
    def test_returns_velopack_version_when_installed() -> None:
        """Velopack version is preferred when an installed updater exists."""
        mock_updater = MagicMock()
        mock_updater.is_installed = True
        mock_updater.current_version = Version('5.6.7')

        client = Client()
        client._updater = mock_updater

        assert client.version == Version('5.6.7')

    @staticmethod
    def test_falls_back_when_not_installed() -> None:
        """Metadata version is used when the updater is not Velopack-installed."""
        mock_updater = MagicMock()
        mock_updater.is_installed = False

        client = Client()
        client._updater = mock_updater

        with patch.object(importlib.metadata, 'version', return_value='1.0.0.dev1'):
            version = client.version

        assert version == Version('1.0.0.dev1')

    @staticmethod
    def test_falls_back_when_no_updater() -> None:
        """Metadata version is used when the updater has not been initialized."""
        client = Client()

        with patch.object(importlib.metadata, 'version', return_value='2.3.4'):
            version = client.version

        assert version == Version('2.3.4')

    @staticmethod
    def test_falls_back_on_exception() -> None:
        """Graceful fallback when querying the updater raises an exception."""
        mock_updater = MagicMock()
        type(mock_updater).is_installed = PropertyMock(side_effect=RuntimeError('boom'))

        client = Client()
        client._updater = mock_updater

        with patch.object(importlib.metadata, 'version', return_value='3.0.0'):
            version = client.version

        assert version == Version('3.0.0')
