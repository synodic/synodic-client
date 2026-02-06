"""Tests for URI protocol handler registration."""

import sys
import winreg
from unittest.mock import MagicMock, patch

import pytest

from synodic_client.protocol import PROTOCOL_NAME, register_protocol, remove_protocol

_EXPECTED_REGISTRY_KEY_COUNT = 2


class TestRegisterProtocol:
    """Tests for register_protocol."""

    @staticmethod
    @pytest.mark.skipif(sys.platform != 'win32', reason='Windows only')
    def test_writes_registry_keys() -> None:
        """Verify correct registry keys are written on Windows."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'CreateKey', return_value=mock_key) as mock_create,
            patch.object(winreg, 'SetValueEx'),
        ):
            register_protocol(r'C:\Program Files\Synodic\synodic.exe')

        # Should create the protocol key and command key
        assert mock_create.call_count == _EXPECTED_REGISTRY_KEY_COUNT

        # Verify protocol key path
        first_call_args = mock_create.call_args_list[0][0]
        assert first_call_args[1] == f'Software\\Classes\\{PROTOCOL_NAME}'

        # Verify command key path
        second_call_args = mock_create.call_args_list[1][0]
        assert second_call_args[1].endswith('shell\\open\\command')

    @staticmethod
    @pytest.mark.skipif(sys.platform != 'win32', reason='Windows only')
    def test_sets_url_protocol_value() -> None:
        """Verify the 'URL Protocol' value is set."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with patch.object(winreg, 'CreateKey', return_value=mock_key), patch.object(winreg, 'SetValueEx') as mock_set:
            register_protocol(r'C:\Program Files\Synodic\synodic.exe')

        # Check that SetValueEx was called with 'URL Protocol'
        url_protocol_calls = [c for c in mock_set.call_args_list if c[0][1] == 'URL Protocol']
        assert len(url_protocol_calls) == 1

    @staticmethod
    def test_noop_on_non_windows() -> None:
        """Verify register_protocol is a no-op on non-Windows platforms."""
        with patch('synodic_client.protocol.sys') as mock_sys:
            mock_sys.platform = 'linux'
            # Should not raise and should not attempt winreg import
            register_protocol('/usr/bin/synodic')


class TestRemoveProtocol:
    """Tests for remove_protocol."""

    @staticmethod
    @pytest.mark.skipif(sys.platform != 'win32', reason='Windows only')
    def test_deletes_registry_key() -> None:
        """Verify the protocol key is deleted."""
        with patch('synodic_client.protocol._delete_key_recursive') as mock_delete:
            remove_protocol()

        mock_delete.assert_called_once_with(
            winreg.HKEY_CURRENT_USER,
            f'Software\\Classes\\{PROTOCOL_NAME}',
        )

    @staticmethod
    @pytest.mark.skipif(sys.platform != 'win32', reason='Windows only')
    def test_handles_missing_key_gracefully() -> None:
        """Verify no error when protocol key doesn't exist."""
        with patch(
            'synodic_client.protocol._delete_key_recursive',
            side_effect=FileNotFoundError,
        ):
            # Should not raise
            remove_protocol()

    @staticmethod
    def test_noop_on_non_windows() -> None:
        """Verify remove_protocol is a no-op on non-Windows platforms."""
        with patch('synodic_client.protocol.sys') as mock_sys:
            mock_sys.platform = 'linux'
            remove_protocol()
