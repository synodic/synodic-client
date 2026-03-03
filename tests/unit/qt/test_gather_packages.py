"""Tests for ToolsView._gather_packages global + per-directory queries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from packaging.version import Version
from porringer.core.schema import Package, PackageRelation, PackageRelationKind
from porringer.schema import ManifestDirectory
from porringer.schema.plugin import PluginInfo, PluginKind
from PySide6.QtWidgets import QLabel, QPushButton

from synodic_client.application.screen.screen import (
    FilterChip,
    PackageEntry,
    PluginKindHeader,
    PluginProviderHeader,
    PluginRow,
    PluginRowData,
    ProjectChildRow,
    ProjectInstance,
    ToolsView,
)
from synodic_client.resolution import ResolvedConfig

# Named constants for expected counts (avoids PLR2004)
_EXPECTED_PROJECT_INSTANCES = 2
_EXPECTED_VISIBLE_ROWS_ALL = 3
_EXPECTED_VISIBLE_ROWS_PIPX = 2


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
        auto_apply=True,
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

        async def _mock_list(plugin_name: str, project_path: Path | None = None, **kwargs) -> list[Package]:
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

        async def _mock_list(plugin_name: str, project_path: Path | None = None, **kwargs) -> list[Package]:
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

        async def _mock_list(plugin_name: str, project_path: Path | None = None, **kwargs) -> list[Package]:
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


# ---------------------------------------------------------------------------
# _build_display_packages
# ---------------------------------------------------------------------------


class TestBuildDisplayPackages:
    """Verify the two-tier display model built from raw PackageEntry lists."""

    @staticmethod
    def test_global_only_package() -> None:
        """A package from the global query has is_global=True and no project instances."""
        entries = [PackageEntry(name='ruff', version='0.8.0')]
        result = ToolsView._build_display_packages(entries, set())

        assert len(result) == 1
        pkg = result[0]
        assert pkg.name == 'ruff'
        assert pkg.is_global is True
        assert pkg.global_version == '0.8.0'
        assert pkg.project_instances == []

    @staticmethod
    def test_project_only_package() -> None:
        """A package found only in a project venv is not global."""
        entries = [
            PackageEntry(
                name='cppython',
                version='0.9.15.dev3',
                project_label='periapsis',
                project_path='/projects/periapsis',
            ),
        ]
        result = ToolsView._build_display_packages(entries, set())

        assert len(result) == 1
        pkg = result[0]
        assert pkg.name == 'cppython'
        assert pkg.is_global is False
        assert pkg.global_version is None
        assert len(pkg.project_instances) == 1
        assert pkg.project_instances[0].project_label == 'periapsis'
        assert pkg.project_instances[0].project_path == '/projects/periapsis'

    @staticmethod
    def test_both_global_and_project() -> None:
        """A package found globally AND in a project has both fields set."""
        entries = [
            PackageEntry(name='ruff', version='0.8.0'),
            PackageEntry(
                name='ruff',
                version='0.7.0',
                project_label='myproject',
                project_path='/projects/myproject',
            ),
        ]
        result = ToolsView._build_display_packages(entries, set())

        assert len(result) == 1
        pkg = result[0]
        assert pkg.is_global is True
        assert pkg.global_version == '0.8.0'
        assert len(pkg.project_instances) == 1
        assert pkg.project_instances[0].version == '0.7.0'

    @staticmethod
    def test_transitive_dependency_marked() -> None:
        """Project-scoped packages not in the manifest are marked transitive."""
        entries = [
            PackageEntry(
                name='cppython',
                version='0.9.15.dev3',
                project_label='periapsis',
                project_path='/projects/periapsis',
            ),
        ]
        # 'cppython' is NOT in the manifest set → transitive
        result = ToolsView._build_display_packages(entries, set())
        assert result[0].project_instances[0].is_transitive is True

    @staticmethod
    def test_manifest_declared_not_transitive() -> None:
        """Project-scoped packages in the manifest are NOT marked transitive."""
        entries = [
            PackageEntry(
                name='cppython',
                version='0.9.15.dev3',
                project_label='periapsis',
                project_path='/projects/periapsis',
            ),
        ]
        result = ToolsView._build_display_packages(entries, {'cppython'})
        assert result[0].project_instances[0].is_transitive is False

    @staticmethod
    def test_multiple_projects_same_package() -> None:
        """Same package in multiple projects creates multiple ProjectInstances."""
        entries = [
            PackageEntry(
                name='requests',
                version='2.31.0',
                project_label='project-a',
                project_path='/projects/a',
            ),
            PackageEntry(
                name='requests',
                version='2.30.0',
                project_label='project-b',
                project_path='/projects/b',
            ),
        ]
        result = ToolsView._build_display_packages(entries, set())

        assert len(result) == 1
        pkg = result[0]
        assert len(pkg.project_instances) == _EXPECTED_PROJECT_INSTANCES
        labels = {pi.project_label for pi in pkg.project_instances}
        assert labels == {'project-a', 'project-b'}

    @staticmethod
    def test_deduplicates_same_project_path() -> None:
        """Duplicate entries for the same project_path produce one instance."""
        entries = [
            PackageEntry(
                name='ruff',
                version='0.8.0',
                project_label='myproject',
                project_path='/projects/myproject',
            ),
            PackageEntry(
                name='ruff',
                version='0.8.0',
                project_label='myproject',
                project_path='/projects/myproject',
            ),
        ]
        result = ToolsView._build_display_packages(entries, set())
        assert len(result[0].project_instances) == 1

    @staticmethod
    def test_host_tool_preserved() -> None:
        """The host_tool from the first entry is carried through."""
        entries = [
            PackageEntry(name='cppython', version='0.5.0', host_tool='pdm'),
        ]
        result = ToolsView._build_display_packages(entries, set())
        assert result[0].host_tool == 'pdm'

    @staticmethod
    def test_empty_input() -> None:
        """Empty input returns empty list."""
        result = ToolsView._build_display_packages([], set())
        assert result == []


# ---------------------------------------------------------------------------
# ProjectChildRow
# ---------------------------------------------------------------------------


class TestProjectChildRow:
    """Verify the ProjectChildRow widget renders and emits signals."""

    @staticmethod
    def _make_instance(*, transitive: bool = False) -> ProjectChildRow:
        return ProjectChildRow(
            ProjectInstance(
                project_label='periapsis',
                project_path='/projects/periapsis',
                version='0.9.15.dev3',
                is_transitive=transitive,
            ),
            package_name='cppython',
        )

    def test_navigate_signal_emitted(self) -> None:
        """Clicking the navigate button emits the project path."""
        row = self._make_instance()
        spy = MagicMock()
        row.navigate_to_project.connect(spy)

        # Find the navigate button (→)
        nav_btns = [w for w in row.findChildren(QPushButton) if w.text() == '\u2192']
        assert len(nav_btns) == 1
        nav_btns[0].click()
        spy.assert_called_once_with('/projects/periapsis')

    def test_transitive_label_shown(self) -> None:
        """Transitive instances show a (transitive) label."""
        row = self._make_instance(transitive=True)
        labels = [w for w in row.findChildren(QLabel) if w.text() == '(transitive)']
        assert len(labels) == 1

    def test_transitive_label_hidden_when_not_transitive(self) -> None:
        """Non-transitive instances do not show a (transitive) label."""
        row = self._make_instance(transitive=False)
        labels = [w for w in row.findChildren(QLabel) if w.text() == '(transitive)']
        assert len(labels) == 0


# ---------------------------------------------------------------------------
# FilterChip
# ---------------------------------------------------------------------------


class TestFilterChip:
    """Verify the FilterChip widget renders and emits toggled signals."""

    @staticmethod
    def test_chip_starts_checked() -> None:
        """Filter chips start in the checked (active) state."""
        chip = FilterChip('pipx')
        assert chip.isChecked()
        assert chip.text() == 'pipx'

    @staticmethod
    def test_toggling_emits_signal() -> None:
        """Toggling a chip emits the plugin name and new state."""
        chip = FilterChip('uv')
        spy = MagicMock()
        chip.toggled_with_name.connect(spy)

        chip.setChecked(False)
        spy.assert_called_once_with('uv', False)

    @staticmethod
    def test_recheck_emits_true() -> None:
        """Re-checking a chip emits True."""
        chip = FilterChip('pip')
        spy = MagicMock()
        chip.setChecked(False)
        chip.toggled_with_name.connect(spy)
        chip.setChecked(True)
        spy.assert_called_once_with('pip', True)


# ---------------------------------------------------------------------------
# Search & filter integration (ToolsView._apply_filter)
# ---------------------------------------------------------------------------


class TestSearchFilter:
    """Verify the search and filter logic on ToolsView."""

    @staticmethod
    def _make_view() -> ToolsView:
        """Build a ToolsView with a mock porringer."""
        porringer = _make_porringer()
        config = _make_config()
        return ToolsView(porringer, config)

    @staticmethod
    def _populate_section_widgets(view: ToolsView) -> None:
        """Manually inject section widgets simulating a two-plugin tree.

        Structure:
          KindHeader(TOOL)
            ProviderHeader(pipx)
              PluginRow(ruff, plugin=pipx)
              PluginRow(pdm, plugin=pipx)
            ProviderHeader(uv)
              PluginRow(mypy, plugin=uv)
        """
        kind_hdr = PluginKindHeader(PluginKind.TOOL)
        view._section_widgets.append(kind_hdr)
        view._container_layout.insertWidget(0, kind_hdr)

        pipx_info = PluginInfo(
            name='pipx', kind=PluginKind.TOOL, version=Version('0.1.0'), installed=True, tool_version=Version('1.0.0')
        )
        pipx_hdr = PluginProviderHeader(pipx_info, True)
        view._section_widgets.append(pipx_hdr)
        view._container_layout.insertWidget(1, pipx_hdr)

        ruff_row = PluginRow(PluginRowData(name='ruff', plugin_name='pipx'))
        view._section_widgets.append(ruff_row)
        view._container_layout.insertWidget(2, ruff_row)

        pdm_row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx'))
        view._section_widgets.append(pdm_row)
        view._container_layout.insertWidget(3, pdm_row)

        uv_info = PluginInfo(
            name='uv', kind=PluginKind.TOOL, version=Version('0.1.0'), installed=True, tool_version=Version('2.0.0')
        )
        uv_hdr = PluginProviderHeader(uv_info, True)
        view._section_widgets.append(uv_hdr)
        view._container_layout.insertWidget(4, uv_hdr)

        mypy_row = PluginRow(PluginRowData(name='mypy', plugin_name='uv'))
        view._section_widgets.append(mypy_row)
        view._container_layout.insertWidget(5, mypy_row)

        # Build chips
        view._rebuild_chips()

    def test_search_hides_non_matching_rows(self) -> None:
        """Typing a search term hides rows whose names don't match."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._search_input.setText('ruff')

        visible_rows = [w for w in view._section_widgets if isinstance(w, PluginRow) and not w.isHidden()]
        assert len(visible_rows) == 1
        assert visible_rows[0]._package_name == 'ruff'

    def test_empty_search_shows_all(self) -> None:
        """Clearing the search bar makes all rows visible again."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._search_input.setText('ruff')
        view._search_input.setText('')

        visible_rows = [w for w in view._section_widgets if isinstance(w, PluginRow) and not w.isHidden()]
        assert len(visible_rows) == _EXPECTED_VISIBLE_ROWS_ALL

    def test_chip_deselection_hides_plugin(self) -> None:
        """Deselecting a chip hides all rows from that plugin."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._filter_chips['pipx'].setChecked(False)

        visible_rows = [w for w in view._section_widgets if isinstance(w, PluginRow) and not w.isHidden()]
        assert len(visible_rows) == 1
        assert visible_rows[0]._package_name == 'mypy'

    def test_chip_reselection_restores(self) -> None:
        """Re-checking a chip restores the plugin's rows."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._filter_chips['pipx'].setChecked(False)
        view._filter_chips['pipx'].setChecked(True)

        visible_rows = [w for w in view._section_widgets if isinstance(w, PluginRow) and not w.isHidden()]
        assert len(visible_rows) == _EXPECTED_VISIBLE_ROWS_ALL

    def test_search_plus_chip_filter(self) -> None:
        """Search and chip filtering compose — only matching rows in active plugins survive."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._filter_chips['uv'].setChecked(False)
        view._search_input.setText('pdm')

        visible_rows = [w for w in view._section_widgets if isinstance(w, PluginRow) and not w.isHidden()]
        assert len(visible_rows) == 1
        assert visible_rows[0]._package_name == 'pdm'

    def test_kind_header_hidden_when_no_children_visible(self) -> None:
        """Kind headers hide when all their children are filtered out."""
        view = self._make_view()
        self._populate_section_widgets(view)

        # Hide both plugins
        view._filter_chips['pipx'].setChecked(False)
        view._filter_chips['uv'].setChecked(False)

        hidden_kinds = [w for w in view._section_widgets if isinstance(w, PluginKindHeader) and w.isHidden()]
        assert len(hidden_kinds) == 1

    def test_provider_hidden_when_search_matches_nothing(self) -> None:
        """A provider header hides when no child rows match the search."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._search_input.setText('mypy')

        visible_providers = [
            w for w in view._section_widgets if isinstance(w, PluginProviderHeader) and not w.isHidden()
        ]
        assert len(visible_providers) == 1
        assert visible_providers[0]._plugin_name == 'uv'

    def test_search_matches_plugin_name(self) -> None:
        """Searching by plugin name shows all rows from that plugin."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._search_input.setText('pipx')

        visible_rows = [w for w in view._section_widgets if isinstance(w, PluginRow) and not w.isHidden()]
        assert len(visible_rows) == _EXPECTED_VISIBLE_ROWS_PIPX
        names = {w._package_name for w in visible_rows}
        assert names == {'ruff', 'pdm'}

    def test_deselected_chips_preserved_across_rebuild(self) -> None:
        """_rebuild_chips preserves deselected state from self._deselected_plugins."""
        view = self._make_view()
        self._populate_section_widgets(view)

        view._filter_chips['pipx'].setChecked(False)
        assert 'pipx' in view._deselected_plugins

        # Simulate refresh by rebuilding chips
        view._rebuild_chips()
        assert not view._filter_chips['pipx'].isChecked()
        assert view._filter_chips['uv'].isChecked()
