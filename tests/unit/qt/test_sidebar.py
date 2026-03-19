"""Tests for the ManifestSidebar and ManifestItem widgets."""

from __future__ import annotations

from pathlib import Path

import pytest

from synodic_client.application.screen.schema import PreviewPhase
from synodic_client.application.screen.sidebar import ManifestItem, ManifestSidebar
from synodic_client.application.theme import SIDEBAR_WIDTH

_EXPECTED_DIRECTORY_COUNT = 2


# ---------------------------------------------------------------------------
# ManifestItem
# ---------------------------------------------------------------------------


class TestManifestItemInit:
    """Basic construction and property access."""

    @staticmethod
    def test_path_property(tmp_path: Path) -> None:
        """Verify the path property returns the construction path."""
        item = ManifestItem(tmp_path, 'proj')
        assert item.path == tmp_path

    @staticmethod
    def test_default_not_selected(tmp_path: Path) -> None:
        """Verify a new item is not selected by default."""
        item = ManifestItem(tmp_path, 'proj')
        assert item.selected is False

    @staticmethod
    def test_display_name_uses_explicit_name(tmp_path: Path) -> None:
        """Verify label uses the explicit display name when provided."""
        item = ManifestItem(tmp_path, 'My Project')
        assert item._label.text() == 'My Project'

    @staticmethod
    def test_display_name_falls_back_to_path_name(tmp_path: Path) -> None:
        """Verify label falls back to the path stem when no name is given."""
        item = ManifestItem(tmp_path)
        assert item._label.text() == tmp_path.name

    @staticmethod
    def test_tooltip_shows_full_path(tmp_path: Path) -> None:
        """Verify the tooltip shows the full path string."""
        item = ManifestItem(tmp_path, 'proj')
        assert item.toolTip() == str(tmp_path)


class TestManifestItemSelection:
    """Selection state changes."""

    @staticmethod
    def test_set_selected_true(tmp_path: Path) -> None:
        """Verify setting selected to True updates the state."""
        item = ManifestItem(tmp_path, 'proj')
        item.selected = True
        assert item.selected is True

    @staticmethod
    def test_set_selected_false(tmp_path: Path) -> None:
        """Verify toggling selected back to False works."""
        item = ManifestItem(tmp_path, 'proj')
        item.selected = True
        item.selected = False
        assert item.selected is False


class TestManifestItemPhase:
    """Phase indicator updates."""

    @staticmethod
    @pytest.mark.parametrize(
        ('phase', 'expected_text'),
        [
            (PreviewPhase.LOADING, 'Loading\u2026'),
            (PreviewPhase.READY, 'Ready'),
            (PreviewPhase.ERROR, 'Error'),
            (PreviewPhase.INSTALLING, 'Installing\u2026'),
            (PreviewPhase.DONE, 'Done'),
        ],
        ids=['loading', 'ready', 'error', 'installing', 'done'],
    )
    def test_phase_label(tmp_path: Path, phase: PreviewPhase, expected_text: str) -> None:
        """Verify phase label text matches the phase enum."""
        item = ManifestItem(tmp_path, 'proj')
        item.set_phase(phase)
        assert not item._phase_label.isHidden()
        assert item._phase_label.text() == expected_text


class TestManifestItemSignals:
    """Signal emission."""

    @staticmethod
    def test_clicked_on_mouse_press(tmp_path: Path) -> None:
        """Verify clicked signal fires on mousePressEvent."""
        item = ManifestItem(tmp_path, 'proj')
        received: list[Path] = []
        item.clicked.connect(received.append)
        item.mousePressEvent(None)
        assert received == [tmp_path]

    @staticmethod
    def test_remove_requested_on_close(tmp_path: Path) -> None:
        """Verify remove_requested signal fires on close button click."""
        item = ManifestItem(tmp_path, 'proj')
        received: list[Path] = []
        item.remove_requested.connect(received.append)
        item._close_btn.click()
        assert received == [tmp_path]


# ---------------------------------------------------------------------------
# ManifestSidebar
# ---------------------------------------------------------------------------


class TestManifestSidebarInit:
    """Basic construction."""

    @staticmethod
    def test_default_no_items() -> None:
        """Verify a new sidebar has no selection."""
        sidebar = ManifestSidebar()
        assert sidebar.selected_path is None

    @staticmethod
    def test_fixed_width() -> None:
        """Verify the sidebar minimum width matches the theme constant."""
        sidebar = ManifestSidebar()
        assert sidebar.minimumWidth() == SIDEBAR_WIDTH


