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
from dataclasses import dataclass

from packaging.version import Version

from synodic_client.config import (
    UserConfig,
    load_build_config,
    load_user_config,
    save_user_config,
)
from synodic_client.updater import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    GITHUB_REPO_URL,
    UpdateChannel,
    UpdateConfig,
    github_release_asset_url,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ResolvedConfig — immutable runtime snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedConfig:
    """Immutable runtime configuration snapshot.

    Constructed by :func:`resolve_config` from the merged
    ``BuildConfig`` + ``UserConfig`` layers.  Every field has a
    concrete, non-``None`` value (except ``update_source`` and
    ``prerelease_packages`` where ``None`` is a valid semantic value
    meaning "use default" / "no overrides").
    """

    update_source: str | None
    update_channel: str
    auto_update_interval_minutes: int
    tool_update_interval_minutes: int
    plugin_auto_update: dict[str, bool | dict[str, bool]] | None
    detect_updates: bool
    prerelease_packages: dict[str, list[str]] | None
    auto_start: bool


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

    auto_start = user.auto_start if user.auto_start is not None else True

    return ResolvedConfig(
        update_source=user.update_source,
        update_channel=channel,
        auto_update_interval_minutes=auto_interval,
        tool_update_interval_minutes=tool_interval,
        plugin_auto_update=user.plugin_auto_update,
        detect_updates=user.detect_updates,
        prerelease_packages=user.prerelease_packages,
        auto_start=auto_start,
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
    """Derive an ``UpdateConfig`` from resolved configuration values.

    Args:
        config: A resolved configuration snapshot.

    Returns:
        An ``UpdateConfig`` ready to initialise the updater.
    """
    channel = UpdateChannel.DEVELOPMENT if config.update_channel == 'dev' else UpdateChannel.STABLE

    repo_url = github_release_asset_url(
        config.update_source or GITHUB_REPO_URL,
        channel,
    )

    return UpdateConfig(
        channel=channel,
        repo_url=repo_url,
        auto_update_interval_minutes=config.auto_update_interval_minutes,
        tool_update_interval_minutes=config.tool_update_interval_minutes,
    )


def resolve_version(client: object) -> Version:
    """Return the best-known application version.

    When a Velopack-installed ``Updater`` is available the authoritative
    version comes from the native binary manifest.  Otherwise, the
    Python package metadata version (``importlib.metadata``) is used.

    Accepts ``Client`` (or any object with ``.updater`` and ``.version``
    attributes) so that :mod:`resolution` does not need a hard import
    of :class:`~synodic_client.client.Client` — avoiding a tighter
    coupling than necessary.

    Args:
        client: The application service facade (typically a
            :class:`~synodic_client.client.Client` instance).

    Returns:
        The resolved :class:`~packaging.version.Version`.
    """
    updater = getattr(client, 'updater', None)
    if updater is not None:
        try:
            if updater.is_installed:
                return updater.current_version
        except Exception:
            logger.debug('Failed to query Velopack version, falling back', exc_info=True)

    return getattr(client, 'version', Version('0.0.0'))


def resolve_enabled_plugins(
    config: ResolvedConfig,
    all_plugin_names: list[str],
) -> list[str] | None:
    """Derive the include-list of plugins that should auto-update.

    Returns the list of plugin names whose auto-update is **not** disabled.
    If all plugins are enabled (the common case), returns ``None`` to
    indicate "no filtering".

    Args:
        config: A resolved configuration snapshot.
        all_plugin_names: Every known plugin name.

    Returns:
        A list of enabled plugin names, or ``None`` when all are enabled.
    """
    mapping = config.plugin_auto_update
    if not mapping:
        return None

    disabled = {name for name, enabled in mapping.items() if enabled is False}
    if not disabled:
        return None

    return [n for n in all_plugin_names if n not in disabled]


def resolve_auto_update_scope(
    config: ResolvedConfig,
    all_plugin_names: list[str],
    manifest_packages: dict[str, set[str]] | None = None,
) -> tuple[set[str] | None, set[str] | None]:
    """Derive plugin and package include-lists for auto-update.

    Walks ``plugin_auto_update`` to determine which plugins and packages
    should participate in automatic updates.  When a plugin entry is a
    nested ``dict[str, bool]``, individual packages can be toggled on or
    off.  Packages not listed in the config inherit a manifest-aware
    default: **ON** if the package appears in *manifest_packages* for
    that plugin, **OFF** otherwise.

    Args:
        config: A resolved configuration snapshot.
        all_plugin_names: Every known (installed) plugin name.
        manifest_packages: Mapping of ``plugin_name`` → set of package
            names declared in cached manifests.  ``None`` means treat
            all packages as manifest-referenced (conservative default).

    Returns:
        A ``(enabled_plugins, include_packages)`` tuple.  Either element
        may be ``None`` meaning "no filtering".
    """
    mapping = config.plugin_auto_update

    # --- Determine enabled plugins ---
    disabled_plugins: set[str] = set()
    per_package_entries: dict[str, dict[str, bool]] = {}

    if mapping:
        for name, value in mapping.items():
            if value is False:
                disabled_plugins.add(name)
            elif isinstance(value, dict):
                per_package_entries[name] = value

    enabled_plugins: set[str] | None = None
    if disabled_plugins:
        enabled_plugins = {n for n in all_plugin_names if n not in disabled_plugins}

    # --- Determine include_packages ---
    # Only build the set when there are per-package overrides or
    # manifest data that distinguishes global from manifest-required.
    include_packages: set[str] | None = None

    if per_package_entries or manifest_packages:
        # Start with manifest-referenced packages (auto-update ON by default)
        pkg_set: set[str] = set()
        if manifest_packages:
            for plugin_name, pkgs in manifest_packages.items():
                if plugin_name in disabled_plugins:
                    continue
                pkg_set |= pkgs

        # Apply per-package config overrides
        for plugin_name, pkg_map in per_package_entries.items():
            if plugin_name in disabled_plugins:
                continue
            for pkg_name, enabled in pkg_map.items():
                if enabled:
                    pkg_set.add(pkg_name)
                else:
                    pkg_set.discard(pkg_name)

        if pkg_set:
            include_packages = pkg_set

    return enabled_plugins, include_packages
