"""Tests for Client.version property behavior."""

import importlib.metadata
import sys
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
    def test_version_fallback_to_bundled() -> None:
        """Verify fallback to _version.py when metadata unavailable."""
        client = Client()

        with (
            patch.object(
                importlib.metadata,
                'version',
                side_effect=importlib.metadata.PackageNotFoundError('synodic_client'),
            ),
            patch.dict('sys.modules', {'synodic_client._version': None}),
            patch('synodic_client.client.Version') as mock_version,
        ):
            # Simulate _version module with __version__
            mock_version_module = type(sys)('synodic_client._version')
            mock_version_module.__version__ = '2.0.0.dev5'
            sys.modules['synodic_client._version'] = mock_version_module
            mock_version.side_effect = Version

            version = client.version

        assert version == Version('2.0.0.dev5')

    @staticmethod
    def test_version_fallback_to_dev_default() -> None:
        """Verify fallback to 0.0.0.dev0 when both metadata and _version.py unavailable."""
        client = Client()

        # Remove _version from sys.modules if present to force ImportError
        sys.modules.pop('synodic_client._version', None)

        with (
            patch.object(
                importlib.metadata,
                'version',
                side_effect=importlib.metadata.PackageNotFoundError('synodic_client'),
            ),
            patch.dict('sys.modules', {'synodic_client._version': None}),
        ):
            # Force ImportError by making the module None (import will fail)
            del sys.modules['synodic_client._version']

            version = client.version

        assert version == Version('0.0.0.dev0')

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
