"""Tests for ToolUpdateResult dataclass in workers module."""

from __future__ import annotations

from synodic_client.application.schema import ToolUpdateResult


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
        expected_manifests = 3
        expected_updated = 2
        expected_latest = 1
        expected_failed = 0
        expected_packages = {'pdm', 'ruff'}
        result = ToolUpdateResult(
            manifests_processed=expected_manifests,
            updated=expected_updated,
            already_latest=expected_latest,
            failed=expected_failed,
            updated_packages=expected_packages,
        )
        assert result.manifests_processed == expected_manifests
        assert result.updated == expected_updated
        assert result.already_latest == expected_latest
        assert result.failed == expected_failed
        assert result.updated_packages == expected_packages

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
