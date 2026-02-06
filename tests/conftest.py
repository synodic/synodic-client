"""Shared pytest fixtures for the Synodic Client test suite."""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES_DIR = _REPO_ROOT / 'examples'


def _discover_example_dirs() -> list[Path]:
    """Return all subdirectories under ``examples/``."""
    if not _EXAMPLES_DIR.is_dir():
        return []
    return sorted(child for child in _EXAMPLES_DIR.iterdir() if child.is_dir())


@pytest.fixture(params=_discover_example_dirs(), ids=lambda p: p.name)
def example_dir(request: pytest.FixtureRequest) -> Path:
    """Parametrised fixture yielding each example directory in turn."""
    return request.param
