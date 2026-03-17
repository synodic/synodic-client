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
from synodic_client.operations.config import get_config, get_config_value, list_config_keys, set_config
from synodic_client.operations.install import (
    execute_install,
    preview_manifest,
    preview_manifest_stream,
    resolve_manifest_path,
)
from synodic_client.operations.project import (
    add_project,
    find_manifest,
    list_projects,
    project_status,
    remove_project,
    run_project_action,
)
from synodic_client.operations.schema import (
    DEBUG_ACTIONS,
    GUI_ONLY_ACTIONS,
    SKIP_REASON_LABELS,
    ActionInfo,
    ConfigKeyInfo,
    DownloadResult,
    PackageInfo,
    PreviewActionChecked,
    PreviewEvent,
    PreviewManifestParsed,
    PreviewPluginsQueried,
    PreviewReady,
    PreviewResult,
    ProjectInfo,
    ProjectStatus,
    ProviderInfo,
    StatusSummary,
    TagInfo,
    ToolSection,
    UpdateCheckResult,
    UpdateResult,
    classify_status,
    resolve_action_status,
    skip_reason_label,
)
from synodic_client.operations.tool import (
    check_tool_updates,
    parse_plugin_key,
    remove_package,
    resolve_auto_update_scope,
    update_all_tools,
    update_runtime_plugin,
    update_tool,
)
from synodic_client.operations.update import apply_self_update, check_self_update, download_self_update

__all__ = [
    # bootstrap
    'init_services',
    # config
    'get_config',
    'get_config_value',
    'list_config_keys',
    'set_config',
    # install
    'execute_install',
    'preview_manifest',
    'preview_manifest_stream',
    'resolve_manifest_path',
    # project
    'add_project',
    'find_manifest',
    'list_projects',
    'project_status',
    'remove_project',
    'run_project_action',
    # schema
    'ActionInfo',
    'ConfigKeyInfo',
    'DEBUG_ACTIONS',
    'DownloadResult',
    'GUI_ONLY_ACTIONS',
    'PackageInfo',
    'PreviewActionChecked',
    'PreviewEvent',
    'PreviewManifestParsed',
    'PreviewPluginsQueried',
    'PreviewReady',
    'PreviewResult',
    'ProjectInfo',
    'ProjectStatus',
    'ProviderInfo',
    'SKIP_REASON_LABELS',
    'StatusSummary',
    'TagInfo',
    'ToolSection',
    'UpdateCheckResult',
    'UpdateResult',
    'classify_status',
    'resolve_action_status',
    'skip_reason_label',
    # tool
    'check_tool_updates',
    'parse_plugin_key',
    'remove_package',
    'resolve_auto_update_scope',
    'update_all_tools',
    'update_runtime_plugin',
    'update_tool',
    # update
    'apply_self_update',
    'check_self_update',
    'download_self_update',
]