class TestManifestSidebarSetDirectories:
    """Populating the sidebar with items."""

    @staticmethod
    def test_creates_items(tmp_path: Path) -> None:
        """Verify set_directories creates the expected number of items."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        d2 = tmp_path / 'b'
        sidebar.set_directories([(d1, 'A', True), (d2, 'B', True)])
        assert len(sidebar._items) == _EXPECTED_DIRECTORY_COUNT

    @staticmethod
    def test_replaces_previous_items(tmp_path: Path) -> None:
        """Verify set_directories replaces prior items completely."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        d2 = tmp_path / 'b'
        d3 = tmp_path / 'c'
        sidebar.set_directories([(d1, 'A', True), (d2, 'B', True)])
        sidebar.set_directories([(d3, 'C', True)])
        assert len(sidebar._items) == 1
        assert sidebar._items[0].path == d3

    @staticmethod
    def test_clears_selection(tmp_path: Path) -> None:
        """Verify set_directories resets the selection to None."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        sidebar.set_directories([(d1, 'A', True)])
        sidebar.select(d1)
        sidebar.set_directories([(d1, 'A', True)])
        assert sidebar.selected_path is None


class TestManifestSidebarSelect:
    """Selection behaviour."""

    @staticmethod
    def test_select_by_path(tmp_path: Path) -> None:
        """Verify selecting a path updates selected_path."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        d2 = tmp_path / 'b'
        sidebar.set_directories([(d1, 'A', True), (d2, 'B', True)])
        sidebar.select(d2)
        assert sidebar.selected_path == d2

    @staticmethod
    def test_select_none_falls_back_to_first(tmp_path: Path) -> None:
        """Verify selecting None falls back to the first item."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        d2 = tmp_path / 'b'
        sidebar.set_directories([(d1, 'A', True), (d2, 'B', True)])
        sidebar.select(None)
        assert sidebar.selected_path == d1

    @staticmethod
    def test_select_missing_path_falls_back_to_first(tmp_path: Path) -> None:
        """Verify selecting a nonexistent path falls back to the first item."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        sidebar.set_directories([(d1, 'A', True)])
        sidebar.select(tmp_path / 'nonexistent')
        assert sidebar.selected_path == d1

    @staticmethod
    def test_select_emits_signal(tmp_path: Path) -> None:
        """Verify select emits selection_changed with the selected path."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        sidebar.set_directories([(d1, 'A', True)])
        received: list[Path] = []
        sidebar.selection_changed.connect(received.append)
        sidebar.select(d1)
        assert received == [d1]


class TestManifestSidebarGetItem:
    """Finding items by path."""

    @staticmethod
    def test_found(tmp_path: Path) -> None:
        """Verify get_item returns the item matching the given path."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        sidebar.set_directories([(d1, 'A', True)])
        item = sidebar.get_item(d1)
        assert item is not None
        assert item.path == d1

    @staticmethod
    def test_not_found(tmp_path: Path) -> None:
        """Verify get_item returns None for an unknown path."""
        sidebar = ManifestSidebar()
        sidebar.set_directories([])
        assert sidebar.get_item(tmp_path / 'x') is None


class TestManifestSidebarSignals:
    """Signal forwarding from child items and the Add button."""

    @staticmethod
    def test_add_requested() -> None:
        """Verify add_requested fires when the add button is clicked."""
        sidebar = ManifestSidebar()
        received: list[bool] = []
        sidebar.add_requested.connect(lambda: received.append(True))
        sidebar._add_btn.click()
        assert received == [True]

    @staticmethod
    def test_remove_requested_forwarded(tmp_path: Path) -> None:
        """Verify remove_requested is forwarded from child items."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        sidebar.set_directories([(d1, 'A', True)])
        received: list[Path] = []
        sidebar.remove_requested.connect(received.append)
        # Simulate the item's close button click
        sidebar._items[0]._close_btn.click()
        assert received == [d1]

    @staticmethod
    def test_selection_changed_on_item_click(tmp_path: Path) -> None:
        """Verify selection_changed fires when an item is clicked."""
        sidebar = ManifestSidebar()
        d1 = tmp_path / 'a'
        d2 = tmp_path / 'b'
        sidebar.set_directories([(d1, 'A', True), (d2, 'B', True)])
        received: list[Path] = []
        sidebar.selection_changed.connect(received.append)
        sidebar._items[1].mousePressEvent(None)
        assert received == [d2]


class TestManifestSidebarSetEnabled:
    """Enabling and disabling the sidebar."""

    @staticmethod
    def test_disable_add_button() -> None:
        """Verify disabling the sidebar disables the add button."""
        sidebar = ManifestSidebar()
        sidebar.set_enabled(False)
        assert not sidebar._add_btn.isEnabled()

    @staticmethod
    def test_reenable() -> None:
        """Verify re-enabling the sidebar re-enables the add button."""
        sidebar = ManifestSidebar()
        sidebar.set_enabled(False)
        sidebar.set_enabled(True)
        assert sidebar._add_btn.isEnabled()
