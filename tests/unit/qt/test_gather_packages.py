"""Tests for ToolsView._gather_packages global + per-directory queries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from porringer.core.schema import Package, PackageRelation, PackageRelationKind
from porringer.schema import ManifestDirectory

from synodic_client.application.screen.screen import ToolsView
from synodic_client.resolution import ResolvedConfig


def _make_config() -> ResolvedConfig:
    """Build a minimal ResolvedConfig for tests."""
    return ResolvedConfig(
        update_source=None,
        update_channel='stable',
        auto_update_interval_minutes=60,
        tool_update_interval_minutes=60,
        plugin_auto_update=None,
        detect_updates=False,
        prerelease_packages=None,
        auto_start=False,
    )


def _make_porringer() -> MagicMock:
    """Build a MagicMock standing in for the porringer API."""
    mock = MagicMock()
    mock.plugin.list = AsyncMock(return_value=[])
    mock.plugin.list_packages = AsyncMock(return_value=[])
    mock.cache.list_directories.return_value = []
    return mock


# ---------------------------------------------------------------------------
# _gather_packages
# ---------------------------------------------------------------------------


class TestGatherPackages:
    """Verify that _gather_packages issues a global query alongside per-directory ones."""

    @staticmethod
    def test_global_query_returns_packages_with_no_directories() -> None:
        """Packages from the global query appear even when no directories are cached."""
        porringer = _make_porringer()
        porringer.plugin.list_packages = AsyncMock(
            return_value=[
                Package(name='pdm', version='2.22.4'),
                Package(name='cppython', version='0.5.0'),
            ],
        )

        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', []))

        assert {e.name for e in result} == {'pdm', 'cppython'}

    @staticmethod
    def test_global_query_returns_packages_with_empty_project_path() -> None:
        """Packages from the global query should have an empty project_path."""
        porringer = _make_porringer()
        porringer.plugin.list_packages = AsyncMock(
            return_value=[
                Package(name='pdm', version='2.22.4'),
            ],
        )

        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', []))

        matching = [e for e in result if e.name == 'pdm']
        assert len(matching) == 1
        assert not matching[0].project_path, 'global packages should have empty project_path'

    @staticmethod
    def test_global_query_called_without_project_path() -> None:
        """The global query must call list_packages with no project_path arg."""
        porringer = _make_porringer()
        porringer.plugin.list_packages = AsyncMock(return_value=[])

        view = ToolsView(porringer, _make_config())
        asyncio.run(view._gather_packages('pipx', []))

        # At least one call should have been made with only plugin_name (no path)
        calls = porringer.plugin.list_packages.call_args_list
        plugin_name_only = 1
        min_args_with_path = 2
        global_calls = [
            c
            for c in calls
            if len(c.args) == plugin_name_only or (len(c.args) >= min_args_with_path and c.args[1] is None)
        ]
        assert len(global_calls) >= 1, f'Expected a global call (no project_path), got: {calls}'

    @staticmethod
    def test_per_directory_queries_still_work() -> None:
        """Per-directory queries continue to run alongside the global query."""
        porringer = _make_porringer()

        async def _mock_list(plugin_name: str, project_path: Path | None = None) -> list[Package]:
            if project_path is None:
                return [Package(name='pdm', version='2.22.4')]
            return [Package(name='mylib', version='1.0.0')]

        porringer.plugin.list_packages = AsyncMock(side_effect=_mock_list)

        directory = ManifestDirectory(path=Path('/fake/project'))
        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', [directory]))

        names = {entry.name for entry in result}
        assert 'pdm' in names, 'global package should be present'
        assert 'mylib' in names, 'per-directory package should be present'

    @staticmethod
    def test_per_directory_packages_carry_project_path() -> None:
        """Per-directory packages should include the directory path as project_path."""
        porringer = _make_porringer()

        async def _mock_list(plugin_name: str, project_path: Path | None = None) -> list[Package]:
            if project_path is None:
                return []
            return [Package(name='mylib', version='1.0.0')]

        porringer.plugin.list_packages = AsyncMock(side_effect=_mock_list)

        directory = ManifestDirectory(path=Path('/fake/project'))
        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', [directory]))

        matching = [e for e in result if e.name == 'mylib']
        assert len(matching) == 1
        assert matching[0].project_path == str(Path('/fake/project')), 'per-directory package should carry project path'

    @staticmethod
    def test_global_packages_have_empty_project_label() -> None:
        """Packages from the global query should have an empty project label."""
        porringer = _make_porringer()
        porringer.plugin.list_packages = AsyncMock(
            return_value=[Package(name='cppython', version='0.5.0')],
        )

        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', []))

        matching = [e for e in result if e.name == 'cppython']
        assert len(matching) == 1
        assert not matching[0].project_label, 'global packages should have empty project label'
        assert matching[0].version == '0.5.0'

    @staticmethod
    def test_global_query_failure_does_not_block_directory_queries() -> None:
        """If the global query fails, per-directory results still come through."""
        porringer = _make_porringer()
        call_count = 0

        async def _mock_list(plugin_name: str, project_path: Path | None = None) -> list[Package]:
            nonlocal call_count
            call_count += 1
            if project_path is None:
                raise RuntimeError('global query failed')
            return [Package(name='django', version='5.0')]

        porringer.plugin.list_packages = AsyncMock(side_effect=_mock_list)

        directory = ManifestDirectory(path=Path('/fake/project'))
        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', [directory]))

        names = {entry.name for entry in result}
        assert 'django' in names
        expected_calls = 2  # one global + one directory
        assert call_count == expected_calls

    @staticmethod
    def test_relation_host_extracted_into_host_tool() -> None:
        """Packages with a PackageRelation populate the host_tool element."""
        porringer = _make_porringer()
        porringer.plugin.list_packages = AsyncMock(
            return_value=[
                Package(
                    name='cppython',
                    version='0.5.0',
                    relation=PackageRelation(
                        host='pdm',
                        kind=PackageRelationKind.INJECTED,
                    ),
                ),
                Package(name='pdm', version='2.22.4'),
            ],
        )

        view = ToolsView(porringer, _make_config())
        result = asyncio.run(view._gather_packages('pipx', []))

        by_name = {entry.name: entry.host_tool for entry in result}
        assert by_name['cppython'] == 'pdm', 'injected package should carry host'
        assert not by_name['pdm'], 'non-injected package should have empty host'


# ---------------------------------------------------------------------------
# _gather_tool_plugins
# ---------------------------------------------------------------------------


class TestGatherToolPlugins:
    """Verify that _gather_tool_plugins discovers PluginManager sub-plugins."""

    @staticmethod
    def test_returns_plugins_keyed_by_host_tool(monkeypatch) -> None:
        """installed_plugins() results are keyed by tool name and returned as PackageEntry."""
        porringer = _make_porringer()
        view = ToolsView(porringer, _make_config())

        # Mock _discover_plugin_managers to return a fake manager
        mock_manager = MagicMock()
        mock_manager.installed_plugins = AsyncMock(
            return_value=[
                Package(
                    name='cppython',
                    version='0.5.0',
                    relation=PackageRelation(host='pdm', kind=PackageRelationKind.PLUGIN),
                ),
            ],
        )
        monkeypatch.setattr(
            ToolsView,
            '_discover_plugin_managers',
            staticmethod(lambda: {'pdm': mock_manager}),
        )

        result = asyncio.run(view._gather_tool_plugins())

        assert 'pdm' in result
        assert len(result['pdm']) == 1
        entry = result['pdm'][0]
        assert entry.name == 'cppython'
        assert not entry.project_label
        assert entry.version == '0.5.0'
        assert entry.host_tool == 'pdm'

    @staticmethod
    def test_empty_when_no_managers(monkeypatch) -> None:
        """Returns empty dict when no PluginManager instances are discovered."""
        porringer = _make_porringer()
        view = ToolsView(porringer, _make_config())
        monkeypatch.setattr(
            ToolsView,
            '_discover_plugin_managers',
            staticmethod(lambda: {}),
        )

        result = asyncio.run(view._gather_tool_plugins())
        assert result == {}

    @staticmethod
    def test_manager_failure_does_not_propagate(monkeypatch) -> None:
        """A failing installed_plugins() call produces an empty entry, not an exception."""
        porringer = _make_porringer()
        view = ToolsView(porringer, _make_config())

        mock_manager = MagicMock()
        mock_manager.installed_plugins = AsyncMock(side_effect=RuntimeError('boom'))
        monkeypatch.setattr(
            ToolsView,
            '_discover_plugin_managers',
            staticmethod(lambda: {'pdm': mock_manager}),
        )

        result = asyncio.run(view._gather_tool_plugins())
        # Should not raise; failed manager produces no entry
        assert 'pdm' not in result

    @staticmethod
    def test_multiple_managers(monkeypatch) -> None:
        """Multiple PluginManager instances are queried in parallel."""
        porringer = _make_porringer()
        view = ToolsView(porringer, _make_config())

        mgr_pdm = MagicMock()
        mgr_pdm.installed_plugins = AsyncMock(
            return_value=[
                Package(
                    name='cppython',
                    version='0.5.0',
                    relation=PackageRelation(host='pdm', kind=PackageRelationKind.PLUGIN),
                ),
            ],
        )
        mgr_poetry = MagicMock()
        mgr_poetry.installed_plugins = AsyncMock(
            return_value=[
                Package(
                    name='poetry-plugin-export',
                    version='1.8.0',
                    relation=PackageRelation(host='poetry', kind=PackageRelationKind.PLUGIN),
                ),
            ],
        )
        monkeypatch.setattr(
            ToolsView,
            '_discover_plugin_managers',
            staticmethod(lambda: {'pdm': mgr_pdm, 'poetry': mgr_poetry}),
        )

        result = asyncio.run(view._gather_tool_plugins())
        assert 'pdm' in result
        assert 'poetry' in result
        assert result['pdm'][0].name == 'cppython'
        assert result['poetry'][0].name == 'poetry-plugin-export'
