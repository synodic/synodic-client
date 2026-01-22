"""Schema for the client"""

from enum import Enum

from pydantic import BaseModel


class VersionInformation(BaseModel):
    """Comparable information that can be extracted from a Python package"""

    version: str


class UpdateChannel(str, Enum):
    """Update channel for selecting release types."""

    STABLE = 'stable'
    DEVELOPMENT = 'development'


class UpdateStatus(str, Enum):
    """Status of an update check or operation."""

    NO_UPDATE = 'no_update'
    UPDATE_AVAILABLE = 'update_available'
    DOWNLOADING = 'downloading'
    DOWNLOADED = 'downloaded'
    APPLYING = 'applying'
    APPLIED = 'applied'
    FAILED = 'failed'
    ROLLBACK_REQUIRED = 'rollback_required'


class UpdateCheckResult(BaseModel):
    """Result of an update check operation."""

    status: UpdateStatus
    current_version: str
    latest_version: str | None = None
    download_url: str | None = None
    error_message: str | None = None


class UpdateProgress(BaseModel):
    """Progress information for an update download."""

    bytes_downloaded: int
    total_bytes: int | None = None
    percentage: float | None = None
