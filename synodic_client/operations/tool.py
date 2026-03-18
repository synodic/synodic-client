"""Tool and package listing/update operations.

Pure async functions for listing installed tools, checking for updates,
and running updates.  Policy logic (auto-update scope, manifest-aware
defaults) lives here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from porringer.core.schema import PackageRef
from porringer.schema import (
    ActionCompletedEvent,
    ActionStartedEvent,
    SetupParameters,
    SkipReason,
    SyncStrategy,
)

from synodic_client.operations.schema import UpdateResult

if TYPE_CHECKING:
    from porringer.api import API
    from porringer.backend.command.core.discovery import DiscoveredPlugins
    from porringer.schema import ManifestDirectory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plugin key parsing
# ---------------------------------------------------------------------------


def parse_plugin_key(name: str) -> tuple[str, str | None]:
    """Split a composite ``'plugin:tag'`` key into ``(bare_name, tag)``.

    Returns ``(name, None)`` when there is no tag component.
    """
    if ':' in name:
        bare, tag = name.split(':', 1)
        return bare, tag
    return name, None


def _capture_versions(result: UpdateResult, pkg_name: str, action_result: object) -> None:
    """Store before/after version info from *action_result* into *result*."""
    old_ver = getattr(action_result, 'installed_version', '') or ''
    new_ver = getattr(action_result, 'available_version', '') or ''
    if pkg_name and (old_ver or new_ver):
        result.version_map[pkg_name] = (old_ver, new_ver)


def log_update_result(result: UpdateResult) -> None:
    """Log a human-readable summary of an :class:`UpdateResult`.

    Called by both the GUI controller and the CLI after an update
    completes so that version transitions are recorded consistently.
    """
    logger.info(
        'Tool update completed: %d manifest(s), %d updated, %d already latest, %d failed',
        result.manifests_processed,
        result.updated,
        len(result.already_latest),
        result.failed,
    )
    for pkg_name, (old_ver, new_ver) in result.version_map.items():
        if old_ver and new_ver:
            logger.info('  %s: %s \u2192 %s', pkg_name, old_ver, new_ver)
        elif new_ver:
            logger.info('  %s: \u2192 %s', pkg_name, new_ver)


# ---------------------------------------------------------------------------
# Update-check
# ---------------------------------------------------------------------------


async def check_tool_updates(
    porringer: API,
    directories: list[ManifestDirectory] | None = None,
    discovered: DiscoveredPlugins | None = None,
) -> dict[str, dict[str, str]]:
    """Detect available updates across cached manifests.

    Returns ``{plugin_name: {package_name: latest_version}}`` for
    packages that have a newer version available.

    When *directories* is ``None`` the function fetches and filters
    the cached directory list internally.

    Args:
        porringer: The porringer API instance.
        directories: Cached project directories to scan.  ``None``
            means fetch from the cache automatically.
        discovered: Pre-discovered plugins to avoid redundant discovery.
    """
    if directories is None:
        loop = asyncio.get_running_loop()
        dir_results = await loop.run_in_executor(
            None,
            lambda: porringer.cache.list_directories(validate=True, check_manifest=True),
        )
        directories = [dr.directory for dr in dir_results if dr.has_manifest]
    available: dict[str, dict[str, str]] = {}

    async def _check_one(directory: ManifestDirectory) -> None:
        try:
            from synodic_client.operations.project import find_manifest

            path = Path(directory.path)
            manifest_path = find_manifest(porringer, path)

            if manifest_path is None:
                return

            params = SetupParameters(
                paths=[str(manifest_path)],
                dry_run=True,
                project_directory=path,
            )
            async for event in porringer.sync.execute_stream(params, plugins=discovered):
                if isinstance(event, ActionCompletedEvent) and event.result.skip_reason == SkipReason.UPDATE_AVAILABLE:
                    action = event.result.action
                    if action.installer and action.package:
                        pkg_name = str(action.package.name)
                        latest = event.result.available_version or ''
                        available.setdefault(action.installer, {})[pkg_name] = latest
        except Exception:
            logger.debug('Could not detect updates for %s', directory.path, exc_info=True)

    async with asyncio.TaskGroup() as tg:
        for d in directories:
            tg.create_task(_check_one(d))

    return available


# ---------------------------------------------------------------------------
# Update execution
# ---------------------------------------------------------------------------


async def update_tool(
    porringer: API,
    plugin_name: str,
    package_name: str | None = None,
    *,
    runtime_tag: str | None = None,
    discovered: DiscoveredPlugins | None = None,
    on_package_starting: Callable[[str], None] | None = None,
    on_package_completed: Callable[[str, bool, bool], None] | None = None,
) -> UpdateResult:
    """Upgrade a single plugin or a specific package within it.

    When *package_name* is ``None`` the entire plugin is updated by
    re-syncing cached manifests for that plugin only.  When a
    *runtime_tag* is provided, the upgrade is scoped to that runtime.

    Args:
        porringer: The porringer API instance.
        plugin_name: The installer plugin name.
        package_name: Optional specific package to upgrade.
        runtime_tag: Optional runtime tag for per-runtime updates.
        discovered: Pre-discovered plugins.
        on_package_starting: Called with ``(package_name)`` before each
            package upgrade begins.
        on_package_completed: Called with ``(package_name, success, skipped)``
            after each package upgrade finishes.

    Returns:
        An :class:`UpdateResult` summarising the operation.
    """
    result = UpdateResult(plugin=plugin_name)

    if package_name is not None:
        # Single-package upgrade
        ref = PackageRef(name=package_name)
        action_result = await porringer.package.upgrade(
            plugin_name,
            ref,
            runtime_tag=runtime_tag,
            plugins=discovered,
        )
        if action_result.skipped:
            result.already_latest.append(package_name)
        elif action_result.success:
            result.packages_updated.append(package_name)
            result.updated_packages.add(package_name)
            _capture_versions(result, package_name, action_result)
        else:
            result.packages_failed.append(package_name)
        return result

    # Full-plugin update: re-sync all cached manifests for this plugin.
    if runtime_tag is not None:
        return await update_runtime_plugin(
            porringer,
            plugin_name,
            runtime_tag,
            discovered=discovered,
            on_package_starting=on_package_starting,
            on_package_completed=on_package_completed,
        )

    return await _update_plugin_via_manifests(
        porringer,
        plugin_name,
        discovered=discovered,
        on_package_starting=on_package_starting,
        on_package_completed=on_package_completed,
    )


async def _update_plugin_via_manifests(
    porringer: API,
    plugin_name: str,
    *,
    discovered: DiscoveredPlugins | None = None,
    on_package_starting: Callable[[str], None] | None = None,
    on_package_completed: Callable[[str, bool, bool], None] | None = None,
) -> UpdateResult:
    """Re-sync cached manifests scoped to a single plugin."""
    result = await update_all_tools(
        porringer,
        plugins={plugin_name},
        discovered=discovered,
        on_package_starting=on_package_starting,
        on_package_completed=on_package_completed,
    )
    result.plugin = plugin_name
    return result


async def update_runtime_plugin(
    porringer: API,
    plugin_name: str,
    runtime_tag: str,
    *,
    include_packages: set[str] | None = None,
    discovered: DiscoveredPlugins | None = None,
    on_package_starting: Callable[[str], None] | None = None,
    on_package_completed: Callable[[str, bool, bool], None] | None = None,
) -> UpdateResult:
    """Upgrade packages for a plugin scoped to a specific runtime.

    Args:
        porringer: The porringer API instance.
        plugin_name: The installer plugin name.
        runtime_tag: Runtime tag to scope the upgrade.
        include_packages: Optional include-set of package names.
        discovered: Pre-discovered plugins.
        on_package_starting: Called with ``(package_name)`` before each
            package upgrade begins.
        on_package_completed: Called with ``(package_name, success, skipped)``
            after each package upgrade finishes.
    """
    result = UpdateResult(plugin=plugin_name)
    packages = await porringer.package.list_by_runtime(plugin_name, plugins=discovered)
    if packages is None:
        return result
    for rt in packages:
        if rt.tag != runtime_tag:
            continue
        for pkg in rt.packages:
            pkg_name = str(pkg.name)
            if include_packages is not None and pkg_name not in include_packages:
                continue
            if on_package_starting is not None:
                on_package_starting(pkg_name)
            ref = PackageRef(name=pkg_name)
            ar = await porringer.package.upgrade(
                plugin_name,
                ref,
                runtime_tag=runtime_tag,
                plugins=discovered,
            )
            if ar.skipped:
                result.already_latest.append(pkg_name)
                if on_package_completed is not None:
                    on_package_completed(pkg_name, False, True)
            elif ar.success:
                result.packages_updated.append(pkg_name)
                result.updated_packages.add(pkg_name)
                _capture_versions(result, pkg_name, ar)
                if on_package_completed is not None:
                    on_package_completed(pkg_name, True, False)
            else:
                result.packages_failed.append(pkg_name)
                if on_package_completed is not None:
                    on_package_completed(pkg_name, False, False)
        break
    return result


async def remove_package(
    porringer: API,
    plugin_name: str,
    package_name: str,
    *,
    runtime_tag: str | None = None,
    discovered: DiscoveredPlugins | None = None,
) -> bool:
    """Uninstall a single package.

    Args:
        porringer: The porringer API instance.
        plugin_name: The installer plugin name.
        package_name: The package to remove.
        runtime_tag: Optional runtime tag for per-runtime removal.
        discovered: Pre-discovered plugins.

    Returns:
        ``True`` if the removal succeeded.
    """
    ref = PackageRef(name=package_name)
    action_result = await porringer.package.uninstall(
        plugin_name,
        ref,
        runtime_tag=runtime_tag,
        plugins=discovered,
    )
    return action_result.success


def _record_completed_event(
    result: UpdateResult,
    ar: object,
    pkg_name: str,
    on_package_completed: Callable[[str, bool, bool], None] | None,
) -> None:
    """Record a single completed-event into *result* and fire the callback."""
    if ar.skipped:  # type: ignore[union-attr]
        if ar.skip_reason in {SkipReason.ALREADY_LATEST, SkipReason.ALREADY_INSTALLED}:  # type: ignore[union-attr]
            result.already_latest.append(pkg_name)
        if on_package_completed is not None and pkg_name:
            on_package_completed(pkg_name, False, True)
    elif ar.success:  # type: ignore[union-attr]
        result.packages_updated.append(pkg_name)
        if pkg_name:
            result.updated_packages.add(pkg_name)
        _capture_versions(result, pkg_name, ar)
        if on_package_completed is not None and pkg_name:
            on_package_completed(pkg_name, True, False)
    else:
        result.packages_failed.append(pkg_name)
        if on_package_completed is not None and pkg_name:
            on_package_completed(pkg_name, False, False)


async def update_all_tools(
    porringer: API,
    plugins: set[str] | None = None,
    include_packages: set[str] | None = None,
    *,
    discovered: DiscoveredPlugins | None = None,
    on_package_starting: Callable[[str], None] | None = None,
    on_package_completed: Callable[[str, bool, bool], None] | None = None,
) -> UpdateResult:
    """Re-sync all cached project manifests (bulk update).

    Args:
        porringer: The porringer API instance.
        plugins: Optional include-set of plugin names.
        include_packages: Optional include-set of package names.
        discovered: Pre-discovered plugins.
        on_package_starting: Called with ``(package_name)`` before each
            package action begins.
        on_package_completed: Called with ``(package_name, success, skipped)``
            after each package action completes.

    Returns:
        An :class:`UpdateResult` summarising the full run.
    """
    result = UpdateResult(plugin='*')
    loop = asyncio.get_running_loop()
    dir_results = await loop.run_in_executor(
        None,
        lambda: porringer.cache.list_directories(validate=True, check_manifest=True),
    )

    for dr in dir_results:
        if not dr.has_manifest:
            continue
        path = Path(dr.directory.path)
        params = SetupParameters(
            paths=[path],
            project_directory=path if path.is_dir() else None,
            strategy=SyncStrategy.LATEST,
            plugins=plugins,
            include_packages=include_packages,
        )
        try:
            async for event in porringer.sync.execute_stream(params, plugins=discovered):
                if isinstance(event, ActionStartedEvent):
                    pkg_name = str(event.action.package.name) if event.action.package else ''
                    if pkg_name and on_package_starting is not None:
                        on_package_starting(pkg_name)
                    continue
                if not isinstance(event, ActionCompletedEvent):
                    continue
                ar = event.result
                pkg_name = str(ar.action.package.name) if ar.action.package else ''
                _record_completed_event(result, ar, pkg_name, on_package_completed)
        except asyncio.CancelledError:
            raise
        result.manifests_processed += 1

    return result


# ---------------------------------------------------------------------------
# Auto-update scope policy
# ---------------------------------------------------------------------------


def resolve_auto_update_scope(
    plugin_auto_update: dict[str, bool | dict[str, bool]] | None,
    all_plugin_names: list[str],
    manifest_packages: dict[str, set[str]] | None = None,
) -> tuple[set[str] | None, set[str] | None]:
    """Derive plugin and package include-lists for auto-update.

    Walks ``plugin_auto_update`` to determine which plugins and packages
    should participate in automatic updates.

    Args:
        plugin_auto_update: The per-plugin auto-update config mapping.
        all_plugin_names: Every known (installed) plugin name.
        manifest_packages: Mapping of ``plugin_name`` → set of package
            names declared in cached manifests.

    Returns:
        A ``(enabled_plugins, include_packages)`` tuple.  Either element
        may be ``None`` meaning "no filtering".
    """
    mapping = plugin_auto_update

    disabled_plugins: set[str] = set()
    per_package_entries: dict[str, dict[str, bool]] = {}

    if mapping:
        for name, value in mapping.items():
            if ':' in name:
                continue
            if value is False:
                disabled_plugins.add(name)
            elif isinstance(value, dict):
                per_package_entries[name] = value

    enabled_plugins: set[str] | None = None
    if disabled_plugins:
        enabled_plugins = {n for n in all_plugin_names if n not in disabled_plugins}

    include_packages = _build_include_packages(
        per_package_entries,
        manifest_packages,
        disabled_plugins,
    )

    return enabled_plugins, include_packages


def _build_include_packages(
    per_package_entries: dict[str, dict[str, bool]],
    manifest_packages: dict[str, set[str]] | None,
    disabled_plugins: set[str],
) -> set[str] | None:
    """Build the set of package names eligible for auto-update."""
    if not per_package_entries and not manifest_packages:
        return None

    pkg_set: set[str] = set()
    if manifest_packages:
        for plugin_name, pkgs in manifest_packages.items():
            if plugin_name not in disabled_plugins:
                pkg_set |= pkgs

    for plugin_name, pkg_map in per_package_entries.items():
        if plugin_name in disabled_plugins:
            continue
        for pkg_name, enabled in pkg_map.items():
            if enabled:
                pkg_set.add(pkg_name)
            else:
                pkg_set.discard(pkg_name)

    return pkg_set or None
