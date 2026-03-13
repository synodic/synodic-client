"""Operations layer — pure functions for all user-facing actions.

Every module in this package provides stateless functions that take
explicit dependencies (porringer ``API``, ``Client``, config) as
arguments and return typed result dataclasses.  No Qt imports, no
signal emission, no implicit state.

Modules:
    schema      — Typed result dataclasses consumed by CLI and GUI.
    project     — Project directory CRUD and status queries.
    tool        — Tool/package listing, update checking, and upgrades.
    install     — Manifest preview and execution.
    config      — Configuration introspection and mutation.
    update      — Self-update lifecycle (check, download, apply).
    bootstrap   — Porringer API initialisation without Qt.
"""

from synodic_client.operations.bootstrap import init_services
from synodic_client.operations.config import get_config, list_config_keys, set_config
from synodic_client.operations.install import execute_install, preview_manifest
from synodic_client.operations.project import add_project, list_projects, remove_project
from synodic_client.operations.schema import (
    ActionInfo,
    ConfigKeyInfo,
    DownloadResult,
    PackageInfo,
    PreviewResult,
    ProjectInfo,
    ProjectStatus,
    ProviderInfo,
    StatusSummary,
    TagInfo,
    ToolSection,
    UpdateCheckResult,
    UpdateResult,
)
from synodic_client.operations.tool import (
    check_tool_updates,
    remove_package,
    resolve_auto_update_scope,
    update_all_tools,
    update_tool,
)
from synodic_client.operations.update import apply_self_update, check_self_update, download_self_update

__all__ = [
    # bootstrap
    'init_services',
    # config
    'get_config',
    'list_config_keys',
    'set_config',
    # install
    'execute_install',
    'preview_manifest',
    # project
    'add_project',
    'list_projects',
    'remove_project',
    # schema
    'ActionInfo',
    'ConfigKeyInfo',
    'DownloadResult',
    'PackageInfo',
    'PreviewResult',
    'ProjectInfo',
    'ProjectStatus',
    'ProviderInfo',
    'StatusSummary',
    'TagInfo',
    'ToolSection',
    'UpdateCheckResult',
    'UpdateResult',
    # tool
    'check_tool_updates',
    'remove_package',
    'resolve_auto_update_scope',
    'update_all_tools',
    'update_tool',
    # update
    'apply_self_update',
    'check_self_update',
    'download_self_update',
]
