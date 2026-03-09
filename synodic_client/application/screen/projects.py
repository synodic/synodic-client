"""ProjectsView — widget for managing project directories and their manifests."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from porringer.api import API
from porringer.backend.command.core.discovery import DiscoveredPlugins
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.data import DataCoordinator
from synodic_client.application.screen.install import SetupPreviewWidget
from synodic_client.application.screen.schema import PreviewPhase
from synodic_client.application.screen.sidebar import ManifestSidebar
from synodic_client.application.screen.spinner import LoadingIndicator
from synodic_client.application.theme import COMPACT_MARGINS
from synodic_client.resolution import ResolvedConfig

logger = logging.getLogger(__name__)


class ProjectsView(QWidget):
    """Widget for managing project directories and previewing their manifests.

    Displays a vertical sidebar of cached project directories on the
    left with a stacked widget on the right showing one
    :class:`SetupPreviewWidget` per manifest.  All manifests are loaded
    in parallel on first refresh; switching between them is instant.
    """

    def __init__(
        self,
        porringer: API,
        config: ResolvedConfig,
        parent: QWidget | None = None,
        *,
        coordinator: DataCoordinator | None = None,
    ) -> None:
        """Initialize the projects view.

        Args:
            porringer: The porringer API instance.
            config: Resolved configuration.
            parent: Optional parent widget.
            coordinator: Shared data coordinator for validated directory
                data.
        """
        super().__init__(parent)
        self._porringer = porringer
        self._config = config
        self._coordinator = coordinator
        self._refresh_in_progress = False
        self._pending_select: Path | None = None
        self._widgets: dict[Path, SetupPreviewWidget] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        """Build the sidebar + stacked widget layout."""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left — sidebar
        self._sidebar = ManifestSidebar()
        self._sidebar.add_requested.connect(self._on_add)
        self._sidebar.remove_requested.connect(self._on_remove)
        self._sidebar.selection_changed.connect(self._on_selection_changed)
        outer.addWidget(self._sidebar)

        # Right — stacked previews + empty placeholder
        right = QVBoxLayout()
        right.setContentsMargins(*COMPACT_MARGINS)
        right.setSpacing(0)

        self._stack = QStackedWidget()
        right.addWidget(self._stack, stretch=1)

        # Empty placeholder shown when there are no manifests
        self._empty_placeholder = QLabel('No projects. Click + Add Project to get started.')
        self._empty_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_placeholder.setStyleSheet('color: grey; font-size: 13px;')
        self._stack.addWidget(self._empty_placeholder)

        self._loading_indicator = LoadingIndicator('Loading projects\u2026')
        self._stack.addWidget(self._loading_indicator)

        outer.addLayout(right, stretch=1)

    # --- Public API ---

    def refresh(self) -> None:
        """Schedule an asynchronous refresh of the cached directories."""
        if self._refresh_in_progress:
            return
        asyncio.create_task(self._async_refresh())

    async def _async_refresh(self) -> None:
        """Refresh the sidebar and stacked widgets from the porringer cache."""
        self._refresh_in_progress = True
        self._loading_indicator.start()
        self._stack.setCurrentWidget(self._loading_indicator)
        self._sidebar.set_enabled(False)

        try:
            previous = self._pending_select or self._sidebar.selected_path
            self._pending_select = None

            if self._coordinator is not None:
                snapshot = await self._coordinator.refresh()
                results = snapshot.validated_directories
                discovered = snapshot.discovered
            else:
                loop = asyncio.get_running_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: self._porringer.cache.list_directories(
                        validate=True,
                        check_manifest=True,
                    ),
                )
                discovered = None

            directories: list[tuple[Path, str, bool]] = []
            current_paths: set[Path] = set()
            for result in results:
                d = result.directory
                valid = bool(result.exists and result.has_manifest is not False)
                path = Path(d.path)
                directories.append((path, d.name or '', valid))
                current_paths.add(path)

            # Remove widgets for directories no longer in cache
            self._remove_stale_widgets(current_paths)

            # Grab pre-discovered plugins so each widget can skip redundant discovery

            # Create new widgets for new directories
            self._create_directory_widgets(directories, discovered)

            # Rebuild sidebar
            self._sidebar.set_directories(directories)
            self._sidebar.select(previous)

            # Push latest discovered plugins to all existing widgets
            if discovered is not None:
                for w in self._widgets.values():
                    w._discovered_plugins = discovered

            # Load all stacked widgets in parallel
            for path, _name, valid in directories:
                widget = self._widgets.get(path)
                if widget is not None and valid:
                    widget.load(
                        str(path),
                        project_directory=path if path.is_dir() else path.parent,
                        detect_updates=self._config.detect_updates,
                    )

        except Exception:
            logger.exception('Failed to refresh projects')
        finally:
            self._loading_indicator.stop()
            self._sidebar.set_enabled(True)
            self._refresh_in_progress = False

    # --- Event handlers ---

    def _remove_stale_widgets(self, current_paths: set[Path]) -> None:
        """Remove stacked widgets for directories no longer in the cache."""
        for path in list(self._widgets):
            if path not in current_paths:
                widget = self._widgets.pop(path)
                self._stack.removeWidget(widget)
                widget.reset()
                widget.deleteLater()

    def _create_directory_widgets(
        self,
        directories: list[tuple[Path, str, bool]],
        discovered: DiscoveredPlugins | None,
    ) -> None:
        """Create :class:`SetupPreviewWidget` instances for new valid directories."""
        for path, _name, valid in directories:
            if path not in self._widgets and valid:
                widget = SetupPreviewWidget(
                    self._porringer,
                    self,
                    show_close=False,
                    config=self._config,
                )
                widget._discovered_plugins = discovered
                widget.install_finished.connect(self._on_install_finished)
                widget.phase_changed.connect(
                    lambda phase, p=path: self._on_widget_phase_changed(p, phase),
                )
                self._widgets[path] = widget
                self._stack.addWidget(widget)

    def _on_selection_changed(self, path: Path) -> None:
        """Handle sidebar selection — switch the stacked widget."""
        widget = self._widgets.get(path)
        if widget is not None:
            self._stack.setCurrentWidget(widget)
        else:
            self._stack.setCurrentWidget(self._empty_placeholder)

    def _on_widget_phase_changed(self, path: Path, phase: PreviewPhase) -> None:
        """Update the sidebar item's phase indicator."""
        item = self._sidebar.get_item(path)
        if item is not None:
            item.set_phase(phase)

    def _on_add(self) -> None:
        """Open a file picker and immediately cache the chosen directory."""
        filenames = self._porringer.sync.manifest_filenames()
        filter_str = 'Manifests (' + ' '.join(filenames) + ');;All Files (*)'
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            'Select Manifest File',
            '',
            filter_str,
        )
        if not chosen:
            return

        selected = Path(chosen)
        directory = selected if selected.is_dir() else selected.parent

        try:
            self._porringer.cache.add_directory(directory)
            logger.info('Cached new project directory: %s', directory)
        except ValueError:
            logger.debug('Directory already cached: %s', directory)

        if self._coordinator is not None:
            self._coordinator.invalidate()
        self._pending_select = directory
        self.refresh()

    def _on_remove(self, path: Path) -> None:
        """Remove a directory from the porringer cache."""
        self._porringer.cache.remove_directory(path)
        logger.info('Removed project directory from cache: %s', path)

        # Tear down the widget immediately
        widget = self._widgets.pop(path, None)
        if widget is not None:
            self._stack.removeWidget(widget)
            widget.reset()
            widget.deleteLater()

        if self._coordinator is not None:
            self._coordinator.invalidate()
        self.refresh()

    def _on_install_finished(self, _results: object) -> None:
        """Refresh after a successful install."""
        if self._coordinator is not None:
            self._coordinator.invalidate()
        self.refresh()
