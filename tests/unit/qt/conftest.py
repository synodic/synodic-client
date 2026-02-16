"""Configuration for Qt-dependent tests.

Tests in this directory require PySide6.  When the Qt runtime libraries
are not available (e.g. on headless Linux CI), the entire directory is
skipped automatically.
"""

import pytest

pytest.importorskip('PySide6.QtWidgets', reason='PySide6 requires system Qt libraries')
