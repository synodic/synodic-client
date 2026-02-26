"""Configuration for Qt-dependent tests.

Tests in this directory require PySide6.  When the Qt runtime libraries
are not available (e.g. on headless Linux CI), the entire directory is
skipped automatically.

All Qt tests run with the ``offscreen`` platform plugin so that no
windows appear on screen during the test run.
"""

import os
import sys

# Force offscreen rendering *before* any PySide6 import.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6.QtWidgets', reason='PySide6 requires system Qt libraries')

from PySide6.QtWidgets import QApplication

# Single shared QApplication for all Qt tests in this directory.
_app = QApplication.instance() or QApplication(sys.argv)
