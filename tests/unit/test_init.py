"""Tests for the shared startup preamble."""

from unittest.mock import MagicMock, patch

import pytest

import synodic_client.application.init as init_mod
from synodic_client.application.init import run_startup_preamble

_MODULE = 'synodic_client.application.init'


@pytest.fixture(autouse=True)
def _reset_preamble_guard() -> None:
    """Reset the idempotency guard before each test."""
    init_mod._preamble_done = False


class TestRunStartupPreamble:
    """Verify that run_startup_preamble orchestrates the correct calls."""

    @staticmethod
    def test_calls_seed_and_register_protocol() -> None:
        """Seed, protocol registration, and config resolution are invoked."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build') as mock_seed,
            patch(f'{_MODULE}.register_protocol') as mock_proto,
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.register_startup'),
            patch(f'{_MODULE}.remove_startup'),
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_seed.assert_called_once()
        mock_proto.assert_called_once_with(r'C:\app\synodic.exe')
        mock_resolve.assert_called_once()

    @staticmethod
    def test_registers_startup_when_auto_start_true() -> None:
        """register_startup is called when auto_start is True."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol'),
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.register_startup') as mock_register,
            patch(f'{_MODULE}.remove_startup') as mock_remove,
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_register.assert_called_once_with(r'C:\app\synodic.exe')
        mock_remove.assert_not_called()

    @staticmethod
    def test_removes_startup_when_auto_start_false() -> None:
        """remove_startup is called when auto_start is False."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol'),
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.register_startup') as mock_register,
            patch(f'{_MODULE}.remove_startup') as mock_remove,
        ):
            mock_resolve.return_value = MagicMock(auto_start=False)
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_remove.assert_called_once()
        mock_register.assert_not_called()

    @staticmethod
    def test_defaults_exe_path_to_sys_executable() -> None:
        """When exe_path is None, sys.executable is used."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol') as mock_proto,
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.register_startup') as mock_register,
            patch(f'{_MODULE}.remove_startup'),
            patch(f'{_MODULE}.sys') as mock_sys,
        ):
            mock_sys.executable = r'C:\Python\python.exe'
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble()

        mock_proto.assert_called_once_with(r'C:\Python\python.exe')
        mock_register.assert_called_once_with(r'C:\Python\python.exe')

    @staticmethod
    def test_idempotent_on_second_call() -> None:
        """A second call is a no-op; the preamble runs only once."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build') as mock_seed,
            patch(f'{_MODULE}.register_protocol'),
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.register_startup'),
            patch(f'{_MODULE}.remove_startup'),
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\app\synodic.exe')
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_seed.assert_called_once()
