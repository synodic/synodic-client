"""Tests for URI protocol handler registration."""

import winreg
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from synodic_client.protocol import PROTOCOL_NAME, register_protocol, remove_protocol

_EXPECTED_REGISTRY_KEY_COUNT = 2

_TEST_PROTOCOL = f'{PROTOCOL_NAME}_test'
"""Temporary protocol name used by integration tests to avoid clobbering the real registration."""


class TestRegisterProtocol:
    """Tests for register_protocol."""

    @staticmethod
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
    def test_deletes_registry_key() -> None:
        """Verify the protocol key is deleted."""
        with patch('synodic_client.protocol._delete_key_recursive') as mock_delete:
            remove_protocol()

        mock_delete.assert_called_once_with(
            winreg.HKEY_CURRENT_USER,
            f'Software\\Classes\\{PROTOCOL_NAME}',
        )

    @staticmethod
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


class TestProtocolIntegration:
    """Integration tests that read/write real registry keys under a test protocol name."""

    @staticmethod
    def test_register_creates_valid_registry_entries() -> None:
        """Register under a test key, verify values, then clean up."""
        test_exe = r'C:\test\synodic_test.exe'
        key_path = f'Software\\Classes\\{_TEST_PROTOCOL}'

        try:
            # Register using the test protocol name
            with patch('synodic_client.protocol.PROTOCOL_NAME', _TEST_PROTOCOL):
                register_protocol(test_exe)

            # Verify the protocol key
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                description, _ = winreg.QueryValueEx(key, '')
                assert description == 'Synodic Client Protocol'

                url_protocol, _ = winreg.QueryValueEx(key, 'URL Protocol')
                assert not url_protocol

            # Verify the command key
            command_path = f'{key_path}\\shell\\open\\command'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, command_path) as key:
                command, _ = winreg.QueryValueEx(key, '')
                assert test_exe in command
                assert '"%1"' in command

        finally:
            # Clean up the test key
            with patch('synodic_client.protocol.PROTOCOL_NAME', _TEST_PROTOCOL):
                remove_protocol()

    @staticmethod
    def test_remove_deletes_registry_entries() -> None:
        """Register then remove under a test key, verify the key is gone."""
        key_path = f'Software\\Classes\\{_TEST_PROTOCOL}'

        with patch('synodic_client.protocol.PROTOCOL_NAME', _TEST_PROTOCOL):
            register_protocol(r'C:\test\synodic_test.exe')
            remove_protocol()

        with pytest.raises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)

    @staticmethod
    def test_register_is_idempotent() -> None:
        """Calling register twice with a different exe updates the command."""
        key_path = f'Software\\Classes\\{_TEST_PROTOCOL}\\shell\\open\\command'
        exe_v1 = r'C:\test\v1\synodic.exe'
        exe_v2 = r'C:\test\v2\synodic.exe'

        try:
            with patch('synodic_client.protocol.PROTOCOL_NAME', _TEST_PROTOCOL):
                register_protocol(exe_v1)
                register_protocol(exe_v2)

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                command, _ = winreg.QueryValueEx(key, '')
                assert exe_v2 in command
                assert exe_v1 not in command

        finally:
            with patch('synodic_client.protocol.PROTOCOL_NAME', _TEST_PROTOCOL):
                remove_protocol()


class TestProtocolLive:
    """Verify the live protocol registration on this machine."""

    @staticmethod
    def test_protocol_is_registered() -> None:
        """Verify that the synodic:// protocol handler is currently registered."""
        key_path = f'Software\\Classes\\{PROTOCOL_NAME}'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                _, reg_type = winreg.QueryValueEx(key, 'URL Protocol')
                assert reg_type == winreg.REG_SZ
        except FileNotFoundError:
            pytest.skip('Protocol handler not registered on this machine')

    @staticmethod
    def test_command_points_to_existing_exe() -> None:
        """Verify the registered command points to an exe path (may not exist in CI)."""
        key_path = f'Software\\Classes\\{PROTOCOL_NAME}\\shell\\open\\command'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                command, _ = winreg.QueryValueEx(key, '')
                # Command format: "C:\...\synodic.exe" "%1"
                exe_path = command.split('"')[1]
                assert exe_path.endswith('.exe'), f'Expected .exe path, got: {exe_path}'
                assert Path(exe_path).name in {'synodic.exe', 'python.exe'}, f'Unexpected exe: {exe_path}'
        except FileNotFoundError:
            pytest.skip('Protocol handler not registered on this machine')
