"""Tests for the ActionCard and ActionCardList widgets."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from porringer.schema import (
    SetupAction,
    SetupActionResult,
    SkipReason,
)
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from synodic_client.application.screen import is_version_specifier
from synodic_client.application.screen.action_card import (
    ActionCard,
    ActionCardList,
    action_sort_key,
)
from synodic_client.application.theme import (
    ACTION_CARD_EXECUTING_STYLE,
    ACTION_CARD_SKELETON_STYLE,
    ACTION_CARD_STATUS_DONE,
    ACTION_CARD_STATUS_FAILED,
    ACTION_CARD_STATUS_NEEDED,
    ACTION_CARD_STATUS_PENDING,
    ACTION_CARD_STATUS_RUNNING,
    ACTION_CARD_STATUS_SATISFIED,
    ACTION_CARD_STATUS_SKIPPED,
    ACTION_CARD_STATUS_UPDATE,
    ACTION_CARD_STYLE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    *,
    kind: PluginKind | None = PluginKind.PACKAGE,
    description: str = 'Install requests',
    installer: str | None = 'pip',
    package: str = 'requests',
    **overrides: Any,
) -> SetupAction:
    """Create a mock SetupAction with sensible defaults.

    Extra keyword arguments are set as attributes on the mock, supporting
    ``package_description``, ``include_prereleases``, ``command``,
    ``cli_command``, and ``plugin_target``.
    """
    action = MagicMock(spec=SetupAction)
    action.kind = kind
    action.description = description
    action.installer = installer
    pkg_mock = MagicMock()
    pkg_mock.name = package
    pkg_mock.constraint = overrides.get('constraint')
    pkg_mock.configure_mock(**{'__str__': MagicMock(return_value=package)})
    action.package = pkg_mock
    action.package_description = overrides.get('package_description', description)
    action.command = overrides.get('command')
    action.include_prereleases = overrides.get('include_prereleases', False)
    action.plugin_target = overrides.get('plugin_target')
    return action


def _make_result(
    *,
    success: bool = True,
    skipped: bool = False,
    skip_reason: SkipReason | None = None,
    message: str | None = None,
    **overrides: Any,
) -> SetupActionResult:
    """Create a SetupActionResult.

    Extra keyword arguments (``action``, ``installed_version``,
    ``available_version``, ``cli_command``) are forwarded to the constructor.
    """
    return SetupActionResult(
        action=overrides.get('action') or _make_action(),
        success=success,
        skipped=skipped,
        skip_reason=skip_reason,
        message=message,
        installed_version=overrides.get('installed_version'),
        available_version=overrides.get('available_version'),
        cli_command=overrides.get('cli_command'),
    )


# ---------------------------------------------------------------------------
# ActionCard — skeleton
# ---------------------------------------------------------------------------


class TestActionCardSkeleton:
    """Tests for skeleton ActionCard."""

    @staticmethod
    def test_skeleton_card_has_skeleton_style() -> None:
        """Skeleton cards use the skeleton stylesheet."""
        card = ActionCard(skeleton=True)
        assert ACTION_CARD_SKELETON_STYLE in card.styleSheet()

    @staticmethod
    def test_skeleton_card_status_text_is_empty() -> None:
        """Skeleton cards return empty status text."""
        card = ActionCard(skeleton=True)
        assert not card.status_text()

    @staticmethod
    def test_skeleton_populate_does_nothing() -> None:
        """Calling populate on a skeleton card is a no-op."""
        card = ActionCard(skeleton=True)
        action = _make_action()
        card.populate(action)
        assert not card.status_text()

    @staticmethod
    def test_skeleton_set_check_result_does_nothing() -> None:
        """set_check_result on skeleton is a no-op."""
        card = ActionCard(skeleton=True)
        result = _make_result()
        card.set_check_result(result)
        assert not card.status_text()

    @staticmethod
    def test_skeleton_set_executing_does_nothing() -> None:
        """set_executing on skeleton is a no-op."""
        card = ActionCard(skeleton=True)
        card.set_executing()
        assert not card.status_text()


# ---------------------------------------------------------------------------
# ActionCard — populated
# ---------------------------------------------------------------------------


class TestActionCardPopulated:
    """Tests for populated ActionCard."""

    @staticmethod
    def test_populate_shows_package_name() -> None:
        """populate() fills the package label."""
        card = ActionCard()
        action = _make_action(package='ruff')
        card.populate(action)
        assert card._package_label.text() == 'ruff'

    @staticmethod
    def test_populate_shows_type_badge() -> None:
        """populate() sets the type badge."""
        card = ActionCard()
        action = _make_action(kind=PluginKind.TOOL)
        card.populate(action)
        assert card._type_badge.text() == 'Tool'

    @staticmethod
    def test_populate_shows_description() -> None:
        """populate() sets the description label."""
        card = ActionCard()
        action = _make_action(package='ruff', package_description='A fast Python linter')
        card.populate(action)
        assert card._desc_label.text() == 'A fast Python linter'

    @staticmethod
    def test_initial_status_is_checking() -> None:
        """Card starts with 'Checking…' status (via spinner) after populate."""
        card = ActionCard()
        action = _make_action()
        card.populate(action)
        assert card.status_text() == 'Checking\u2026'
        assert card._checking
        assert card._status_label.isHidden()
        assert not card._spinner_canvas.isHidden()

    @staticmethod
    def test_installer_missing_shows_not_installed() -> None:
        """Card shows 'Not installed' when the plugin is missing."""
        card = ActionCard()
        action = _make_action(installer='uv')
        card.populate(action, plugin_installed={'uv': False})
        assert card.status_text() == 'Not installed'

    @staticmethod
    def test_installer_present_shows_checking() -> None:
        """Card shows spinner (Checking) when the plugin is installed."""
        card = ActionCard()
        action = _make_action(installer='pip')
        card.populate(action, plugin_installed={'pip': True})
        assert card.status_text() == 'Checking\u2026'
        assert card._checking

    @staticmethod
    def test_prerelease_checkbox_shown_for_packages() -> None:
        """Pre-release checkbox is visible for package actions."""
        card = ActionCard()
        action = _make_action(package='requests')
        card.populate(action)
        assert not card._prerelease_cb.isHidden()

    @staticmethod
    def test_prerelease_checkbox_locked_by_manifest() -> None:
        """Pre-release checkbox locked if manifest enables it and no user override."""
        card = ActionCard()
        action = _make_action(include_prereleases=True)
        card.populate(action, prerelease_overrides=set())
        assert card._prerelease_cb.isChecked()
        assert not card._prerelease_cb.isEnabled()

    @staticmethod
    def test_prerelease_checkbox_unlocked_if_user_override() -> None:
        """Pre-release checkbox unlocked when user has an override."""
        card = ActionCard()
        action = _make_action(package='requests', include_prereleases=True)
        card.populate(action, prerelease_overrides={'requests'})
        assert card._prerelease_cb.isChecked()
        assert card._prerelease_cb.isEnabled()


# ---------------------------------------------------------------------------
# ActionCard — dry-run check results
# ---------------------------------------------------------------------------


class TestActionCardCheckResult:
    """Tests for set_check_result."""

    @staticmethod
    def test_needed_status() -> None:
        """Non-skipped result shows 'Needed'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(success=True, skipped=False)
        card.set_check_result(result)
        assert card.status_text() == 'Needed'
        assert ACTION_CARD_STATUS_NEEDED in card._status_label.styleSheet()

    @staticmethod
    def test_already_installed_status() -> None:
        """Skipped ALREADY_INSTALLED shows '\u2713 Already installed'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
            installed_version='3.5.2',
        )
        card.set_check_result(result)
        assert card.status_text() == '\u2713 Already installed'
        assert ACTION_CARD_STATUS_SATISFIED in card._status_label.styleSheet()

    @staticmethod
    def test_update_available_status() -> None:
        """Skipped UPDATE_AVAILABLE shows 'Update available'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.UPDATE_AVAILABLE,
            installed_version='1.0.0',
            available_version='2.0.0',
        )
        card.set_check_result(result)
        assert card.status_text() == 'Update available'
        assert card.is_update_available()
        assert ACTION_CARD_STATUS_UPDATE in card._status_label.styleSheet()

    @staticmethod
    def test_version_transition_shown() -> None:
        """Version label shows 'old → new' for update-available actions."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.UPDATE_AVAILABLE,
            installed_version='1.0.0',
            available_version='2.0.0',
        )
        card.set_check_result(result)
        assert '1.0.0' in card._version_label.text()
        assert '2.0.0' in card._version_label.text()
        assert '\u2192' in card._version_label.text()

    @staticmethod
    def test_installed_version_shown() -> None:
        """Version label shows installed version for satisfied actions."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
            installed_version='3.5.2',
        )
        card.set_check_result(result)
        assert card._version_label.text() == '3.5.2'

    @staticmethod
    def test_available_version_only_shown() -> None:
        """Version label shows '→ target' when only available_version is set."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            success=True,
            skipped=False,
            available_version='1.2.0',
        )
        card.set_check_result(result)
        assert '\u2192 1.2.0' in card._version_label.text()
        assert 'grey' in card._version_label.styleSheet()

    @staticmethod
    def test_finalize_checking_resolves_to_needed() -> None:
        """finalize_checking stops spinner and changes to 'Needed'."""
        card = ActionCard()
        card.populate(_make_action())
        assert card.status_text() == 'Checking\u2026'
        assert card._checking
        card.finalize_checking()
        assert card.status_text() == 'Needed'
        assert not card._checking
        assert not card._status_label.isHidden()

    @staticmethod
    def test_finalize_checking_leaves_not_installed() -> None:
        """finalize_checking does not change 'Not installed'."""
        card = ActionCard()
        card.populate(_make_action(installer='uv'), plugin_installed={'uv': False})
        assert card.status_text() == 'Not installed'
        card.finalize_checking()
        assert card.status_text() == 'Not installed'


# ---------------------------------------------------------------------------
# ActionCard — dry-run check failure (success=False)
# ---------------------------------------------------------------------------


class TestActionCardCheckFailure:
    """Tests for set_check_result when the dry-run returns a failure."""

    @staticmethod
    def test_failed_check_shows_failed_status() -> None:
        """A check result with success=False shows 'Failed'."""
        card = ActionCard()
        card.populate(_make_action(kind=PluginKind.SCM, package='periapsis', installer='git'))
        result = _make_result(
            success=False,
            skipped=False,
            message="No SCM plugin was found for ecosystem 'git'.",
        )
        card.set_check_result(result)
        assert card.status_text() == 'Failed'
        assert ACTION_CARD_STATUS_FAILED in card._status_label.styleSheet()

    @staticmethod
    def test_failed_check_shows_error_tooltip() -> None:
        """A failed check result surfaces the error message as a tooltip."""
        card = ActionCard()
        action = _make_action(kind=PluginKind.SCM, package='repo', installer=None)
        card.populate(action)
        msg = "SCM environment 'None' is not available"
        result = _make_result(success=False, skipped=False, message=msg)
        card.set_check_result(result)
        assert card._status_label.toolTip() == msg

    @staticmethod
    def test_failed_check_stops_spinner() -> None:
        """A failed check result stops the inline spinner."""
        card = ActionCard()
        card.populate(_make_action())
        assert card._checking
        result = _make_result(success=False, skipped=False, message='error')
        card.set_check_result(result)
        assert not card._checking
        assert not card._spinner_timer.isActive()

    @staticmethod
    def test_failed_check_not_update_available() -> None:
        """A failed check is not considered 'Update available'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(success=False, skipped=False, message='backend missing')
        card.set_check_result(result)
        assert not card.is_update_available()

    @staticmethod
    def test_success_true_still_needed() -> None:
        """A non-skipped, successful result still shows 'Needed'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(success=True, skipped=False)
        card.set_check_result(result)
        assert card.status_text() == 'Needed'
        assert ACTION_CARD_STATUS_NEEDED in card._status_label.styleSheet()


# ---------------------------------------------------------------------------
# ActionCard — execution (inline log)
# ---------------------------------------------------------------------------


class TestActionCardExecution:
    """Tests for execution-related methods."""

    @staticmethod
    def test_set_executing_shows_running() -> None:
        """set_executing changes status to 'Running…'."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        assert card.status_text() == 'Running\u2026'
        assert ACTION_CARD_STATUS_RUNNING in card._status_label.styleSheet()

    @staticmethod
    def test_set_executing_changes_border_style() -> None:
        """set_executing applies the executing card style."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        assert ACTION_CARD_EXECUTING_STYLE in card.styleSheet()

    @staticmethod
    def test_set_result_success() -> None:
        """Successful result shows 'Done' status."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        result = _make_result(success=True, message='Installed ruff-0.8.0')
        card.set_result(result)
        assert card.status_text() == 'Done'
        assert ACTION_CARD_STATUS_DONE in card._status_label.styleSheet()
        assert ACTION_CARD_STYLE in card.styleSheet()

    @staticmethod
    def test_set_result_failure() -> None:
        """Failed result shows 'Failed' with error in log."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        result = _make_result(success=False, message='Network timeout')
        card.set_result(result)
        assert card.status_text() == 'Failed'
        assert ACTION_CARD_STATUS_FAILED in card._status_label.styleSheet()

    @staticmethod
    def test_set_result_skipped() -> None:
        """Skipped result shows skip reason."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        result = _make_result(
            success=True,
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
        )
        card.set_result(result)
        assert card.status_text() == 'Already installed'
        assert ACTION_CARD_STATUS_SKIPPED in card._status_label.styleSheet()

    @staticmethod
    def test_set_result_updates_version_on_upgrade() -> None:
        """Successful upgrade updates version label to new version."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        result = _make_result(
            success=True,
            installed_version='1.0.0',
            available_version='2.0.0',
        )
        card.set_result(result)
        assert card._version_label.text() == '2.0.0'


# ---------------------------------------------------------------------------
# ActionCardList
# ---------------------------------------------------------------------------


class TestActionCardList:
    """Tests for ActionCardList container."""

    @staticmethod
    def test_show_skeletons() -> None:
        """show_skeletons creates placeholder cards."""
        skeleton_count = 5
        card_list = ActionCardList()
        card_list.show_skeletons(skeleton_count)
        assert card_list.card_count() == skeleton_count
        for i in range(skeleton_count):
            c = card_list.card_at(i)
            assert c is not None
            assert c._is_skeleton

    @staticmethod
    def test_populate_replaces_skeletons() -> None:
        """Populate clears skeletons and creates real cards."""
        card_list = ActionCardList()
        card_list.show_skeletons(3)

        action_count = 2
        actions = [_make_action(package=f'pkg-{i}') for i in range(action_count)]
        card_list.populate(actions)
        assert card_list.card_count() == action_count
        for i in range(action_count):
            c = card_list.card_at(i)
            assert c is not None
            assert not c._is_skeleton

    @staticmethod
    def test_populate_includes_command_actions() -> None:
        """Populate includes actions with kind=None."""
        card_list = ActionCardList()
        a1 = _make_action(package='pkg1')
        a2 = _make_action(package='pkg2', kind=None)
        actions = [a1, a2]
        card_list.populate(actions)
        assert card_list.card_count() == len(actions)

    @staticmethod
    def test_get_card_by_stable_key() -> None:
        """get_card finds the correct card by stable content key."""
        card_list = ActionCardList()
        a1 = _make_action(package='first')
        a2 = _make_action(package='second')
        card_list.populate([a1, a2])

        c1 = card_list.get_card(a1)
        c2 = card_list.get_card(a2)
        assert c1 is not None
        assert c2 is not None
        assert c1 is not c2
        assert c1._package_label.text() == 'first'
        assert c2._package_label.text() == 'second'

    @staticmethod
    def test_get_card_returns_none_for_unknown() -> None:
        """get_card returns None for an unknown action."""
        card_list = ActionCardList()
        card_list.populate([_make_action()])
        unknown = _make_action(package='unknown')
        assert card_list.get_card(unknown) is None

    @staticmethod
    def test_clear_removes_all() -> None:
        """Clear removes all cards."""
        actions = [_make_action(package='pkg1'), _make_action(package='pkg2')]
        card_list = ActionCardList()
        card_list.populate(actions)
        assert card_list.card_count() == len(actions)

        card_list.clear()
        assert card_list.card_count() == 0

    @staticmethod
    def test_finalize_all_checking() -> None:
        """finalize_all_checking resolves pending cards to 'Needed'."""
        card_list = ActionCardList()
        a1 = _make_action(package='pkg1')
        a2 = _make_action(package='pkg2')
        card_list.populate([a1, a2])

        # Simulate: a1 gets a check result, a2 stays as 'Checking…'
        c1 = card_list.get_card(a1)
        assert c1 is not None
        c1.set_check_result(
            _make_result(
                skipped=True,
                skip_reason=SkipReason.ALREADY_INSTALLED,
            )
        )

        card_list.finalize_all_checking()

        assert c1.status_text() == '\u2713 Already installed'  # unchanged
        c2 = card_list.get_card(a2)
        assert c2 is not None
        assert c2.status_text() == 'Needed'  # resolved

    @staticmethod
    def test_prerelease_signal_forwarded() -> None:
        """prerelease_toggled from a card is forwarded through the list."""
        card_list = ActionCardList()
        action = _make_action(package='requests')
        card_list.populate([action])

        received: list[tuple[str, bool]] = []
        card_list.prerelease_toggled.connect(lambda name, checked: received.append((name, checked)))

        card = card_list.get_card(action)
        assert card is not None
        card._prerelease_cb.setChecked(True)

        assert len(received) == 1
        assert received[0] == ('requests', True)


# ---------------------------------------------------------------------------
# ActionCard — PROJECT and bare-command status (Bug B fix)
# ---------------------------------------------------------------------------


class TestActionCardKindStatus:
    """Tests for PROJECT and bare-command actions getting correct status."""

    @staticmethod
    def test_bare_command_shows_pending_after_check() -> None:
        """Bare command (kind=None) keeps 'Pending' after dry-run check."""
        card = ActionCard()
        action = _make_action(kind=None, package='post_sync', installer=None, command=('echo', 'done'))
        card.populate(action)
        assert card.status_text() == 'Pending'

        result = _make_result(success=True, skipped=False)
        card.set_check_result(result)
        assert card.status_text() == 'Pending'
        assert ACTION_CARD_STATUS_PENDING in card._status_label.styleSheet()

    @staticmethod
    def test_project_shows_ready_after_check() -> None:
        """PROJECT action shows 'Ready' after dry-run check."""
        card = ActionCard()
        action = _make_action(kind=PluginKind.PROJECT, package='myproject')
        card.populate(action)

        result = _make_result(success=True, skipped=False)
        card.set_check_result(result)
        assert card.status_text() == 'Ready'
        assert ACTION_CARD_STATUS_SATISFIED in card._status_label.styleSheet()

    @staticmethod
    def test_package_still_shows_needed() -> None:
        """A PACKAGE action with success=True still shows 'Needed'."""
        card = ActionCard()
        card.populate(_make_action(kind=PluginKind.PACKAGE))
        result = _make_result(success=True, skipped=False)
        card.set_check_result(result)
        assert card.status_text() == 'Needed'


# ---------------------------------------------------------------------------
# ActionCard — version specifier display (Phase 3)
# ---------------------------------------------------------------------------


class TestActionCardVersionSpecifier:
    """Tests for constraint-aware version column display."""

    @staticmethod
    def test_specifier_available_version_shows_requires() -> None:
        """available_version with a specifier shows 'requires …'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            success=True,
            skipped=False,
            available_version='>=0.8.0',
        )
        card.set_check_result(result)
        assert card._version_label.text() == 'requires >=0.8.0'
        assert 'grey' in card._version_label.styleSheet()

    @staticmethod
    def test_resolved_available_version_shows_arrow() -> None:
        """available_version with a plain version shows '→ X.Y.Z'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            success=True,
            skipped=False,
            available_version='1.2.0',
        )
        card.set_check_result(result)
        assert '\u2192 1.2.0' in card._version_label.text()

    @staticmethod
    def test_satisfied_with_constraint_shows_tooltip() -> None:
        """Satisfied action with constraint shows 'satisfies ...' tooltip."""
        card = ActionCard()
        action = _make_action(constraint='>=0.8.0')
        card.populate(action)
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
            installed_version='0.9.1',
        )
        card.set_check_result(result)
        assert card._version_label.text() == '0.9.1'
        assert 'satisfies >=0.8.0' in card._version_label.toolTip()

    @staticmethod
    def test_satisfied_without_constraint_no_tooltip() -> None:
        """Satisfied action without constraint has no version tooltip."""
        card = ActionCard()
        action = _make_action()
        card.populate(action)
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
            installed_version='0.9.1',
        )
        card.set_check_result(result)
        assert card._version_label.text() == '0.9.1'
        # No constraint tooltip — only message tooltip may have been set
        assert 'satisfies' not in (card._version_label.toolTip() or '')


# ---------------------------------------------------------------------------
# is_version_specifier helper
# ---------------------------------------------------------------------------


class TestIsVersionSpecifier:
    """Tests for the is_version_specifier helper."""

    @staticmethod
    def test_pep440_operators() -> None:
        """PEP 440 operators are detected."""
        assert is_version_specifier('>=0.8.0')
        assert is_version_specifier('==1.0.0')
        assert is_version_specifier('~=2.0')
        assert is_version_specifier('!=1.5.0')
        assert is_version_specifier('>3.0')
        assert is_version_specifier('<4.0')
        assert is_version_specifier('<=2.0')

    @staticmethod
    def test_caret_tilde() -> None:
        """Caret and tilde shorthand are detected."""
        assert is_version_specifier('^1.0')
        assert is_version_specifier('~1.0')

    @staticmethod
    def test_plain_versions_not_specifiers() -> None:
        """Plain version strings are not specifiers."""
        assert not is_version_specifier('1.2.3')
        assert not is_version_specifier('0.8.0')
        assert not is_version_specifier('2024.1')

    @staticmethod
    def test_card_at_out_of_range() -> None:
        """card_at returns None for out-of-range indices."""
        card_list = ActionCardList()
        assert card_list.card_at(0) is None
        assert card_list.card_at(-1) is None


# ---------------------------------------------------------------------------
# ActionCard — CLI command label
# ---------------------------------------------------------------------------


class TestActionCardCommandLabel:
    """Tests for the CLI command label on action cards."""

    @staticmethod
    def test_default_package_command() -> None:
        """Package actions show 'installer install package' by default."""
        card = ActionCard()
        action = _make_action(package='ruff', installer='pip')
        card.populate(action)
        assert card._command_label.text() == 'pip install ruff'
        assert not card._command_row.isHidden()

    @staticmethod
    def test_explicit_cli_command_from_result() -> None:
        """set_check_result with cli_command updates the command label."""
        card = ActionCard()
        action = _make_action(package='ruff', installer='pip')
        card.populate(action)
        assert card._command_label.text() == 'pip install ruff'

        result = _make_result(
            action=action,
            cli_command=('uv', 'tool', 'install', 'ruff'),
        )
        card.set_check_result(result)
        assert card._command_label.text() == 'uv tool install ruff'

    @staticmethod
    def test_command_label_selectable() -> None:
        """Command label text is selectable by mouse."""
        card = ActionCard()
        action = _make_action()
        card.populate(action)
        flags = card._command_label.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.TextSelectableByMouse

    @staticmethod
    def test_set_check_result_updates_command_label() -> None:
        """set_check_result with result cli_command updates the command label."""
        card = ActionCard()
        action = _make_action(package='ruff', installer='pip')
        card.populate(action)
        assert card._command_label.text() == 'pip install ruff'

        result = _make_result(
            action=action,
            cli_command=('uv', 'tool', 'install', 'ruff'),
        )
        card.set_check_result(result)
        assert card._command_label.text() == 'uv tool install ruff'
        assert not card._command_row.isHidden()

    @staticmethod
    def test_copy_button_copies_command(monkeypatch: object) -> None:
        """Clicking the copy button copies the command text to the clipboard."""
        card = ActionCard()
        action = _make_action(
            package='ruff',
            installer='uv',
            command=('uv', 'tool', 'install', 'ruff'),
        )
        card.populate(action)

        clipboard = QApplication.clipboard()
        assert clipboard is not None
        clipboard.clear()
        card._copy_btn.click()
        assert clipboard.text() == 'uv tool install ruff'

    @staticmethod
    def test_copy_button_shows_feedback() -> None:
        """Clicking copy shows a check-mark on the button."""
        card = ActionCard()
        action = _make_action(
            package='ruff',
            installer='uv',
            command=('uv', 'tool', 'install', 'ruff'),
        )
        card.populate(action)

        card._copy_btn.click()
        assert card._copy_btn.text() == '\u2713'


# ---------------------------------------------------------------------------
# ActionCard — per-card spinner
# ---------------------------------------------------------------------------


class TestActionCardSpinner:
    """Tests for the per-card inline checking spinner."""

    @staticmethod
    def test_spinner_active_during_checking() -> None:
        """Spinner timer is active while card is checking."""
        card = ActionCard()
        card.populate(_make_action())
        assert card._checking
        assert card._spinner_timer.isActive()

    @staticmethod
    def test_spinner_stops_on_check_result() -> None:
        """set_check_result stops the spinner."""
        card = ActionCard()
        card.populate(_make_action())
        assert card._checking
        card.set_check_result(_make_result())
        assert not card._checking
        assert not card._spinner_timer.isActive()
        assert card._spinner_canvas.isHidden()

    @staticmethod
    def test_spinner_stops_on_finalize() -> None:
        """finalize_checking stops the spinner."""
        card = ActionCard()
        card.populate(_make_action())
        assert card._checking
        card.finalize_checking()
        assert not card._checking
        assert not card._spinner_timer.isActive()

    @staticmethod
    def test_spinner_stops_on_executing() -> None:
        """set_executing stops the spinner if still checking."""
        card = ActionCard()
        card.populate(_make_action())
        assert card._checking
        card.set_executing()
        assert not card._checking
        assert not card._spinner_timer.isActive()

    @staticmethod
    def test_no_spinner_for_unavailable() -> None:
        """Unavailable (plugin missing) actions don't spin."""
        card = ActionCard()
        card.populate(_make_action(installer='uv'), plugin_installed={'uv': False})
        assert not card._checking
        assert not card._spinner_timer.isActive()


