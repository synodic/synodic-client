"""Shared package update state registry.

Provides :class:`PackageStateStore`, a centralised record of
per-package update status used by both ToolsView and ProjectsView
so that version/update information discovered in one view is
immediately available to the other.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


@dataclass(slots=True)
class PackageState:
    """Canonical update state for a single package.

    Keyed by ``(signal_key, name)`` inside :class:`PackageStateStore`.
    """

    name: str
    """Package name (e.g. ``"ruff"``)."""

    installed_version: str = ''
    """Currently installed version, or empty if unknown."""

    available_version: str = ''
    """Latest available version, or empty if unknown."""

    has_update: bool = False
    """Whether the package has a newer version available."""


class PackageStateStore(QObject):
    """Shared registry of package update states across views.

    Both ToolsView and ProjectsView write discovered update information
    into the store; each view can then read the canonical state
    regardless of which view made the discovery.

    :attr:`state_changed` is emitted whenever new data arrives so
    listeners can refresh their badges/labels without polling.
    """

    state_changed = Signal()
    """Emitted whenever any package state is created or modified."""

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise with an empty registry."""
        super().__init__(parent)
        self._data: dict[str, dict[str, PackageState]] = {}

    # -- Bulk write (ToolsView check_updates) ----------------------------

    def set_check_results(self, available: dict[str, dict[str, str]]) -> None:
        """Populate from ``check_updates`` results.

        *available* maps ``{signal_key: {package_name: latest_version}}``
        — the same shape previously stored in
        ``ToolsView._updates_available``.
        """
        self._data.clear()
        for key, packages in available.items():
            for pkg_name, latest in packages.items():
                self._data.setdefault(key, {})[pkg_name] = PackageState(
                    name=pkg_name,
                    available_version=latest,
                    has_update=True,
                )
        self.state_changed.emit()

    # -- Single-action write (ProjectsView dry-run) ----------------------

    def record_action_result(
        self,
        signal_key: str,
        pkg_name: str,
        *,
        installed_version: str = '',
        available_version: str = '',
        has_update: bool = False,
    ) -> None:
        """Record a single dry-run result.

        Merges with any existing state so that data discovered by
        different views accumulates rather than overwrites.
        """
        existing = self._data.get(signal_key, {}).get(pkg_name)
        state = PackageState(
            name=pkg_name,
            installed_version=installed_version or (existing.installed_version if existing else ''),
            available_version=available_version or (existing.available_version if existing else ''),
            has_update=has_update or (existing.has_update if existing else False),
        )
        self._data.setdefault(signal_key, {})[pkg_name] = state
        self.state_changed.emit()

    # -- Read API --------------------------------------------------------

    def get_updates(self, signal_key: str) -> dict[str, str]:
        """Return ``{package_name: latest_version}`` for packages with updates.

        Drop-in replacement for ``_updates_available.get(key, {})``.
        """
        bucket = self._data.get(signal_key, {})
        return {name: s.available_version for name, s in bucket.items() if s.has_update}

    def has_updates_for(self, signal_key: str) -> bool:
        """Return whether any package under *signal_key* has an update."""
        return any(s.has_update for s in self._data.get(signal_key, {}).values())

    def get(self, signal_key: str, pkg_name: str) -> PackageState | None:
        """Return the state for a specific package, or ``None``."""
        return self._data.get(signal_key, {}).get(pkg_name)

    @property
    def has_data(self) -> bool:
        """Return whether any update data has been recorded."""
        return bool(self._data)

    def clear(self) -> None:
        """Remove all recorded state."""
        self._data.clear()

    def record_updates_completed(
        self,
        signal_key: str,
        version_map: dict[str, tuple[str, str]],
    ) -> None:
        """Mark packages as updated, clearing stale ``has_update`` flags.

        Called after a successful tool update run.  For each entry in
        *version_map* (``{package_name: (old_version, new_version)}``),
        the corresponding :class:`PackageState` is updated to reflect
        the new installed version and ``has_update`` is cleared.
        """
        changed = False
        bucket = self._data.get(signal_key, {})
        for pkg_name, (_, new_ver) in version_map.items():
            existing = bucket.get(pkg_name)
            if existing is not None:
                existing.installed_version = new_ver
                existing.has_update = False
                changed = True
        if changed:
            self.state_changed.emit()
