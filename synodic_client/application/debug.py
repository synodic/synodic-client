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
from synodic_client.operations.schema import DEBUG_ACTIONS

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

_ACTIONS = DEBUG_ACTIONS


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
        from synodic_client.operations.project import run_project_action

        return json.dumps(run_project_action('list_projects', None, self._s.porringer))

    def _handle_add_project(self, arg: str | None) -> str:
        """Add a directory to the porringer cache."""
        from synodic_client.operations.project import run_project_action

        result = run_project_action('add_project', arg, self._s.porringer)

        if 'error' not in result:
            if self._s.coordinator is not None:
                self._s.coordinator.invalidate()
            projects_view = self._s.main_window._projects_view
            if projects_view is not None:
                projects_view.refresh()

        return json.dumps(result)

    def _handle_remove_project(self, arg: str | None) -> str:
        """Remove a directory from the porringer cache."""
        from synodic_client.operations.project import run_project_action

        result = run_project_action('remove_project', arg, self._s.porringer)

        if 'error' not in result:
            if self._s.coordinator is not None:
                self._s.coordinator.invalidate()
            projects_view = self._s.main_window._projects_view
            if projects_view is not None:
                projects_view.refresh()

        return json.dumps(result)

    def _handle_project_status(self, arg: str | None) -> str:
        """Dump per-action preview status for a project."""
        projects_view = self._s.main_window._projects_view
        if projects_view is None:
            return json.dumps({'error': 'projects view not initialised — run show_main first'})

        if arg:
            target = Path(arg)
        else:
            target = projects_view._sidebar.selected_path
            if target is None:
                return json.dumps({'error': 'no project selected and no path argument provided'})

        widget = projects_view._widgets.get(target)
        if widget is None:
            available = [str(p) for p in projects_view._widgets]
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

        from synodic_client.operations.schema import classify_status

        needed = sum(1 for s in model.action_states if classify_status(s.status) == 'needed')
        satisfied = sum(1 for s in model.action_states if classify_status(s.status) == 'satisfied')
        pending = sum(1 for s in model.action_states if classify_status(s.status) == 'pending')
        upgradable = sum(1 for s in model.action_states if s.status == 'Update available')

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

        self._s.main_window._navigate_to_project(arg)
        return json.dumps({'ok': True, 'action': 'select_project', 'path': arg})
