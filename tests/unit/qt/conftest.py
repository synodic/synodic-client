"""Configuration for Qt-dependent tests.

Tests in this directory require PySide6.  When the Qt runtime libraries
are not available (e.g. on headless Linux CI), the entire directory is
skipped automatically.

All Qt tests run with the ``offscreen`` platform plugin so that no
windows appear on screen during the test run.
"""

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Force offscreen rendering *before* any PySide6 import.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6.QtWidgets', reason='PySide6 requires system Qt libraries')

from porringer.schema import SetupAction, SetupActionResult, SkipReason
from porringer.schema.plugin import PluginKind
from PySide6.QtWidgets import QApplication

from synodic_client.application.config_store import ConfigStore
from synodic_client.resolution import ResolvedConfig
from synodic_client.schema import DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES, DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

# Single shared QApplication for all Qt tests in this directory.
_app = QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Shared test factories
# ---------------------------------------------------------------------------


def make_resolved_config(**overrides: Any) -> ResolvedConfig:
    """Build a ``ResolvedConfig`` with sensible defaults and optional overrides."""
    defaults: dict[str, Any] = {
        'update_source': None,
        'update_channel': 'stable',
        'auto_update_interval_minutes': DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
        'tool_update_interval_minutes': DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
        'plugin_auto_update': None,
        'prerelease_packages': None,
        'auto_apply': True,
        'auto_start': True,
        'debug_logging': False,
        'last_client_update': None,
        'last_tool_updates': None,
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


def make_config_store(config: ResolvedConfig | None = None) -> ConfigStore:
    """Build a ``ConfigStore`` seeded with *config*."""
    return ConfigStore(config or make_resolved_config())


def make_mock_porringer() -> MagicMock:
    """Build a ``MagicMock`` standing in for the porringer ``API``."""
    mock = MagicMock()
    mock.plugin.list = AsyncMock(return_value=[])
    mock.package.list = AsyncMock(return_value=[])
    mock.cache.list_directories.return_value = []
    return mock


def make_action(
    *,
    kind: PluginKind | None = PluginKind.PACKAGE,
    description: str = 'Install requests',
    installer: str | None = 'pip',
    package: str = 'requests',
    **overrides: Any,
) -> SetupAction:
    """Create a mock ``SetupAction`` with sensible defaults.

    Extra keyword arguments are set as attributes on the mock, supporting
    ``package_description``, ``include_prereleases``, ``command``,
    ``cli_command``, ``constraint``, and ``plugin_target``.
    """
    action = MagicMock(spec=SetupAction)
    action.kind = kind
    action.description = description
    action.installer = installer
    pkg_mock = MagicMock()
    pkg_mock.name = package
    pkg_mock.constraint = overrides.get('constraint')
    pkg_mock.configure_mock(**{'__str__': MagicMock(return_value=package)})
    action.package = pkg_mock
    action.package_description = overrides.get('package_description', description)
    action.command = overrides.get('command')
    action.include_prereleases = overrides.get('include_prereleases', False)
    action.plugin_target = overrides.get('plugin_target')
    action.distro = overrides.get('distro')
    return action


def make_result(
    *,
    success: bool = True,
    skipped: bool = False,
    skip_reason: SkipReason | None = None,
    message: str | None = None,
    **overrides: Any,
) -> SetupActionResult:
    """Create a ``SetupActionResult``.

    Extra keyword arguments (``action``, ``installed_version``,
    ``available_version``, ``cli_command``) are forwarded to the constructor.
    """
    return SetupActionResult(
        action=overrides.get('action') or make_action(),
        success=success,
        skipped=skipped,
        skip_reason=skip_reason,
        message=message,
        installed_version=overrides.get('installed_version'),
        available_version=overrides.get('available_version'),
        cli_command=overrides.get('cli_command'),
    )
