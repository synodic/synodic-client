"""Tests for Windows auto-startup registration."""

import winreg
from unittest.mock import MagicMock, patch

import pytest

from synodic_client.startup import (
    APPROVED_ENABLED,
    RUN_KEY_PATH,
    STARTUP_APPROVED_KEY_PATH,
    STARTUP_VALUE_NAME,
    get_registered_startup_path,
    is_startup_registered,
    register_startup,
    remove_startup,
    sync_startup,
)


class TestRegisterStartup:
    """Tests for register_startup."""

    @staticmethod
    def test_writes_registry_value() -> None:
        """Verify correct registry value is written on Windows."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key) as mock_open,
            patch.object(winreg, 'SetValueEx') as mock_set,
            patch.object(winreg, 'CreateKey', return_value=mock_key),
        ):
            register_startup(r'C:\Program Files\Synodic\synodic.exe')

        mock_open.assert_called_once_with(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        mock_set.assert_any_call(
            mock_key,
            STARTUP_VALUE_NAME,
            0,
            winreg.REG_SZ,
            r'"C:\Program Files\Synodic\synodic.exe"',
        )

    @staticmethod
    def test_writes_startup_approved_enabled() -> None:
        """Verify the StartupApproved enabled flag is written."""
        mock_run_key = MagicMock()
        mock_run_key.__enter__ = MagicMock(return_value=mock_run_key)
        mock_run_key.__exit__ = MagicMock(return_value=False)

        mock_approved_key = MagicMock()
        mock_approved_key.__enter__ = MagicMock(return_value=mock_approved_key)
        mock_approved_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_run_key),
            patch.object(winreg, 'SetValueEx') as mock_set,
            patch.object(winreg, 'CreateKey', return_value=mock_approved_key) as mock_create,
        ):
            register_startup(r'C:\synodic.exe')

        mock_create.assert_called_once_with(
            winreg.HKEY_CURRENT_USER,
            STARTUP_APPROVED_KEY_PATH,
        )
        mock_set.assert_any_call(
            mock_approved_key,
            STARTUP_VALUE_NAME,
            0,
            winreg.REG_BINARY,
            APPROVED_ENABLED,
        )

    @staticmethod
    def test_noop_on_non_windows() -> None:
        """Verify register_startup is a no-op on non-Windows platforms."""
        with patch('synodic_client.startup.sys') as mock_sys:
            mock_sys.platform = 'linux'
            register_startup('/usr/bin/synodic')


class TestRemoveStartup:
    """Tests for remove_startup."""

    @staticmethod
    def test_deletes_registry_value() -> None:
        """Verify the startup value is deleted."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(winreg, 'DeleteValue') as mock_delete,
        ):
            remove_startup()

        mock_delete.assert_any_call(mock_key, STARTUP_VALUE_NAME)

    @staticmethod
    def test_clears_startup_approved() -> None:
        """Verify the StartupApproved flag is also deleted."""
        mock_run_key = MagicMock()
        mock_run_key.__enter__ = MagicMock(return_value=mock_run_key)
        mock_run_key.__exit__ = MagicMock(return_value=False)

        mock_approved_key = MagicMock()
        mock_approved_key.__enter__ = MagicMock(return_value=mock_approved_key)
        mock_approved_key.__exit__ = MagicMock(return_value=False)

        def _open_key_side_effect(_root: int, path: str, _reserved: int, _access: int) -> MagicMock:
            if 'Explorer' in path:
                return mock_approved_key
            return mock_run_key

        with (
            patch.object(winreg, 'OpenKey', side_effect=_open_key_side_effect),
            patch.object(winreg, 'DeleteValue') as mock_delete,
        ):
            remove_startup()

        # Both the Run and StartupApproved values should be deleted
        expected_delete_count = 2
        assert mock_delete.call_count == expected_delete_count
        mock_delete.assert_any_call(mock_run_key, STARTUP_VALUE_NAME)
        mock_delete.assert_any_call(mock_approved_key, STARTUP_VALUE_NAME)

    @staticmethod
    def test_handles_missing_value_gracefully() -> None:
        """Verify no error when startup value doesn't exist."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(winreg, 'DeleteValue', side_effect=FileNotFoundError),
        ):
            # Should not raise
            remove_startup()

    @staticmethod
    def test_noop_on_non_windows() -> None:
        """Verify remove_startup is a no-op on non-Windows platforms."""
        with patch('synodic_client.startup.sys') as mock_sys:
            mock_sys.platform = 'linux'
            remove_startup()


class TestIsStartupRegistered:
    """Tests for is_startup_registered."""

    @staticmethod
    def test_returns_true_when_present() -> None:
        """Verify True when the value exists and no approval override."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        def _open_key_side_effect(_root: int, path: str, _reserved: int, _access: int) -> MagicMock:
            return mock_key

        def _query_side_effect(key: MagicMock, name: str) -> tuple[object, int]:
            # Run key exists; StartupApproved key raises FileNotFoundError
            # (no override → treated as enabled)
            raise FileNotFoundError

        with (
            patch.object(winreg, 'OpenKey', side_effect=_open_key_side_effect),
            patch.object(
                winreg,
                'QueryValueEx',
                side_effect=[
                    (r'"C:\synodic.exe"', winreg.REG_SZ),  # Run key query
                    FileNotFoundError,  # StartupApproved query
                ],
            ),
        ):
            assert is_startup_registered() is True

    @staticmethod
    def test_returns_true_when_startup_approved_enabled() -> None:
        """Verify True when the StartupApproved byte is 0x02 (enabled)."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        enabled_data = b'\x02' + b'\x00' * 11

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(
                winreg,
                'QueryValueEx',
                side_effect=[
                    (r'"C:\synodic.exe"', winreg.REG_SZ),  # Run key query
                    (enabled_data, winreg.REG_BINARY),  # StartupApproved query
                ],
            ),
        ):
            assert is_startup_registered() is True

    @staticmethod
    def test_returns_false_when_startup_approved_disabled() -> None:
        """Verify False when the StartupApproved byte is 0x03 (disabled)."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        disabled_data = b'\x03' + b'\x00' * 11

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(
                winreg,
                'QueryValueEx',
                side_effect=[
                    (r'"C:\synodic.exe"', winreg.REG_SZ),  # Run key query
                    (disabled_data, winreg.REG_BINARY),  # StartupApproved query
                ],
            ),
        ):
            assert is_startup_registered() is False

    @staticmethod
    def test_returns_false_when_missing() -> None:
        """Verify False when the value does not exist."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(winreg, 'QueryValueEx', side_effect=FileNotFoundError),
        ):
            assert is_startup_registered() is False


class TestGetRegisteredStartupPath:
    """Tests for get_registered_startup_path."""

    @staticmethod
    def test_returns_unquoted_path() -> None:
        """Verify the returned path has surrounding quotes stripped."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(
                winreg,
                'QueryValueEx',
                return_value=(r'"C:\Program Files\Synodic\synodic.exe"', winreg.REG_SZ),
            ),
        ):
            assert get_registered_startup_path() == r'C:\Program Files\Synodic\synodic.exe'

    @staticmethod
    def test_returns_none_when_missing() -> None:
        """Verify None when the registry value does not exist."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(winreg, 'QueryValueEx', side_effect=FileNotFoundError),
        ):
            assert get_registered_startup_path() is None

    @staticmethod
    def test_returns_none_on_os_error() -> None:
        """Verify None when an OSError prevents reading the registry."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(winreg, 'QueryValueEx', side_effect=OSError('access denied')),
        ):
            assert get_registered_startup_path() is None


