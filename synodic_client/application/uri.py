"""URI parsing and path utilities for the ``synodic://`` scheme."""

import logging
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import url2pathname

logger = logging.getLogger(__name__)


def parse_uri(uri: str) -> dict[str, str | list[str]]:
    """Parse a ``synodic://`` URI into its components.

    Example:
        ``synodic://install?manifest=https://example.com/foo.toml``
        returns ``{'action': 'install', 'manifest': ['https://example.com/foo.toml']}``.

    Args:
        uri: A ``synodic://`` URI string.

    Returns:
        A dict with ``'action'`` (the host/path) and any query parameters.
    """
    parsed = urlparse(uri)
    result: dict[str, str | list[str]] = {
        'action': parsed.netloc or parsed.path.strip('/'),
    }
    result.update(parse_qs(parsed.query))
    return result


def normalize_manifest_key(path_or_url: str) -> str:
    """Return a canonical key for a manifest path or URL.

    Local paths are resolved to absolute form so that the same manifest on
    disk always maps to the same config entry regardless of how it was
    referenced (relative, symlinked, etc.).  Remote URLs are returned
    unchanged.
    """
    parsed = urlparse(path_or_url)
    if parsed.scheme in {'http', 'https'}:
        return path_or_url
    try:
        return str(Path(path_or_url).resolve())
    except Exception:
        return path_or_url


def resolve_local_path(manifest_ref: str) -> Path | None:
    r"""Return a ``Path`` if *manifest_ref* points to a local file, else ``None``.

    Recognised forms:
    * ``file:///C:/path/to/porringer.json``
    * An absolute OS path (``C:\...`` or ``/...``)
    * A relative path that exists on disk
    """
    parsed = urlparse(manifest_ref)

    if parsed.scheme == 'file':
        # file:///C:/Users/... → C:/Users/...
        return Path(url2pathname(parsed.path))

    if parsed.scheme in {'http', 'https'}:
        return None

    # No scheme — treat as a filesystem path
    candidate = Path(manifest_ref)
    if candidate.is_absolute() or candidate.exists():
        return candidate

    return None


def safe_rmtree(path: str) -> None:
    """Remove a directory tree, ignoring errors."""
    try:
        shutil.rmtree(path)
    except OSError:
        logger.debug('Failed to clean up temp dir: %s', path)
