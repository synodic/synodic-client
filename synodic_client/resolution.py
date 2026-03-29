"""Configuration resolution for the Synodic Client.

Combines ``BuildConfig`` (read-only, next to exe) and ``UserConfig``
(read-write, ``%LOCALAPPDATA%``) into an immutable ``ResolvedConfig``
dataclass, then derives runtime objects like ``UpdateConfig``.

Key design rules:
- ``ResolvedConfig`` is frozen — no mutation after construction.
- ``UserConfig`` always saves *all* fields (no sparse writes).
- ``BuildConfig`` seeds user config once, then stays out of the way.
- Settings UI calls ``update_user_config()`` to persist changes and
  receive a new ``ResolvedConfig``.
"""

from __future__ import annotations

import logging
import sys

from synodic_client.config import (
    load_build_config,
    load_user_config,
    save_user_config,
)
from synodic_client.schema import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    ResolvedConfig,
    UpdateConfig,
    UserConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed — one-time build → user config propagation
# ---------------------------------------------------------------------------


def seed_user_config_from_build() -> None:
    """Copy ``BuildConfig`` fields into ``UserConfig`` when they are still at defaults.

    Called once during bootstrap (before the UI) so that the build's
    channel/source are persisted into the user config.  If the user
    has already customised a field, the build value is ignored.
    """
    build = load_build_config()
    if build is None:
        return

    user = load_user_config()
    changed = False

    if build.update_source is not None and user.update_source is None:
        user.update_source = build.update_source
        changed = True

    if build.update_channel is not None and user.update_channel is None:
        user.update_channel = build.update_channel
        changed = True

    if changed:
        save_user_config(user)
        logger.info(
            'Seeded user config from build config: source=%s, channel=%s',
            user.update_source,
            user.update_channel,
        )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _default_channel() -> str:
    """Return the default channel based on whether we're running frozen."""
    return 'stable' if getattr(sys, 'frozen', False) else 'dev'


def resolve_config() -> ResolvedConfig:
    """Load user config and return an immutable :class:`ResolvedConfig`.

    Build config is *not* consulted here — it should already have been
    seeded via :func:`seed_user_config_from_build` at startup.

    Returns:
        A fully resolved, immutable configuration snapshot.
    """
    user = load_user_config()
    return _resolve_from_user(user)


def _resolve_from_user(user: UserConfig) -> ResolvedConfig:
    """Derive a ``ResolvedConfig`` from a ``UserConfig``.

    Resolves every ``None`` field to its concrete default.
    """
    channel = user.update_channel or _default_channel()

    # Note: intervals use explicit None-checks because 0 is a valid
    # value meaning "disabled" and `or` would incorrectly skip it.
    auto_interval = user.auto_update_interval_minutes
    if auto_interval is None:
        auto_interval = DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    tool_interval = user.tool_update_interval_minutes
    if tool_interval is None:
        tool_interval = DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    auto_apply = user.auto_apply if user.auto_apply is not None else True
    auto_start = user.auto_start if user.auto_start is not None else True
    debug_logging = user.debug_logging if user.debug_logging is not None else False

    return ResolvedConfig(
        update_source=user.update_source,
        update_channel=channel,
        auto_update_interval_minutes=auto_interval,
        tool_update_interval_minutes=tool_interval,
        plugin_auto_update=user.plugin_auto_update,
        prerelease_packages=user.prerelease_packages,
        auto_apply=auto_apply,
        auto_start=auto_start,
        debug_logging=debug_logging,
        last_client_update=user.last_client_update,
        last_tool_updates=user.last_tool_updates,
    )


# ---------------------------------------------------------------------------
# Mutation — save and re-resolve
# ---------------------------------------------------------------------------


def update_user_config(**changes: object) -> ResolvedConfig:
    """Load user config, apply *changes*, save, and return a new ``ResolvedConfig``.

    This is the primary write path for the Settings UI.  Each keyword
    argument corresponds to a :class:`UserConfig` field name.

    Args:
        **changes: Field-name / value pairs to apply to the user config.

    Returns:
        A fresh :class:`ResolvedConfig` reflecting the saved state.
    """
    user = load_user_config()
    for field_name, value in changes.items():
        setattr(user, field_name, value)
    save_user_config(user)
    return _resolve_from_user(user)


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------


def resolve_update_config(config: ResolvedConfig) -> UpdateConfig:
    """Derive an :class:`UpdateConfig` from resolved configuration values.

    Delegates to :meth:`UpdateConfig.from_resolved` so the type owns
    its own construction while this module stays the canonical entry
    point for all resolution logic.

    Args:
        config: A resolved configuration snapshot.

    Returns:
        An ``UpdateConfig`` ready to initialise the updater.
    """
    return UpdateConfig.from_resolved(config)
