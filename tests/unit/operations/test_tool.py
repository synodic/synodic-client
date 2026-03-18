"""Tests for operations.tool module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from synodic_client.operations.schema import UpdateResult
from synodic_client.operations.tool import (
    check_tool_updates,
    remove_package,
    resolve_auto_update_scope,
    update_tool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action_completed(
    *,
    installer: str,
    package_name: str,
    skip_reason: object,
    available_version: str = '',
) -> MagicMock:
    """Build a mock ActionCompletedEvent."""
    event = MagicMock()
    event.result.skip_reason = skip_reason
    event.result.action.installer = installer
    event.result.action.package.name = package_name
    event.result.available_version = available_version
    return event


def _make_manifest_dir(path: str) -> MagicMock:
    """Build a mock ManifestDirectory."""
    md = MagicMock()
    md.path = path
    return md


# ---------------------------------------------------------------------------
# check_tool_updates
# ---------------------------------------------------------------------------


class TestCheckToolUpdates:
    """Tests for check_tool_updates()."""

    @staticmethod
    def test_empty_directories() -> None:
        """No directories → empty dict."""
        api = MagicMock()
        result = asyncio.run(check_tool_updates(api, []))
        assert result == {}

    @staticmethod
    def test_detects_update_available(tmp_path: Path) -> None:
        """Finds packages with UPDATE_AVAILABLE skip reason."""
        from porringer.schema import ActionCompletedEvent, SkipReason

        # Create a real manifest file so the path check succeeds
        manifest_dir = tmp_path / 'proj'
        manifest_dir.mkdir()

        api = MagicMock()
        api.sync.manifest_filenames.return_value = ['porringer.json']
        (manifest_dir / 'porringer.json').write_text('{}')

        event = _make_action_completed(
            installer='pip',
            package_name='requests',
            skip_reason=SkipReason.UPDATE_AVAILABLE,
            available_version='2.32.0',
        )
        # Make the event pass isinstance check
        event.__class__ = ActionCompletedEvent

        async def _stream(*_a: object, **_kw: object):
            yield event

        api.sync.execute_stream = _stream

        md = _make_manifest_dir(str(manifest_dir))
        result = asyncio.run(check_tool_updates(api, [md]))
        assert result == {'pip': {'requests': '2.32.0'}}

    @staticmethod
    def test_skips_directory_without_manifest(tmp_path: Path) -> None:
        """Directories without a manifest file are skipped silently."""
        manifest_dir = tmp_path / 'empty'
        manifest_dir.mkdir()

        api = MagicMock()
        api.sync.manifest_filenames.return_value = ['porringer.json']

        md = _make_manifest_dir(str(manifest_dir))
        result = asyncio.run(check_tool_updates(api, [md]))
        assert result == {}


# ---------------------------------------------------------------------------
# update_tool
# ---------------------------------------------------------------------------


class TestUpdateTool:
    """Tests for update_tool()."""

    @staticmethod
    def test_single_package_success() -> None:
        """Upgrading a specific package that succeeds."""
        api = MagicMock()
        action_result = MagicMock()
        action_result.skipped = False
        action_result.success = True
        action_result.installed_version = '2.31.0'
        action_result.available_version = '2.32.0'
        api.package.upgrade = AsyncMock(return_value=action_result)

        result = asyncio.run(update_tool(api, 'pip', 'requests'))
        assert isinstance(result, UpdateResult)
        assert result.packages_updated == ['requests']
        assert result.already_latest == []
        assert result.packages_failed == []
        assert result.version_map == {'requests': ('2.31.0', '2.32.0')}

    @staticmethod
    def test_single_package_already_latest() -> None:
        """Upgrading a package that is already up to date."""
        api = MagicMock()
        action_result = MagicMock()
        action_result.skipped = True
        api.package.upgrade = AsyncMock(return_value=action_result)

        result = asyncio.run(update_tool(api, 'pip', 'requests'))
        assert result.already_latest == ['requests']
        assert result.version_map == {}

    @staticmethod
    def test_single_package_failure() -> None:
        """Upgrading a package that fails."""
        api = MagicMock()
        action_result = MagicMock()
        action_result.skipped = False
        action_result.success = False
        api.package.upgrade = AsyncMock(return_value=action_result)

        result = asyncio.run(update_tool(api, 'pip', 'requests'))
        assert result.packages_failed == ['requests']
        assert result.version_map == {}

    @staticmethod
    def test_single_package_success_no_version_data() -> None:
        """Upgrading succeeds but porringer provides no version info."""
        api = MagicMock()
        action_result = MagicMock()
        action_result.skipped = False
        action_result.success = True
        # Simulate older porringer without version attributes
        del action_result.installed_version
        del action_result.available_version
        api.package.upgrade = AsyncMock(return_value=action_result)

        result = asyncio.run(update_tool(api, 'pip', 'requests'))
        assert result.packages_updated == ['requests']
        assert result.version_map == {}


# ---------------------------------------------------------------------------
# remove_package
# ---------------------------------------------------------------------------


class TestRemovePackage:
    """Tests for remove_package()."""

    @staticmethod
    def test_success() -> None:
        """Successful removal returns True."""
        api = MagicMock()
        api.package.uninstall = AsyncMock(return_value=MagicMock(success=True))
        assert asyncio.run(remove_package(api, 'pip', 'requests')) is True

    @staticmethod
    def test_failure() -> None:
        """Failed removal returns False."""
        api = MagicMock()
        api.package.uninstall = AsyncMock(return_value=MagicMock(success=False))
        assert asyncio.run(remove_package(api, 'pip', 'requests')) is False


# ---------------------------------------------------------------------------
# resolve_auto_update_scope
# ---------------------------------------------------------------------------


class TestResolveAutoUpdateScope:
    """Tests for resolve_auto_update_scope()."""

    @staticmethod
    def test_none_config_returns_none_none() -> None:
        """No config → (None, None) meaning all plugins, all packages."""
        plugins, packages = resolve_auto_update_scope(None, ['pip', 'npm'])
        assert plugins is None
        assert packages is None

    @staticmethod
    def test_disabled_plugin_excluded() -> None:
        """A plugin set to False is excluded from the enabled set."""
        plugins, _ = resolve_auto_update_scope(
            {'pip': False, 'npm': True},
            ['pip', 'npm', 'cargo'],
        )
        assert plugins is not None
        assert 'pip' not in plugins
        assert 'npm' in plugins
        assert 'cargo' in plugins

    @staticmethod
    def test_per_package_entries() -> None:
        """Per-package granularity builds the include set."""
        _, packages = resolve_auto_update_scope(
            {'pip': {'requests': True, 'flask': False}},
            ['pip'],
            manifest_packages=None,
        )
        assert packages is not None
        assert 'requests' in packages
        assert 'flask' not in packages

    @staticmethod
    def test_manifest_packages_included() -> None:
        """Manifest packages are added to the include set."""
        _, packages = resolve_auto_update_scope(
            {},
            ['pip'],
            manifest_packages={'pip': {'requests', 'flask'}},
        )
        assert packages is not None
        assert 'requests' in packages
        assert 'flask' in packages

    @staticmethod
    def test_empty_config_returns_none_none() -> None:
        """Empty mapping → (None, None)."""
        plugins, packages = resolve_auto_update_scope({}, ['pip'])
        assert plugins is None
        assert packages is None
