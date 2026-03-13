"""Tests for operations.project module."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from synodic_client.operations.project import add_project, list_projects, remove_project
from synodic_client.operations.schema import ProjectInfo


def _make_dir_result(path: str, *, exists: bool = True, has_manifest: bool = False) -> MagicMock:
    """Create a mock DirectoryResult."""
    result = MagicMock()
    result.directory.path = path
    result.directory.name = Path(path).name
    result.exists = exists
    result.has_manifest = has_manifest
    return result


class TestListProjects:
    """Tests for list_projects()."""

    @staticmethod
    def test_empty() -> None:
        """No cached directories returns empty list."""
        api = MagicMock()
        api.cache.list_directories.return_value = []
        assert list_projects(api) == []

    @staticmethod
    def test_returns_project_info() -> None:
        """Each directory result maps to a ProjectInfo."""
        api = MagicMock()
        api.cache.list_directories.return_value = [
            _make_dir_result('/a/foo', exists=True, has_manifest=True),
            _make_dir_result('/b/bar', exists=False, has_manifest=False),
        ]
        result = list_projects(api)
        expected_count = 2
        assert len(result) == expected_count
        assert result[0] == ProjectInfo(path='/a/foo', name='foo', exists=True, has_manifest=True)
        assert result[1] == ProjectInfo(path='/b/bar', name='bar', exists=False, has_manifest=False)

    @staticmethod
    def test_passes_validation_flags() -> None:
        """list_projects passes validate=True, check_manifest=True."""
        api = MagicMock()
        api.cache.list_directories.return_value = []
        list_projects(api)
        api.cache.list_directories.assert_called_once_with(validate=True, check_manifest=True)


class TestAddProject:
    """Tests for add_project()."""

    @staticmethod
    def test_not_a_directory(tmp_path: Path) -> None:
        """Raises NotADirectoryError for a missing directory."""
        api = MagicMock()
        with pytest.raises(NotADirectoryError, match='Not a directory'):
            add_project(api, tmp_path / 'nonexistent')

    @staticmethod
    def test_adds_and_returns_info(tmp_path: Path) -> None:
        """Adds the directory and returns ProjectInfo."""
        api = MagicMock()
        api.cache.list_directories.return_value = [
            _make_dir_result(str(tmp_path), exists=True, has_manifest=False),
        ]
        info = add_project(api, tmp_path)
        api.cache.add_directory.assert_called_once_with(tmp_path)
        assert info.path == str(tmp_path)


class TestRemoveProject:
    """Tests for remove_project()."""

    @staticmethod
    def test_delegates_to_cache() -> None:
        """remove_project calls porringer.cache.remove_directory."""
        api = MagicMock()
        remove_project(api, '/tmp/foo')
        api.cache.remove_directory.assert_called_once_with(Path('/tmp/foo'))
