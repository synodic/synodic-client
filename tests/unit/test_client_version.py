"""Tests for Client.version property behavior."""

import importlib.metadata
from unittest.mock import patch

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
