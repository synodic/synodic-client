"""Tests for ToolUpdateResult dataclass in workers module."""

from __future__ import annotations

from synodic_client.application.workers import ToolUpdateResult


class TestToolUpdateResult:
    """Tests for the ToolUpdateResult dataclass."""

    @staticmethod
    def test_defaults() -> None:
        """Verify all fields start at zero / empty."""
        result = ToolUpdateResult()
        assert result.manifests_processed == 0
        assert result.updated == 0
        assert result.already_latest == 0
        assert result.failed == 0
        assert result.updated_packages == set()

    @staticmethod
    def test_fields_are_assignable() -> None:
        """Verify fields can be set via constructor."""
        result = ToolUpdateResult(
            manifests_processed=3,
            updated=2,
            already_latest=1,
            failed=0,
            updated_packages={'pdm', 'ruff'},
        )
        assert result.manifests_processed == 3
        assert result.updated == 2
        assert result.already_latest == 1
        assert result.failed == 0
        assert result.updated_packages == {'pdm', 'ruff'}

    @staticmethod
    def test_updated_packages_mutation() -> None:
        """Verify updated_packages is a mutable set."""
        result = ToolUpdateResult()
        result.updated_packages.add('uv')
        assert 'uv' in result.updated_packages

    @staticmethod
    def test_independent_set_per_instance() -> None:
        """Verify each instance gets its own set (field default_factory)."""
        a = ToolUpdateResult()
        b = ToolUpdateResult()
        a.updated_packages.add('foo')
        assert 'foo' not in b.updated_packages
