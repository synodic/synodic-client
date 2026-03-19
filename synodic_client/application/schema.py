"""Application-layer data models.

Contains data structures shared across application modules — the
``DataCoordinator`` snapshot and the tool-update result summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from porringer.backend.command.core.discovery import DiscoveredPlugins
from porringer.core.plugin_schema.plugin_manager import PluginManager
from porringer.schema import (
    DirectoryValidationResult,
    ManifestDirectory,
    PluginCapability,
    PluginInfo,
)


@dataclass(slots=True)
class Snapshot:
    """Immutable bundle of data produced by a single refresh cycle.

    All fields are populated by :meth:`DataCoordinator.refresh` and
    remain stable until the next refresh.
    """

    plugins: list[PluginInfo] = field(default_factory=list)
    """All discovered plugins with install status and version info."""

    directories: list[ManifestDirectory] = field(default_factory=list)
    """Cached project directories (un-validated)."""

    validated_directories: list[DirectoryValidationResult] = field(default_factory=list)
    """Cached directories with ``exists`` / ``has_manifest`` validation."""

    discovered: DiscoveredPlugins | None = None
    """Full plugin discovery result including runtime context."""

    plugin_managers: dict[str, PluginManager] = field(default_factory=dict)
    """Project-environment plugins implementing the ``PluginManager`` protocol."""

    plugin_capabilities: dict[str, frozenset[PluginCapability]] = field(default_factory=dict)
    """Protocol capabilities reported for each discovered plugin."""