_SYNC_MODULE = 'synodic_client.startup'


class TestSyncStartup:
    """Tests for sync_startup."""

    @staticmethod
    def test_registers_when_auto_start_true() -> None:
        """sync_startup calls register_startup when auto_start is True."""
        with (
            patch(f'{_SYNC_MODULE}.getattr', return_value=True),
            patch(f'{_SYNC_MODULE}.get_registered_startup_path', return_value=None),
            patch(f'{_SYNC_MODULE}.register_startup') as mock_reg,
            patch(f'{_SYNC_MODULE}.remove_startup') as mock_rem,
        ):
            sync_startup(r'C:\app\synodic.exe', auto_start=True)

        mock_reg.assert_called_once_with(r'C:\app\synodic.exe')
        mock_rem.assert_not_called()

    @staticmethod
    def test_removes_when_auto_start_false() -> None:
        """sync_startup calls remove_startup when auto_start is False."""
        with (
            patch(f'{_SYNC_MODULE}.getattr', return_value=True),
            patch(f'{_SYNC_MODULE}.get_registered_startup_path', return_value=None),
            patch(f'{_SYNC_MODULE}.register_startup') as mock_reg,
            patch(f'{_SYNC_MODULE}.remove_startup') as mock_rem,
        ):
            sync_startup(r'C:\app\synodic.exe', auto_start=False)

        mock_rem.assert_called_once()
        mock_reg.assert_not_called()

    @staticmethod
    def test_noop_when_not_frozen() -> None:
        """sync_startup is a no-op when sys.frozen is falsy."""
        with (
            patch(f'{_SYNC_MODULE}.getattr', return_value=False),
            patch(f'{_SYNC_MODULE}.register_startup') as mock_reg,
            patch(f'{_SYNC_MODULE}.remove_startup') as mock_rem,
        ):
            sync_startup(r'C:\app\synodic.exe', auto_start=True)

        mock_reg.assert_not_called()
        mock_rem.assert_not_called()

    @staticmethod
    def test_logs_warning_on_path_mismatch(caplog: pytest.LogCaptureFixture) -> None:
        """A warning is logged when the registered path differs from exe_path."""
        with (
            patch(f'{_SYNC_MODULE}.getattr', return_value=True),
            patch(f'{_SYNC_MODULE}.get_registered_startup_path', return_value=r'C:\old\synodic.exe'),
            patch(f'{_SYNC_MODULE}.register_startup'),
            patch(f'{_SYNC_MODULE}.remove_startup'),
        ):
            sync_startup(r'C:\new\synodic.exe', auto_start=True)

        assert 'mismatch' in caplog.text.lower()

    @staticmethod
    def test_no_warning_when_paths_match(caplog: pytest.LogCaptureFixture) -> None:
        """No warning when the registered path matches exe_path."""
        with (
            patch(f'{_SYNC_MODULE}.getattr', return_value=True),
            patch(f'{_SYNC_MODULE}.get_registered_startup_path', return_value=r'C:\app\synodic.exe'),
            patch(f'{_SYNC_MODULE}.register_startup'),
            patch(f'{_SYNC_MODULE}.remove_startup'),
        ):
            sync_startup(r'C:\app\synodic.exe', auto_start=True)

        assert 'mismatch' not in caplog.text.lower()
