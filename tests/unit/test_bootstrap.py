"""Tests for the bootstrap entry point startup-sync ordering."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

_MODULE = 'synodic_client.application.bootstrap'


def _run_bootstrap(*, argv: list[str]) -> None:
    """Import (or reload) the bootstrap module, triggering ``bootstrap()``.

    The module-level ``bootstrap()`` call runs on every import/reload,
    so all patches must be in place before calling this.
    """
    # Ensure sys.argv is set for the bootstrap function
    with patch.object(sys, 'argv', argv):
        if _MODULE in sys.modules:
            importlib.reload(sys.modules[_MODULE])
        else:
            importlib.import_module(_MODULE)


class TestBootstrapStartupSync:
    """Verify sync_startup runs before initialize_velopack in bootstrap."""

    @staticmethod
    def test_sync_startup_called_before_velopack_init() -> None:
        """sync_startup must execute before initialize_velopack.

        Velopack's App.run() may exit the process during post-update
        hooks, so the startup registry must already be refreshed.
        """
        call_order: list[str] = []

        def _record_sync(*args: object, **kwargs: object) -> None:
            call_order.append('sync_startup')

        def _record_velopack() -> None:
            call_order.append('initialize_velopack')

        mock_config = MagicMock(auto_start=True)

        with (
            patch('synodic_client.config.set_dev_mode'),
            patch('synodic_client.logging.configure_logging'),
            patch('synodic_client.subprocess_patch.apply'),
            patch('synodic_client.updater.initialize_velopack', side_effect=_record_velopack),
            patch('synodic_client.resolution.resolve_config', return_value=mock_config),
            patch('synodic_client.startup.sync_startup', side_effect=_record_sync) as mock_sync,
            patch('synodic_client.application.init.run_startup_preamble'),
            patch('synodic_client.application.qt.application'),
            patch('synodic_client.protocol.extract_uri_from_args', return_value=None),
        ):
            _run_bootstrap(argv=[r'C:\app\synodic.exe'])

        assert call_order == ['sync_startup', 'initialize_velopack']
        mock_sync.assert_called_once()
        assert mock_sync.call_args.kwargs['auto_start'] is True

    @staticmethod
    def test_sync_startup_skipped_in_dev_mode() -> None:
        """sync_startup is not called when --dev flag is passed."""
        with (
            patch('synodic_client.config.set_dev_mode'),
            patch('synodic_client.logging.configure_logging'),
            patch('synodic_client.subprocess_patch.apply'),
            patch('synodic_client.updater.initialize_velopack'),
            patch('synodic_client.resolution.resolve_config') as mock_resolve,
            patch('synodic_client.startup.sync_startup') as mock_sync,
            patch('synodic_client.application.qt.application'),
            patch('synodic_client.protocol.extract_uri_from_args', return_value=None),
        ):
            _run_bootstrap(argv=[r'C:\app\synodic.exe', '--dev'])

        mock_resolve.assert_not_called()
        mock_sync.assert_not_called()