# ---------------------------------------------------------------------------
# action_sort_key — ordering
# ---------------------------------------------------------------------------


class TestActionSortKey:
    """Tests for the action_sort_key function."""

    @staticmethod
    def test_runtime_before_package() -> None:
        """Runtime actions sort before packages."""
        runtime = _make_action(kind=PluginKind.RUNTIME, package='python')
        package = _make_action(kind=PluginKind.PACKAGE, package='numpy')
        assert action_sort_key(runtime) < action_sort_key(package)

    @staticmethod
    def test_tool_before_scm() -> None:
        """Tool actions sort before SCM (matches execution phase order)."""
        tool = _make_action(kind=PluginKind.TOOL, package='ruff')
        scm = _make_action(kind=PluginKind.SCM, package='git')
        assert action_sort_key(tool) < action_sort_key(scm)

    @staticmethod
    def test_package_before_tool() -> None:
        """Package actions sort before tools (matches execution phase order)."""
        package = _make_action(kind=PluginKind.PACKAGE, package='numpy')
        tool = _make_action(kind=PluginKind.TOOL, package='ruff')
        assert action_sort_key(package) < action_sort_key(tool)

    @staticmethod
    def test_same_kind_returns_equal_key() -> None:
        """Same-kind actions get equal sort keys so stable sort preserves order."""
        alpha = _make_action(package='alpha')
        beta = _make_action(package='beta')
        assert action_sort_key(alpha) == action_sort_key(beta)


