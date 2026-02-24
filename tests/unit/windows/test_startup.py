"""Tests for Windows auto-startup registration."""

import winreg
from unittest.mock import MagicMock, patch

from synodic_client.startup import (
    RUN_KEY_PATH,
    STARTUP_VALUE_NAME,
    is_startup_registered,
    register_startup,
    remove_startup,
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
        ):
            register_startup(r'C:\Program Files\Synodic\synodic.exe')

        mock_open.assert_called_once_with(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        mock_set.assert_called_once_with(
            mock_key,
            STARTUP_VALUE_NAME,
            0,
            winreg.REG_SZ,
            r'"C:\Program Files\Synodic\synodic.exe"',
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

        mock_delete.assert_called_once_with(mock_key, STARTUP_VALUE_NAME)

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
        """Verify True when the value exists."""
        mock_key = MagicMock()
        mock_key.__enter__ = MagicMock(return_value=mock_key)
        mock_key.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(winreg, 'OpenKey', return_value=mock_key),
            patch.object(winreg, 'QueryValueEx', return_value=(r'"C:\synodic.exe"', winreg.REG_SZ)),
        ):
            assert is_startup_registered() is True

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
            assert is_startup_registered() is False
