"""Tests for PreviewModel and ActionState."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from porringer.schema import SetupAction
from porringer.schema.plugin import PluginKind

from synodic_client.application.screen.schema import ActionState, PreviewModel, PreviewPhase
from synodic_client.application.uri import normalize_manifest_key
from synodic_client.operations.schema import InstallPlan, SyncStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    *,
    kind: PluginKind | None = PluginKind.PACKAGE,
    description: str = 'Install requests',
    installer: str = 'pip',
    package: str = 'requests',
    **overrides: Any,
) -> SetupAction:
    """Create a mock SetupAction with sensible defaults."""
    action = MagicMock(spec=SetupAction)
    action.kind = kind
    action.description = description
    action.installer = installer
    pkg_mock = MagicMock()
    pkg_mock.name = package
    pkg_mock.configure_mock(**{'__str__': MagicMock(return_value=package)})
    action.package = pkg_mock
    action.package_description = overrides.get('package_description', description)
    action.command = overrides.get('command')
    action.include_prereleases = overrides.get('include_prereleases', False)
    action.plugin_target = overrides.get('plugin_target')
    return action


# ---------------------------------------------------------------------------
# ActionState
# ---------------------------------------------------------------------------


class TestActionState:
    """Verify ActionState dataclass behaviour."""

    @staticmethod
    def test_defaults() -> None:
        """Defaults should be sensible for a freshly-created state."""
        act = _make_action()
        state = ActionState(action=act)
        assert state.status == 'Checking\u2026'
        assert state.log_lines == []

    @staticmethod
    def test_log_lines_are_independent() -> None:
        """Each ActionState should have its own independent log list."""
        a = ActionState(action=_make_action())
        b = ActionState(action=_make_action(package='ruff'))
        a.log_lines.append(('hello', None))
        assert b.log_lines == []


# ---------------------------------------------------------------------------
# PreviewModel
# ---------------------------------------------------------------------------


class TestPreviewModel:
    """Tests for the PreviewModel data layer."""

    @staticmethod
    def test_initial_phase_is_idle() -> None:
        """A fresh model starts in IDLE phase."""
        model = PreviewModel()
        assert model.phase is PreviewPhase.IDLE

    @staticmethod
    def test_install_enabled_false_when_idle() -> None:
        """Install button should not be enabled in IDLE phase."""
        model = PreviewModel()
        assert model.install_enabled is False

    @staticmethod
    def test_install_enabled_true_when_ready_with_needed_actions() -> None:
        """Install should be enabled when READY and install_plan says so."""
        model = PreviewModel()
        model.phase = PreviewPhase.READY
        state = ActionState(action=_make_action())
        state.status = 'Needed'
        model.action_states.append(state)
        model.install_plan = InstallPlan(
            install_indices=(0,),
            satisfied_indices=(),
            upgradable_indices=(),
            post_sync_indices=(),
            strategy=SyncStrategy.MINIMAL,
            install_enabled=True,
            has_post_sync=False,
            summary='1 action(s): 1 needed.',
        )
        assert model.install_enabled is True

    @staticmethod
    def test_install_enabled_false_when_only_upgradable() -> None:
        """Install should be disabled when only upgradable actions exist.

        Upgradable actions are managed in the Tools view, not via install.
        """
        model = PreviewModel()
        model.phase = PreviewPhase.READY
        state = ActionState(action=_make_action())
        state.status = 'Update available'
        model.action_states.append(state)
        model.install_plan = InstallPlan(
            install_indices=(),
            satisfied_indices=(),
            upgradable_indices=(0,),
            post_sync_indices=(),
            strategy=SyncStrategy.MINIMAL,
            install_enabled=False,
            has_post_sync=False,
            summary='1 action(s): 1 upgradable (manage in Tools).',
        )
        assert model.install_enabled is False

    @staticmethod
    def test_install_enabled_false_when_ready_but_all_satisfied() -> None:
        """Install should be disabled when all actions are satisfied."""
        model = PreviewModel()
        model.phase = PreviewPhase.READY
        state = ActionState(action=_make_action())
        state.status = 'Already installed'
        model.action_states.append(state)
        assert model.install_enabled is False

    @staticmethod
    def test_has_post_sync_for_command_actions() -> None:
        """Command actions (kind=None) are tracked as post-sync."""
        model = PreviewModel()
        model.phase = PreviewPhase.READY
        state = ActionState(action=_make_action(kind=None, description='Run setup'))
        state.status = 'Pending'
        model.action_states.append(state)
        model.install_plan = InstallPlan(
            install_indices=(),
            satisfied_indices=(),
            upgradable_indices=(),
            post_sync_indices=(0,),
            strategy=SyncStrategy.MINIMAL,
            install_enabled=False,
            has_post_sync=True,
            summary='1 action(s): 1 pending.',
        )
        assert model.install_enabled is False
        assert model.has_post_sync is True

    @staticmethod
    def test_install_enabled_false_when_installing() -> None:
        """Install should be disabled during installation."""
        model = PreviewModel()
        model.phase = PreviewPhase.INSTALLING
        state = ActionState(action=_make_action())
        state.status = 'Needed'
        model.action_states.append(state)
        assert model.install_enabled is False

    @staticmethod
    def test_install_plan_indices_partition() -> None:
        """Install plan correctly partitions actions."""
        model = PreviewModel()
        model.phase = PreviewPhase.READY
        needed = ActionState(action=_make_action(package='a'))
        needed.status = 'Needed'
        satisfied = ActionState(action=_make_action(package='b'))
        satisfied.status = 'Already installed'
        upgradable = ActionState(action=_make_action(package='c'))
        upgradable.status = 'Update available'
        model.action_states = [needed, satisfied, upgradable]
        model.install_plan = InstallPlan(
            install_indices=(0,),
            satisfied_indices=(1,),
            upgradable_indices=(2,),
            post_sync_indices=(),
            strategy=SyncStrategy.MINIMAL,
            install_enabled=True,
            has_post_sync=False,
            summary='3 action(s): 1 needed, 1 upgradable (manage in Tools), 1 already satisfied.',
        )
        assert model.install_enabled is True
        assert model.install_plan.install_indices == (0,)
        assert model.install_plan.satisfied_indices == (1,)
        assert model.install_plan.upgradable_indices == (2,)

    @staticmethod
    def test_action_state_for_found() -> None:
        """action_state_for should find a state by matching action key."""
        model = PreviewModel()
        act = _make_action(package='ruff')
        state = ActionState(action=act)
        model.action_states.append(state)
        found = model.action_state_for(act)
        assert found is state

    @staticmethod
    def test_action_state_for_not_found() -> None:
        """action_state_for should return None for unknown actions."""
        model = PreviewModel()
        act = _make_action(package='ruff')
        assert model.action_state_for(act) is None

    @staticmethod
    def test_has_same_manifest_match() -> None:
        """has_same_manifest should return True for matching keys."""
        model = PreviewModel()
        model.manifest_key = normalize_manifest_key('https://example.com/porringer.json')
        assert model.has_same_manifest('https://example.com/porringer.json') is True

    @staticmethod
    def test_has_same_manifest_mismatch() -> None:
        """has_same_manifest should return False for different keys."""
        model = PreviewModel()
        model.manifest_key = normalize_manifest_key('https://example.com/a.json')
        assert model.has_same_manifest('https://example.com/b.json') is False

    @staticmethod
    def test_has_same_manifest_when_empty() -> None:
        """has_same_manifest should return False when no manifest loaded."""
        model = PreviewModel()
        assert model.has_same_manifest('https://example.com/porringer.json') is False