# ---------------------------------------------------------------------------
# ActionCardList — ordering & scroll
# ---------------------------------------------------------------------------


class TestActionCardListOrdering:
    """Tests for card ordering in ActionCardList."""

    @staticmethod
    def test_cards_grouped_by_kind_preserving_order() -> None:
        """Cards are grouped by execution phase, preserving porringer order within."""
        card_list = ActionCardList()
        a_pkg_b = _make_action(kind=PluginKind.PACKAGE, package='beta')
        a_tool = _make_action(kind=PluginKind.TOOL, package='ruff')
        a_pkg_a = _make_action(kind=PluginKind.PACKAGE, package='alpha')
        a_runtime = _make_action(kind=PluginKind.RUNTIME, package='python')

        # Populate in porringer's execution order
        card_list.populate([a_pkg_b, a_tool, a_pkg_a, a_runtime])

        # Grouped by phase: RUNTIME(0) → PACKAGE(1) → TOOL(2)
        # Within PACKAGE group, original (porringer) order is preserved:
        # beta came before alpha in the input list.
        expected = ['python', 'beta', 'alpha', 'ruff']
        assert card_list.card_count() == len(expected)
        for i, name in enumerate(expected):
            card = card_list.card_at(i)
            assert card is not None
            assert card._package_label.text() == name

    @staticmethod
    def test_bare_commands_included() -> None:
        """Actions with kind=None are included in the card list."""
        card_list = ActionCardList()
        pkg = _make_action(kind=PluginKind.PACKAGE, package='requests')
        cmd = _make_action(kind=None, package='run-something')
        actions = [pkg, cmd]
        card_list.populate(actions)
        assert card_list.card_count() == len(actions)

    @staticmethod
    def test_bare_commands_sort_last() -> None:
        """Bare-command actions sort after all PluginKind phases."""
        card_list = ActionCardList()
        cmd = _make_action(kind=None, package='post-cmd')
        a_pkg = _make_action(kind=PluginKind.PACKAGE, package='requests')
        a_scm = _make_action(kind=PluginKind.SCM, package='my-repo')
        actions = [cmd, a_pkg, a_scm]
        card_list.populate(actions)

        assert card_list.card_count() == len(actions)
        # Package(1) → SCM(4) → None(last)
        card_0 = card_list.card_at(0)
        card_1 = card_list.card_at(1)
        card_2 = card_list.card_at(2)
        assert card_0 is not None
        assert card_0._package_label.text() == 'requests'
        assert card_1 is not None
        assert card_1._package_label.text() == 'my-repo'
        assert card_2 is not None
        assert card_2._package_label.text() == 'post-cmd'

    @staticmethod
    def test_bare_command_shows_pending_status() -> None:
        """Bare-command card shows 'Pending' status with the pending style."""
        card = ActionCard()
        card.populate(_make_action(kind=None, package='echo-hello'))
        assert card.status_text() == 'Pending'
        assert ACTION_CARD_STATUS_PENDING in card._status_label.styleSheet()


