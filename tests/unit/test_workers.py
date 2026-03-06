"""Tests for ToolUpdateResult dataclass and runtime package workers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from porringer.core.schema import Package
from porringer.schema.execution import SetupAction, SetupActionResult
from porringer.schema.plugin import RuntimePackageResult

from synodic_client.application.schema import ToolUpdateResult
from synodic_client.application.workers import run_runtime_package_updates

_EXPECTED_RUNTIME_UPGRADES = 2


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


class TestRunRuntimePackageUpdates:
    """Tests for the run_runtime_package_updates worker."""

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
            run_runtime_package_updates(porringer, 'pipx', '3.12'),
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
            run_runtime_package_updates(porringer, 'pipx', '3.12'),
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
            run_runtime_package_updates(
                porringer,
                'pipx',
                '3.12',
                include_packages={'ruff'},
            ),
        )
        assert result.updated == 1
        assert result.updated_packages == {'ruff'}
        porringer.package.upgrade.assert_called_once()
