"""Tests for UpdateResult dataclass and runtime package operations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from porringer.core.schema import Package
from porringer.schema.execution import SetupAction, SetupActionResult
from porringer.schema.plugin import RuntimePackageResult

from synodic_client.operations.schema import UpdateResult
from synodic_client.operations.tool import update_runtime_plugin

_EXPECTED_RUNTIME_UPGRADES = 2


class TestUpdateResult:
    """Tests for the UpdateResult dataclass."""

    @staticmethod
    def test_defaults() -> None:
        """Verify all fields start at zero / empty."""
        result = UpdateResult()
        assert result.manifests_processed == 0
        assert result.updated == 0
        assert len(result.already_latest) == 0
        assert result.failed == 0
        assert result.updated_packages == set()

    @staticmethod
    def test_fields_are_assignable() -> None:
        """Verify fields can be set via constructor."""
        expected_manifests = 3
        expected_updated = 2
        expected_packages = {'pdm', 'ruff'}
        result = UpdateResult(
            manifests_processed=expected_manifests,
            packages_updated=['a', 'b'],
            already_latest=['c'],
            packages_failed=[],
            updated_packages=expected_packages,
        )
        assert result.manifests_processed == expected_manifests
        assert result.updated == expected_updated
        assert len(result.already_latest) == 1
        assert result.failed == 0
        assert result.updated_packages == expected_packages

    @staticmethod
    def test_updated_packages_mutation() -> None:
        """Verify updated_packages is a mutable set."""
        result = UpdateResult()
        result.updated_packages.add('uv')
        assert 'uv' in result.updated_packages

    @staticmethod
    def test_independent_set_per_instance() -> None:
        """Verify each instance gets its own set (field default_factory)."""
        a = UpdateResult()
        b = UpdateResult()
        a.updated_packages.add('foo')
        assert 'foo' not in b.updated_packages


class TestUpdateRuntimePlugin:
    """Tests for the update_runtime_plugin operation."""

    @staticmethod
    def test_upgrades_packages_for_matching_tag() -> None:
        """Packages from the matching runtime tag are upgraded."""
        porringer = MagicMock()
        porringer.package.list_by_runtime = AsyncMock(
            return_value=[
                RuntimePackageResult(
                    provider='pim',
                    tag='3.12',
                    executable=Path('/usr/bin/python3.12'),
                    packages=[
                        Package(name='pdm', version='2.22.0'),
                        Package(name='ruff', version='0.1.0'),
                    ],
                ),
                RuntimePackageResult(
                    provider='pim',
                    tag='3.11',
                    executable=Path('/usr/bin/python3.11'),
                    packages=[Package(name='black', version='24.0')],
                ),
            ],
        )
        porringer.package.upgrade = AsyncMock(
            return_value=SetupActionResult(
                action=SetupAction(description='upgrade'),
                success=True,
            ),
        )
        result = asyncio.run(
            update_runtime_plugin(porringer, 'pipx', '3.12'),
        )
        assert result.updated == _EXPECTED_RUNTIME_UPGRADES
        assert result.updated_packages == {'pdm', 'ruff'}
        # Only the matching runtime's packages should be upgraded
        assert porringer.package.upgrade.call_count == _EXPECTED_RUNTIME_UPGRADES

    @staticmethod
    def test_skips_non_matching_tag() -> None:
        """Packages from non-matching runtimes are not touched."""
        porringer = MagicMock()
        porringer.package.list_by_runtime = AsyncMock(
            return_value=[
                RuntimePackageResult(
                    provider='pim',
                    tag='3.11',
                    executable=Path('/usr/bin/python3.11'),
                    packages=[Package(name='pdm', version='2.22.0')],
                ),
            ],
        )
        porringer.package.upgrade = AsyncMock()
        result = asyncio.run(
            update_runtime_plugin(porringer, 'pipx', '3.12'),
        )
        assert result.updated == 0
        porringer.package.upgrade.assert_not_called()

    @staticmethod
    def test_include_packages_filters() -> None:
        """Only packages in include_packages are upgraded."""
        porringer = MagicMock()
        porringer.package.list_by_runtime = AsyncMock(
            return_value=[
                RuntimePackageResult(
                    provider='pim',
                    tag='3.12',
                    executable=Path('/usr/bin/python3.12'),
                    packages=[
                        Package(name='pdm', version='2.22.0'),
                        Package(name='ruff', version='0.1.0'),
                    ],
                ),
            ],
        )
        porringer.package.upgrade = AsyncMock(
            return_value=SetupActionResult(
                action=SetupAction(description='upgrade'),
                success=True,
            ),
        )
        result = asyncio.run(
            update_runtime_plugin(
                porringer,
                'pipx',
                '3.12',
                include_packages={'ruff'},
            ),
        )
        assert result.updated == 1
        assert result.updated_packages == {'ruff'}
        porringer.package.upgrade.assert_called_once()
