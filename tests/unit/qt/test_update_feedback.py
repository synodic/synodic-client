"""Tests for update-detection and feedback on ToolsView widgets."""

from __future__ import annotations

from unittest.mock import MagicMock

from packaging.version import Version
from porringer.schema import PluginInfo
from porringer.schema.plugin import PluginKind

from synodic_client.application.screen.plugin_row import PluginProviderHeader, PluginRow
from synodic_client.application.screen.schema import PluginRowData


def _make_plugin(
    name: str = 'pipx',
    kind: PluginKind = PluginKind.TOOL,
    installed: bool = True,
    tool_version: str | None = '1.0.0',
) -> PluginInfo:
    """Build a minimal PluginInfo for tests."""
    return PluginInfo(
        name=name,
        kind=kind,
        version=Version('0.1.0'),
        installed=installed,
        tool_version=Version(tool_version) if tool_version else None,
    )


# ---------------------------------------------------------------------------
# PluginProviderHeader
# ---------------------------------------------------------------------------


class TestPluginProviderHeaderUpdates:
    """Tests for the update-visibility and feedback on PluginProviderHeader."""

    @staticmethod
    def test_update_button_hidden_by_default() -> None:
        """Update button should be invisible when has_updates is False."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=True,
            has_updates=False,
        )
        assert header._update_btn is not None
        assert header._update_btn.isHidden()

    @staticmethod
    def test_update_button_visible_when_updates_available() -> None:
        """Update button should be visible when has_updates is True."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=True,
            has_updates=True,
        )
        assert header._update_btn is not None
        assert not header._update_btn.isHidden()

    @staticmethod
    def test_set_updating_true_disables_button() -> None:
        """set_updating(True) should show 'Updating…' and disable."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=True,
            has_updates=True,
        )
        header.set_updating(True)
        assert header._update_btn is not None
        assert header._update_btn.text() == 'Updating\u2026'
        assert not header._update_btn.isEnabled()

    @staticmethod
    def test_set_updating_false_restores_button() -> None:
        """set_updating(False) should restore 'Update' and re-enable."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=True,
            has_updates=True,
        )
        header.set_updating(True)
        header.set_updating(False)
        assert header._update_btn is not None
        assert header._update_btn.text() == 'Update'
        assert header._update_btn.isEnabled()

    @staticmethod
    def test_set_updating_noop_without_controls() -> None:
        """set_updating should be a no-op when controls are not shown."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=False,
        )
        # Should not raise
        header.set_updating(True)
        assert header._update_btn is None

    @staticmethod
    def test_update_requested_signal() -> None:
        """Clicking the update button emits update_requested(plugin_name)."""
        header = PluginProviderHeader(
            _make_plugin(name='uv'),
            auto_update=True,
            show_controls=True,
            has_updates=True,
        )
        spy = MagicMock()
        header.update_requested.connect(spy)
        assert header._update_btn is not None
        header._update_btn.click()
        spy.assert_called_once_with('uv')

    @staticmethod
    def test_set_checking_shows_spinner() -> None:
        """set_checking(True) starts the inline spinner and hides update button."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=True,
            has_updates=True,
        )
        header.set_checking(True)
        assert header._checking_spinner is not None
        assert not header._checking_spinner.isHidden()
        assert header._update_btn is not None
        assert header._update_btn.isHidden()

    @staticmethod
    def test_set_checking_false_hides_spinner() -> None:
        """set_checking(False) stops the spinner."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=True,
            has_updates=True,
        )
        header.set_checking(True)
        header.set_checking(False)
        assert header._checking_spinner is not None
        assert header._checking_spinner.isHidden()

    @staticmethod
    def test_set_checking_noop_without_controls() -> None:
        """set_checking is a no-op when controls are not shown."""
        header = PluginProviderHeader(
            _make_plugin(),
            auto_update=True,
            show_controls=False,
        )
        header.set_checking(True)
        assert header._checking_spinner is None


# ---------------------------------------------------------------------------
# PluginRow
# ---------------------------------------------------------------------------


class TestPluginRowUpdates:
    """Tests for the per-package update button on PluginRow."""

    @staticmethod
    def test_no_update_button_by_default() -> None:
        """With has_update=False the update button exists but is hidden."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', show_toggle=True))
        assert row._update_btn is not None
        assert row._update_btn.isHidden()

    @staticmethod
    def test_update_button_visible_when_has_update() -> None:
        """With has_update=True the row shows an inline update button."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                show_toggle=True,
                has_update=True,
            )
        )
        assert row._update_btn is not None
        assert not row._update_btn.isHidden()

    @staticmethod
    def test_set_updating_true_disables() -> None:
        """set_updating(True) shows 'Updating…' and disables."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                show_toggle=True,
                has_update=True,
            )
        )
        row.set_updating(True)
        assert row._update_btn is not None
        assert row._update_btn.text() == 'Updating\u2026'
        assert not row._update_btn.isEnabled()

    @staticmethod
    def test_set_updating_false_restores() -> None:
        """set_updating(False) restores 'Update' and re-enables."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                show_toggle=True,
                has_update=True,
            )
        )
        row.set_updating(True)
        row.set_updating(False)
        assert row._update_btn is not None
        assert row._update_btn.text() == 'Update'
        assert row._update_btn.isEnabled()

    @staticmethod
    def test_update_requested_signal() -> None:
        """Clicking update emits update_requested(plugin_name, package_name)."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                show_toggle=True,
                has_update=True,
            )
        )
        spy = MagicMock()
        row.update_requested.connect(spy)
        assert row._update_btn is not None
        row._update_btn.click()
        spy.assert_called_once_with('pipx', 'pdm')

    @staticmethod
    def test_set_updating_noop_without_button() -> None:
        """set_updating works even when has_update was False (button is hidden)."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', show_toggle=True))
        # Should not raise
        row.set_updating(True)
        assert row._update_btn is not None

    @staticmethod
    def test_set_checking_shows_spinner() -> None:
        """set_checking(True) starts the inline spinner and hides update button."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                show_toggle=True,
                has_update=True,
            )
        )
        row.set_checking(True)
        assert row._checking_spinner is not None
        assert not row._checking_spinner.isHidden()
        assert row._update_btn is not None
        assert row._update_btn.isHidden()

    @staticmethod
    def test_set_checking_false_hides_spinner() -> None:
        """set_checking(False) stops the spinner."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                show_toggle=True,
                has_update=True,
            )
        )
        row.set_checking(True)
        row.set_checking(False)
        assert row._checking_spinner is not None
        assert row._checking_spinner.isHidden()

    @staticmethod
    def test_set_checking_noop_without_toggle() -> None:
        """set_checking is a no-op when show_toggle is False (no spinner created)."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx'))
        row.set_checking(True)
        assert row._checking_spinner is None

    @staticmethod
    def test_host_tool_label_shown_when_set() -> None:
        """A host_tool value adds a '\u2192 <host>' label after the name."""
        row = PluginRow(PluginRowData(name='cppython', plugin_name='pipx', host_tool='pdm'))
        assert row._host_label is not None
        assert row._host_label.text() == '\u2192 pdm'
        assert not row._host_label.isHidden()

    @staticmethod
    def test_host_tool_label_absent_when_empty() -> None:
        """No host label is created when host_tool is empty."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx'))
        assert row._host_label is None


# ---------------------------------------------------------------------------
# PluginRow — remove button
# ---------------------------------------------------------------------------


class TestPluginRowRemove:
    """Tests for the per-package remove button on PluginRow."""

    @staticmethod
    def test_remove_button_present() -> None:
        """A remove button is always created on PluginRow."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=True))
        assert row._remove_btn is not None

    @staticmethod
    def test_remove_button_enabled_for_global() -> None:
        """The remove button is enabled when is_global=True."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=True))
        assert row._remove_btn is not None
        assert row._remove_btn.isEnabled()

    @staticmethod
    def test_remove_button_disabled_for_manifest() -> None:
        """The remove button is disabled when is_global=False (manifest-referenced)."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=False, project='myproject'))
        assert row._remove_btn is not None
        assert not row._remove_btn.isEnabled()

    @staticmethod
    def test_remove_button_tooltip_global() -> None:
        """Tooltip for global packages says 'Remove <name>'."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=True))
        assert row._remove_btn is not None
        assert 'Remove pdm' in row._remove_btn.toolTip()

    @staticmethod
    def test_remove_button_tooltip_manifest() -> None:
        """Tooltip for manifest packages mentions the project name."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=False, project='myproject'))
        assert row._remove_btn is not None
        assert 'myproject' in row._remove_btn.toolTip()

    @staticmethod
    def test_remove_requested_signal() -> None:
        """Clicking remove emits remove_requested(plugin_name, package_name)."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=True))
        spy = MagicMock()
        row.remove_requested.connect(spy)
        assert row._remove_btn is not None
        row._remove_btn.click()
        spy.assert_called_once_with('pipx', 'pdm')

    @staticmethod
    def test_remove_signal_not_emitted_when_disabled() -> None:
        """Clicking a disabled remove button does not emit remove_requested."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=False, project='myproject'))
        spy = MagicMock()
        row.remove_requested.connect(spy)
        assert row._remove_btn is not None
        row._remove_btn.click()
        spy.assert_not_called()

    @staticmethod
    def test_set_removing_true() -> None:
        """set_removing(True) shows 'Removing\u2026' and disables."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=True))
        row.set_removing(True)
        assert row._remove_btn is not None
        assert row._remove_btn.text() == 'Removing\u2026'
        assert not row._remove_btn.isEnabled()

    @staticmethod
    def test_set_removing_false() -> None:
        """set_removing(False) restores '\u00d7' and re-enables."""
        row = PluginRow(PluginRowData(name='pdm', plugin_name='pipx', is_global=True))
        row.set_removing(True)
        row.set_removing(False)
        assert row._remove_btn is not None
        assert row._remove_btn.text() == '\u00d7'
        assert row._remove_btn.isEnabled()

    @staticmethod
    def test_project_paths_stored() -> None:
        """PluginRow stores project_paths for navigation."""
        row = PluginRow(
            PluginRowData(
                name='pdm',
                plugin_name='pipx',
                is_global=False,
                project='myproject',
                project_paths=['/fake/project'],
            )
        )
        assert row._project_paths == ['/fake/project']
