"""URI parsing utilities for the ``synodic://`` scheme."""

from urllib.parse import parse_qs, urlparse


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
