"""Core data models for the Synodic Client.

Contains configuration schemas (Pydantic), update-lifecycle enums and
dataclasses, and the immutable runtime configuration snapshot.  These
types are intentionally decoupled from I/O, business logic, and UI so
that every layer can import them without circular dependencies.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from typing import Any

from packaging.version import Version
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# BuildConfig — read-only, lives next to the executable
# ---------------------------------------------------------------------------


class BuildConfig(BaseModel):
    """Read-only configuration embedded next to the executable.

    Written by the packaging script (e.g. ``pdm run package -- --local-source``).
    Only contains the two fields the build system needs to seed.
    """

    # URL or local file path for Velopack releases.
    update_source: str | None = None

    # Update channel: "stable" or "dev".
    update_channel: str | None = None


# ---------------------------------------------------------------------------
# UserConfig — read-write, lives in the OS data directory
# ---------------------------------------------------------------------------


class UserConfig(BaseModel):
    """User-scoped configuration persisted in the OS application data directory.

    On Windows: ``%LOCALAPPDATA%/Synodic/config.json``.

    Every field is always saved.  There are no sparse/unset semantics —
    the on-disk file is a complete snapshot of the user's preferences.
    """

    # URL or local file path for Velopack releases.
    # None means use the default GitHub release source.
    update_source: str | None = None

    # Update channel: "stable" or "dev".
    # None means auto-detect from sys.frozen.
    update_channel: str | None = None

    # Interval in minutes between automatic update checks.
    # 0 disables automatic checking.  None uses the default (30 minutes).
    auto_update_interval_minutes: int | None = None

    # Interval in minutes between tool update checks.
    # 0 disables automatic checking.  None uses the default (20 minutes).
    tool_update_interval_minutes: int | None = None

    # Per-plugin and per-package auto-update toggle.
    #
    # Maps plugin name to:
    #   - ``True``  — all packages under this plugin auto-update (default).
    #   - ``False`` — the entire plugin is disabled from auto-update.
    #   - ``dict[str, bool]`` — per-package overrides within this plugin.
    #     Packages with ``True`` auto-update; ``False`` are skipped.
    #     Packages not listed inherit the manifest-aware default (ON for
    #     manifest-referenced packages, OFF for global packages).
    #
    # ``None`` or absent means all plugins auto-update with manifest-aware defaults.
    plugin_auto_update: dict[str, bool | dict[str, bool]] | None = None

    # Per-manifest pre-release overrides.  Outer key is a normalised
    # manifest path (or URL for remote manifests) produced by
    # ``normalize_manifest_key()``.  Inner value is a sorted list of
    # package names (case-insensitive) that should be checked for
    # pre-release updates even when the manifest does not set
    # ``include_prereleases: true`` on the package.  ``None`` means
    # no overrides anywhere.
    prerelease_packages: dict[str, list[str]] | None = None

    # Whether downloaded updates should be applied and restarted
    # automatically without user interaction.  None resolves to True.
    auto_apply: bool | None = None

    # Whether the application should start automatically with the OS.
    # None means use the default (enabled).  Explicitly False disables
    # auto-startup.
    auto_start: bool | None = None

    # Enable verbose DEBUG-level logging to the log file.
    # None resolves to False (INFO level).
    debug_logging: bool | None = None

    # ISO 8601 timestamp of the last successful client self-update.
    # None means no update has been recorded.
    last_client_update: str | None = None

    # Per-package timestamps of the last successful tool update.
    # Maps "plugin/package" → ISO 8601 timestamp.  None means no
    # tool updates have been recorded.
    last_tool_updates: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Update channel & state enums
# ---------------------------------------------------------------------------


class UpdateChannel(StrEnum):
    """Update channel selection."""

    STABLE = 'stable'
    DEVELOPMENT = 'development'


class UpdateState(Enum):
    """State of an update operation."""

    NO_UPDATE = auto()
    UPDATE_AVAILABLE = auto()
    DOWNLOADING = auto()
    DOWNLOADED = auto()
    APPLYING = auto()
    APPLIED = auto()
    FAILED = auto()


# ---------------------------------------------------------------------------
# Update dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UpdateInfo:
    """Information about an available update."""

    available: bool
    current_version: Version
    latest_version: Version | None = None
    error: str | None = None

    # Internal: Velopack update info for download/apply
    _velopack_info: Any = field(default=None, repr=False)

    # Internal: True when the update was discovered via the manifest
    # fallback rather than the Velopack SDK.  The download path uses
    # this to route to a direct HTTP download instead of the SDK's
    # GithubSource (which cannot find prerelease assets).
    _used_manifest_fallback: bool = field(default=False, repr=False)


# Default interval for automatic update checks (minutes)
DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES = 5

# Default interval for tool update checks (minutes)
DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES = 5

# GitHub repository base URL.  Transformed into a release-asset URL
# by :func:`~synodic_client.updater.github_release_asset_url` at resolution
# time so that Velopack's ``HttpSource`` can fetch
# ``releases.{channel}.json`` from the correct GitHub Releases download path.
GITHUB_REPO_URL = 'https://github.com/synodic/synodic-client'

_PLATFORM_SUFFIXES: dict[str, str] = {
    'win32': 'win',
    'linux': 'linux',
    'darwin': 'osx',
}


def platform_suffix() -> str:
    """Return the Velopack channel suffix for the current platform."""
    try:
        return _PLATFORM_SUFFIXES[sys.platform]
    except KeyError:
        raise RuntimeError(f'Unsupported platform for updates: {sys.platform}') from None


@dataclass
class UpdateConfig:
    """Configuration for the updater."""

    # GitHub repository URL for Velopack to discover releases
    repo_url: str = GITHUB_REPO_URL

    # Channel determines whether to use dev or stable releases
    channel: UpdateChannel = UpdateChannel.STABLE

    # Interval in minutes between automatic update checks (0 = disabled)
    auto_update_interval_minutes: int = DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    # Interval in minutes between tool update checks (0 = disabled)
    tool_update_interval_minutes: int = DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    @property
    def channel_name(self) -> str:
        """Get the channel name for Velopack.

        Combines the update track (dev/stable) with a platform suffix
        so each OS has its own release manifest and nupkg files.
        """
        base = 'dev' if self.channel == UpdateChannel.DEVELOPMENT else 'stable'
        return f'{base}-{platform_suffix()}'


# ---------------------------------------------------------------------------
# ResolvedConfig — immutable runtime snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedConfig:
    """Immutable runtime configuration snapshot.

    Constructed by :func:`~synodic_client.resolution.resolve_config` from
    the merged ``BuildConfig`` + ``UserConfig`` layers.  Every field has a
    concrete, non-``None`` value (except ``update_source`` and
    ``prerelease_packages`` where ``None`` is a valid semantic value
    meaning "use default" / "no overrides").
    """

    update_source: str | None
    update_channel: str
    auto_update_interval_minutes: int
    tool_update_interval_minutes: int
    plugin_auto_update: dict[str, bool | dict[str, bool]] | None
    prerelease_packages: dict[str, list[str]] | None
    auto_apply: bool
    auto_start: bool
    debug_logging: bool
    last_client_update: str | None
    last_tool_updates: dict[str, str] | None
