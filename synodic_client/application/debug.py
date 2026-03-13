"""Debug automation interface for agent and developer interaction.

Provides a command handler that serialises application domain state and
dispatches deterministic actions via the existing controller/service
layer.  Commands arrive over the :class:`SingleInstance` IPC socket and
responses are returned as JSON strings.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from synodic_client.config import is_dev_mode

if TYPE_CHECKING:
    from porringer.api import API

    from synodic_client.application.config_store import ConfigStore
    from synodic_client.application.data import DataCoordinator
    from synodic_client.application.screen.screen import MainWindow
    from synodic_client.application.screen.settings import SettingsWindow
    from synodic_client.application.screen.tool_update_controller import ToolUpdateOrchestrator
    from synodic_client.application.update_controller import UpdateController
    from synodic_client.application.update_model import UpdateModel
    from synodic_client.client import Client

logger = logging.getLogger(__name__)

_ACTIONS: dict[str, str] = {
    'check_update': 'Trigger a self-update check.',
    'tool_update': 'Run tool/package updates for all plugins.',
    'refresh_data': 'Mark cached data as stale (next refresh re-fetches).',
    'show_main': 'Show and raise the main window.',
    'show_settings': 'Show the settings window.',
    'apply_update': 'Apply a downloaded update and restart.',
    'list_projects': 'List cached project directories with validation status.',
    'add_project': 'Add a directory to the project cache. Arg: <path>',
    'remove_project': 'Remove a directory from the project cache. Arg: <path>',
    'project_status': 'Dump per-action preview status. Arg (optional): <path>',
    'select_project': 'Select a project in the sidebar. Arg: <path>',
}


@dataclasses.dataclass
class DebugServices:
    """Bundle of service references for the debug handler."""

    client: Client
    porringer: API
    coordinator: DataCoordinator | None
    config_store: ConfigStore
    update_controller: UpdateController
    update_model: UpdateModel
    tool_orchestrator: ToolUpdateOrchestrator
    main_window: MainWindow
    settings_window: SettingsWindow


class DebugHandler:
    """Routes debug IPC commands to the application service layer."""

    def __init__(self, services: DebugServices) -> None:
        """Initialize the debug handler with service references."""
        self._s = services

    def handle(self, command: str) -> str:
        """Dispatch a debug command and return a JSON response string."""
        logger.debug('Debug command received: %s', command)

        if command == 'state':
            return self._handle_state()
        if command == 'actions':
            return self._handle_actions()
        if command.startswith('action:'):
            remainder = command[len('action:') :]
            name, _, arg = remainder.partition(':')
            return self._handle_action(name, arg or None)

        return json.dumps({'error': f'unknown command: {command}'})

    def _handle_state(self) -> str:
        """Serialise current application domain state."""
        config = self._s.config_store.config
        coordinator = self._s.coordinator
        model = self._s.update_model

        snapshot = coordinator.snapshot if coordinator is not None else None
        data_stale = coordinator.is_stale if coordinator is not None else None

        state = {
            'app': {
                'version': str(self._s.client.version),
                'dev_mode': is_dev_mode(),
                'frozen': getattr(sys, 'frozen', False),
                'platform': sys.platform,
            },
            'config': dataclasses.asdict(config),
            'update': {
                'phase': model.phase.name,
                'version': model.version,
                'error_message': model.error_message,
            },
            'data': {
                'plugin_count': len(snapshot.plugins) if snapshot else 0,
                'directory_count': len(snapshot.directories) if snapshot else 0,
                'manager_count': len(snapshot.plugin_managers) if snapshot else 0,
                'stale': data_stale,
            },
            'windows': {
                'main_visible': self._s.main_window.isVisible(),
                'settings_visible': self._s.settings_window.isVisible(),
            },
        }
        return json.dumps(state, default=str)

    @staticmethod
    def _handle_actions() -> str:
        """Return a list of available action names with descriptions."""
        return json.dumps({'actions': _ACTIONS})

    def _handle_action(self, name: str, arg: str | None = None) -> str:
        """Dispatch a named action to the appropriate controller."""
        if name not in _ACTIONS:
            return json.dumps({'error': f'unknown action: {name}', 'available': list(_ACTIONS)})

        # Actions that return their own JSON response
        _project_dispatch: dict[str, Callable[[str | None], str]] = {
            'list_projects': lambda _: self._handle_list_projects(),
            'add_project': self._handle_add_project,
            'remove_project': self._handle_remove_project,
            'project_status': self._handle_project_status,
            'select_project': self._handle_select_project,
        }

        if name in _project_dispatch:
            return _project_dispatch[name](arg)

        # Fire-and-forget actions
        if name == 'check_update':
            self._s.update_controller.check_now(silent=False)
        elif name == 'tool_update':
            self._s.tool_orchestrator.on_tool_update()
        elif name == 'refresh_data':
            if self._s.coordinator is not None:
                self._s.coordinator.invalidate()
        elif name == 'show_main':
            self._s.main_window.show()
            self._s.main_window.raise_()
            self._s.main_window.activateWindow()
        elif name == 'show_settings':
            self._s.settings_window.show()
        elif name == 'apply_update':
            self._s.update_controller.request_apply()

        return json.dumps({'ok': True, 'action': name})

    # -- Project management actions ----------------------------------------

    def _handle_list_projects(self) -> str:
        """List all cached project directories with validation status."""
        from synodic_client.operations.project import list_projects  # noqa: PLC0415

        projects = list_projects(self._s.porringer)
        return json.dumps({'projects': [dataclasses.asdict(p) for p in projects]})

    def _handle_add_project(self, arg: str | None) -> str:
        """Add a directory to the porringer cache."""
        if not arg:
            return json.dumps({'error': 'add_project requires a path argument'})

        from synodic_client.operations.project import add_project  # noqa: PLC0415

        try:
            add_project(self._s.porringer, arg)
        except (NotADirectoryError, ValueError) as exc:
            return json.dumps({'error': str(exc)})

        if self._s.coordinator is not None:
            self._s.coordinator.invalidate()

        projects_view = self._s.main_window._projects_view  # noqa: SLF001
        if projects_view is not None:
            projects_view.refresh()

        return json.dumps({'ok': True, 'action': 'add_project', 'path': arg})

    def _handle_remove_project(self, arg: str | None) -> str:
        """Remove a directory from the porringer cache."""
        if not arg:
            return json.dumps({'error': 'remove_project requires a path argument'})

        from synodic_client.operations.project import remove_project  # noqa: PLC0415

        remove_project(self._s.porringer, arg)

        if self._s.coordinator is not None:
            self._s.coordinator.invalidate()

        projects_view = self._s.main_window._projects_view  # noqa: SLF001
        if projects_view is not None:
            projects_view.refresh()

        return json.dumps({'ok': True, 'action': 'remove_project', 'path': arg})

    def _handle_project_status(self, arg: str | None) -> str:
        """Dump per-action preview status for a project."""
        projects_view = self._s.main_window._projects_view  # noqa: SLF001
        if projects_view is None:
            return json.dumps({'error': 'projects view not initialised — run show_main first'})

        if arg:
            target = Path(arg)
        else:
            target = projects_view._sidebar.selected_path  # noqa: SLF001
            if target is None:
                return json.dumps({'error': 'no project selected and no path argument provided'})

        widget = projects_view._widgets.get(target)  # noqa: SLF001
        if widget is None:
            available = [str(p) for p in projects_view._widgets]  # noqa: SLF001
            return json.dumps({'error': f'no widget for path: {target}', 'available_paths': available})

        model = widget.model
        actions = []
        for state in model.action_states:
            act = state.action
            entry: dict[str, object] = {
                'description': act.description,
                'kind': act.kind.name if act.kind else None,
                'status': state.status,
            }
            if act.package is not None:
                entry['package'] = act.package.name
                if act.package.constraint:
                    entry['constraint'] = act.package.constraint
            if act.installer:
                entry['installer'] = act.installer
            actions.append(entry)

        needed = sum(1 for s in model.action_states if s.status == 'Needed')
        satisfied = sum(1 for s in model.action_states if '\u2713' in s.status)
        pending = sum(1 for s in model.action_states if s.status == 'Pending')
        upgradable = len(model.upgradable_keys)

        return json.dumps({
            'path': str(target),
            'phase': model.phase.name,
            'action_count': len(model.action_states),
            'checked_count': model.checked_count,
            'actions': actions,
            'summary': {
                'needed': needed,
                'satisfied': satisfied,
                'pending': pending,
                'upgradable': upgradable,
            },
        })

    def _handle_select_project(self, arg: str | None) -> str:
        """Select a project in the sidebar."""
        if not arg:
            return json.dumps({'error': 'select_project requires a path argument'})

        self._s.main_window._navigate_to_project(arg)  # noqa: SLF001
        return json.dumps({'ok': True, 'action': 'select_project', 'path': arg})
