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
from synodic_client.updater import DEFAULT_AUTO_UPDATE_INTERVAL_HOURS, GITHUB_REPO_URL, UpdateChannel, UpdateConfig

logger = logging.getLogger(__name__)


def merge_config(
    global_config: GlobalConfiguration,
    local_config: LocalConfiguration | None,
) -> GlobalConfiguration:
    """Merge local overrides into a global configuration.

    Fields explicitly set (not None) in the local config override the
    corresponding global values.

    Args:
        global_config: The user-scoped global configuration.
        local_config: The portable local configuration, or None.

    Returns:
        A ``GlobalConfiguration`` with merged values.
    """
    if local_config is None:
        return global_config

    merged = global_config.model_dump()
    for field_name, value in local_config.model_dump().items():
        if value is not None:
            merged[field_name] = value

    return GlobalConfiguration.model_validate(merged)


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

    interval = config.auto_update_interval_hours
    if interval is None:
        interval = DEFAULT_AUTO_UPDATE_INTERVAL_HOURS

    return UpdateConfig(channel=channel, repo_url=repo_url, auto_update_interval_hours=interval)


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
