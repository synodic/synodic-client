"""Configuration for Windows-only tests.

Tests in this directory require the ``winreg`` stdlib module and are
skipped automatically on non-Windows platforms.
"""

import pytest

pytest.importorskip('winreg', reason='winreg is only available on Windows')
