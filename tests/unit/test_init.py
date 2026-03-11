"""Tests for the shared startup preamble."""

from unittest.mock import MagicMock, patch

import pytest

import synodic_client.application.init as init_mod
from synodic_client.application.init import run_startup_preamble

_MODULE = 'synodic_client.application.init'


@pytest.fixture(autouse=True)
def _reset_preamble_guard() -> None:
    """Reset the idempotency guard before each test."""
    init_mod._PreambleState.done = False


class TestRunStartupPreamble:
    """Verify that run_startup_preamble orchestrates the correct calls."""

    @staticmethod
    def test_calls_seed_and_register_protocol() -> None:
        """Seed, protocol registration, and config resolution are invoked."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build') as mock_seed,
            patch(f'{_MODULE}.register_protocol') as mock_proto,
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.sync_startup'),
            patch(f'{_MODULE}.getattr', return_value=True),
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_seed.assert_called_once()
        mock_proto.assert_called_once_with(r'C:\app\synodic.exe')
        mock_resolve.assert_called_once()

    @staticmethod
    def test_delegates_to_sync_startup_with_auto_start() -> None:
        """sync_startup is called with the resolved auto_start preference."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol'),
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.sync_startup') as mock_sync,
            patch(f'{_MODULE}.getattr', return_value=True),
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_sync.assert_called_once_with(r'C:\app\synodic.exe', auto_start=True)

    @staticmethod
    def test_delegates_to_sync_startup_when_auto_start_false() -> None:
        """sync_startup receives auto_start=False when config says so."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol'),
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.sync_startup') as mock_sync,
            patch(f'{_MODULE}.getattr', return_value=True),
        ):
            mock_resolve.return_value = MagicMock(auto_start=False)
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_sync.assert_called_once_with(r'C:\app\synodic.exe', auto_start=False)

    @staticmethod
    def test_defaults_exe_path_to_sys_executable() -> None:
        """When exe_path is None, sys.executable is used."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol') as mock_proto,
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.sync_startup') as mock_sync,
            patch(f'{_MODULE}.sys') as mock_sys,
            patch(f'{_MODULE}.getattr', return_value=True),
        ):
            mock_sys.executable = r'C:\Python\python.exe'
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble()

        mock_proto.assert_called_once_with(r'C:\Python\python.exe')
        mock_sync.assert_called_once_with(r'C:\Python\python.exe', auto_start=True)

    @staticmethod
    def test_skips_protocol_when_not_frozen() -> None:
        """Protocol registration is skipped in non-frozen builds."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build'),
            patch(f'{_MODULE}.register_protocol') as mock_proto,
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.sync_startup') as mock_sync,
            patch(f'{_MODULE}.getattr', return_value=False),
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\Python\python.exe')

        mock_proto.assert_not_called()
        # sync_startup is still called — it handles the frozen guard internally
        mock_sync.assert_called_once()

    @staticmethod
    def test_idempotent_on_second_call() -> None:
        """A second call is a no-op; the preamble runs only once."""
        with (
            patch(f'{_MODULE}.seed_user_config_from_build') as mock_seed,
            patch(f'{_MODULE}.register_protocol'),
            patch(f'{_MODULE}.resolve_config') as mock_resolve,
            patch(f'{_MODULE}.sync_startup'),
        ):
            mock_resolve.return_value = MagicMock(auto_start=True)
            run_startup_preamble(r'C:\app\synodic.exe')
            run_startup_preamble(r'C:\app\synodic.exe')

        mock_seed.assert_called_once()
