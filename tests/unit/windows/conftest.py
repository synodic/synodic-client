"""Configuration for Windows-only tests.

Tests in this directory require the ``winreg`` stdlib module and are
skipped automatically on non-Windows platforms.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip('winreg', reason='winreg is only available on Windows')


def make_registry_key() -> MagicMock:
    """Build a ``MagicMock`` that behaves as a context-managed registry key."""
    key = MagicMock()
    key.__enter__ = MagicMock(return_value=key)
    key.__exit__ = MagicMock(return_value=False)
    return key