# ---------------------------------------------------------------------------
# ActionCard — ALREADY_LATEST skip reason
# ---------------------------------------------------------------------------


class TestActionCardAlreadyLatest:
    """Tests for the ALREADY_LATEST skip reason from porringer."""

    @staticmethod
    def test_already_latest_shows_satisfied_style() -> None:
        """ALREADY_LATEST check result uses the satisfied style."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_check_result(
            _make_result(
                skipped=True,
                skip_reason=SkipReason.ALREADY_LATEST,
            )
        )
        assert card.status_text() == '\u2713 Already latest'
        assert ACTION_CARD_STATUS_SATISFIED in card._status_label.styleSheet()

    @staticmethod
    def test_already_latest_shows_version() -> None:
        """ALREADY_LATEST preserves the installed version label."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_check_result(
            _make_result(
                skipped=True,
                skip_reason=SkipReason.ALREADY_LATEST,
                installed_version='1.2.0',
            )
        )
        assert card._version_label.text() == '1.2.0'

    @staticmethod
    def test_already_installed_vs_already_latest() -> None:
        """ALREADY_INSTALLED and ALREADY_LATEST both use satisfied style."""
        card_installed = ActionCard()
        card_installed.populate(_make_action(package='a'))
        card_installed.set_check_result(
            _make_result(
                skipped=True,
                skip_reason=SkipReason.ALREADY_INSTALLED,
            )
        )

        card_latest = ActionCard()
        card_latest.populate(_make_action(package='b'))
        card_latest.set_check_result(
            _make_result(
                skipped=True,
                skip_reason=SkipReason.ALREADY_LATEST,
            )
        )

        assert card_installed.status_text() == '\u2713 Already installed'
        assert card_latest.status_text() == '\u2713 Already latest'
        # Both use the satisfied stylesheet
        assert ACTION_CARD_STATUS_SATISFIED in card_installed._status_label.styleSheet()
        assert ACTION_CARD_STATUS_SATISFIED in card_latest._status_label.styleSheet()
