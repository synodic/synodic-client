"""Tests for compute_install_plan and format_install_summary."""

from __future__ import annotations

from unittest.mock import MagicMock

from porringer.schema import SetupActionResult, SkipReason, SyncStrategy
from porringer.schema.plugin import PluginKind

from synodic_client.operations.schema import (
    ActionCheckResult,
    InstallPlan,
    compute_install_plan,
    format_install_summary,
)


def _make_check_result(
    index: int,
    status: str,
    *,
    kind: PluginKind | None = PluginKind.PACKAGE,
    skipped: bool = False,
    skip_reason: SkipReason | None = None,
    success: bool = True,
) -> ActionCheckResult:
    """Build an ActionCheckResult with a mock action and result."""
    action = MagicMock()
    action.kind = kind
    result = MagicMock(spec=SetupActionResult)
    result.success = success
    result.skipped = skipped
    result.skip_reason = skip_reason
    return ActionCheckResult(index=index, action=action, result=result, status=status)


# ---------------------------------------------------------------------------
# compute_install_plan
# ---------------------------------------------------------------------------


class TestComputeInstallPlan:
    """Tests for compute_install_plan()."""

    @staticmethod
    def test_empty_results() -> None:
        """Empty check results → all empty, install disabled."""
        plan = compute_install_plan([])
        assert plan.install_indices == ()
        assert plan.satisfied_indices == ()
        assert plan.upgradable_indices == ()
        assert plan.post_sync_indices == ()
        assert plan.install_enabled is False
        assert plan.has_post_sync is False

    @staticmethod
    def test_all_satisfied() -> None:
        """All actions already satisfied → install disabled."""
        results = [
            _make_check_result(0, 'Already installed'),
            _make_check_result(1, 'Already latest'),
        ]
        plan = compute_install_plan(results)
        assert plan.install_indices == ()
        assert plan.satisfied_indices == (0, 1)
        assert plan.install_enabled is False
        assert 'already satisfied' in plan.summary

    @staticmethod
    def test_needed_actions() -> None:
        """Needed actions → install enabled, correct indices."""
        results = [
            _make_check_result(0, 'Needed'),
            _make_check_result(1, 'Already installed'),
            _make_check_result(2, 'Needed'),
        ]
        plan = compute_install_plan(results)
        assert plan.install_indices == (0, 2)
        assert plan.satisfied_indices == (1,)
        assert plan.install_enabled is True

    @staticmethod
    def test_update_available_excluded_from_install() -> None:
        """Update-available actions are tracked as upgradable, not install."""
        results = [
            _make_check_result(0, 'Update available'),
            _make_check_result(1, 'Needed'),
        ]
        plan = compute_install_plan(results)
        assert plan.upgradable_indices == (0,)
        assert plan.install_indices == (1,)
        assert plan.install_enabled is True
        assert 'upgradable' in plan.summary

    @staticmethod
    def test_post_sync_tracked_separately() -> None:
        """Post-sync commands (kind=None) are tracked in post_sync_indices."""
        results = [
            _make_check_result(0, 'Needed'),
            _make_check_result(1, 'Pending', kind=None),
            _make_check_result(2, 'Pending', kind=None),
        ]
        plan = compute_install_plan(results)
        assert plan.post_sync_indices == (1, 2)
        assert plan.has_post_sync is True
        assert plan.install_indices == (0,)
        assert plan.install_enabled is True

    @staticmethod
    def test_only_post_sync_means_install_disabled() -> None:
        """Only post-sync commands → install disabled, has_post_sync True."""
        results = [
            _make_check_result(0, 'Pending', kind=None),
        ]
        plan = compute_install_plan(results)
        assert plan.install_enabled is False
        assert plan.has_post_sync is True
        assert plan.post_sync_indices == (0,)

    @staticmethod
    def test_ready_actions_included_in_install() -> None:
        """Ready (PROJECT kind) actions are included in install."""
        results = [
            _make_check_result(0, 'Ready', kind=PluginKind.PROJECT),
        ]
        plan = compute_install_plan(results)
        assert plan.install_indices == (0,)
        assert plan.install_enabled is True

    @staticmethod
    def test_strategy_is_always_minimal() -> None:
        """Strategy should always be MINIMAL since updates are excluded."""
        results = [_make_check_result(0, 'Needed')]
        plan = compute_install_plan(results)
        assert plan.strategy == SyncStrategy.MINIMAL

    @staticmethod
    def test_unavailable_and_failed_not_in_install() -> None:
        """Unavailable and failed actions don't get install indices."""
        results = [
            _make_check_result(0, 'Not installed'),
            _make_check_result(1, 'Failed'),
        ]
        plan = compute_install_plan(results)
        assert plan.install_indices == ()
        assert plan.install_enabled is False

    @staticmethod
    def test_plan_is_frozen() -> None:
        """InstallPlan should be a frozen dataclass."""
        results = [_make_check_result(0, 'Needed')]
        plan = compute_install_plan(results)
        assert isinstance(plan, InstallPlan)


# ---------------------------------------------------------------------------
# format_install_summary
# ---------------------------------------------------------------------------


class TestFormatInstallSummary:
    """Tests for format_install_summary()."""

    @staticmethod
    def test_no_results() -> None:
        """No results at all → 'No actions executed.'"""
        summary = format_install_summary()
        assert 'No actions executed' in summary

    @staticmethod
    def test_install_results_only() -> None:
        """Install results without post-sync."""
        r1 = MagicMock(spec=SetupActionResult, success=True, skipped=False)
        r2 = MagicMock(spec=SetupActionResult, success=True, skipped=True)
        r3 = MagicMock(spec=SetupActionResult, success=False, skipped=False)
        summary = format_install_summary(install_results=[r1, r2, r3])
        assert '1 succeeded' in summary
        assert '1 skipped' in summary
        assert '1 failed' in summary

    @staticmethod
    def test_with_pre_skipped() -> None:
        """Pre-skipped count is included."""
        summary = format_install_summary(pre_skipped_count=3)
        assert '3 already satisfied' in summary

    @staticmethod
    def test_with_post_sync() -> None:
        """Post-sync results are appended."""
        r1 = MagicMock(spec=SetupActionResult, success=True, skipped=False)
        ps1 = MagicMock(spec=SetupActionResult, success=True, skipped=False)
        ps2 = MagicMock(spec=SetupActionResult, success=False, skipped=False)
        summary = format_install_summary(
            install_results=[r1],
            post_sync_results=[ps1, ps2],
        )
        assert 'Post-sync' in summary
        assert '1 ran' in summary
        assert '1 failed' in summary

    @staticmethod
    def test_post_sync_only() -> None:
        """Only post-sync results → includes post-sync section."""
        ps1 = MagicMock(spec=SetupActionResult, success=True, skipped=False)
        summary = format_install_summary(post_sync_results=[ps1])
        assert 'Post-sync' in summary
        assert '1 ran' in summary
