"""Configuration resolution for the Synodic Client.

Merges ``LocalConfiguration`` (portable, next to exe) and ``GlobalConfiguration``
(user-scoped, ``%LOCALAPPDATA%``) into a single resolved configuration, then
derives runtime objects like ``UpdateConfig``.
"""

import logging
import sys

from synodic_client.config import (
    GlobalConfiguration,
    LocalConfiguration,
    _load_global_config,
    _load_local_config,
    save_config,
)
from synodic_client.updater import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    GITHUB_REPO_URL,
    UpdateChannel,
    UpdateConfig,
)

logger = logging.getLogger(__name__)


def merge_config(
    global_config: GlobalConfiguration,
    local_config: LocalConfiguration | None,
) -> GlobalConfiguration:
    """Merge local overrides into a global configuration.

    Fields that the user has explicitly saved (present in the global
    config file) take priority over local overrides.  Local config
    fields only fill in values the user has **not** set.

    The returned object preserves the global config's
    ``model_fields_set`` so that :func:`save_config` can use
    ``exclude_unset=True`` to write only user-changed fields.

    Args:
        global_config: The user-scoped global configuration.
        local_config: The portable local configuration, or None.

    Returns:
        A ``GlobalConfiguration`` with merged values.
    """
    if local_config is None:
        return global_config

    user_set = global_config.model_fields_set
    merged = global_config.model_dump()
    for field_name, value in local_config.model_dump().items():
        if value is not None and field_name not in user_set:
            merged[field_name] = value

    return GlobalConfiguration.model_construct(_fields_set=set(user_set), **merged)


def resolve_config() -> GlobalConfiguration:
    """Load and merge both configuration layers.

    Returns:
        A fully resolved ``GlobalConfiguration``.
    """
    return merge_config(_load_global_config(), _load_local_config())


def resolve_update_config(config: GlobalConfiguration) -> UpdateConfig:
    """Derive an ``UpdateConfig`` from resolved configuration values.

    Args:
        config: A resolved global configuration.

    Returns:
        An ``UpdateConfig`` ready to initialise the updater.
    """
    is_dev = not getattr(sys, 'frozen', False)

    if config.update_channel is not None:
        channel = UpdateChannel.DEVELOPMENT if config.update_channel == 'dev' else UpdateChannel.STABLE
    else:
        channel = UpdateChannel.DEVELOPMENT if is_dev else UpdateChannel.STABLE

    repo_url = config.update_source or GITHUB_REPO_URL

    interval = config.auto_update_interval_minutes
    if interval is None:
        interval = DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    tool_interval = config.tool_update_interval_minutes
    if tool_interval is None:
        tool_interval = DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    return UpdateConfig(
        channel=channel,
        repo_url=repo_url,
        auto_update_interval_minutes=interval,
        tool_update_interval_minutes=tool_interval,
    )


def resolve_enabled_plugins(
    config: GlobalConfiguration,
    all_plugin_names: list[str],
) -> list[str] | None:
    """Derive the include-list of plugins that should auto-update.

    Returns the list of plugin names whose auto-update is **not** disabled.
    If all plugins are enabled (the common case), returns ``None`` to
    indicate "no filtering".

    Args:
        config: A resolved global configuration.
        all_plugin_names: Every known plugin name.

    Returns:
        A list of enabled plugin names, or ``None`` when all are enabled.
    """
    mapping = config.plugin_auto_update
    if not mapping:
        return None

    disabled = {name for name, enabled in mapping.items() if not enabled}
    if not disabled:
        return None

    return [n for n in all_plugin_names if n not in disabled]


def resolve_auto_start(config: GlobalConfiguration) -> bool:
    """Determine whether auto-startup should be enabled.

    ``None`` (the default) is treated as enabled.

    Args:
        config: A resolved global configuration.

    Returns:
        ``True`` when the application should register for auto-startup.
    """
    if config.auto_start is None:
        return True
    return config.auto_start


def update_and_resolve(config: GlobalConfiguration) -> UpdateConfig:
    """Save a modified global config and resolve it into an UpdateConfig.

    Convenience function for the Settings UI: persists the change, then
    returns the derived ``UpdateConfig``.

    Args:
        config: The modified global configuration to save.

    Returns:
        An ``UpdateConfig`` derived from the saved configuration.
    """
    save_config(config)
    return resolve_update_config(config)
