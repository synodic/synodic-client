"""Tests for the ActionCard and ActionCardList widgets."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from porringer.schema import (
    SetupAction,
    SetupActionResult,
    SkipReason,
)
from porringer.schema.plugin import PluginKind
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.action_card import (
    ActionCard,
    ActionCardList,
    action_key,
    action_sort_key,
)
from synodic_client.application.theme import (
    ACTION_CARD_EXECUTING_STYLE,
    ACTION_CARD_SKELETON_STYLE,
    ACTION_CARD_STATUS_DONE,
    ACTION_CARD_STATUS_FAILED,
    ACTION_CARD_STATUS_NEEDED,
    ACTION_CARD_STATUS_RUNNING,
    ACTION_CARD_STATUS_SATISFIED,
    ACTION_CARD_STATUS_SKIPPED,
    ACTION_CARD_STATUS_UPDATE,
    ACTION_CARD_STYLE,
    LOG_COLOR_STDERR,
    LOG_COLOR_STDOUT,
    LOG_COLOR_SUCCESS,
)

_app = QApplication.instance() or QApplication(sys.argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(
    *,
    kind: PluginKind | None = PluginKind.PACKAGE,
    description: str = 'Install requests',
    installer: str = 'pip',
    package: str = 'requests',
    **overrides: object,
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
    pkg_mock.configure_mock(**{'__str__': MagicMock(return_value=package)})
    action.package = pkg_mock
    action.package_description = overrides.get('package_description', description)
    action.command = overrides.get('command')
    action.cli_command = overrides.get('cli_command')
    action.include_prereleases = overrides.get('include_prereleases', False)
    action.plugin_target = overrides.get('plugin_target')
    return action


def _make_result(
    *,
    success: bool = True,
    skipped: bool = False,
    skip_reason: SkipReason | None = None,
    message: str | None = None,
    **overrides: object,
) -> SetupActionResult:
    """Create a SetupActionResult.

    Extra keyword arguments (``action``, ``installed_version``,
    ``available_version``) are forwarded to the constructor.
    """
    return SetupActionResult(
        action=overrides.get('action') or _make_action(),  # type: ignore[arg-type]
        success=success,
        skipped=skipped,
        skip_reason=skip_reason,
        message=message,
        installed_version=overrides.get('installed_version'),  # type: ignore[arg-type]
        available_version=overrides.get('available_version'),  # type: ignore[arg-type]
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
        """Skipped ALREADY_INSTALLED shows 'Already installed'."""
        card = ActionCard()
        card.populate(_make_action())
        result = _make_result(
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
            installed_version='3.5.2',
        )
        card.set_check_result(result)
        assert card.status_text() == 'Already installed'
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
# ActionCard — execution (inline log)
# ---------------------------------------------------------------------------


class TestActionCardExecution:
    """Tests for execution-related methods."""

    @staticmethod
    def test_set_executing_shows_running() -> None:
        """set_executing changes status to 'Running…' and expands log."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        assert card.status_text() == 'Running\u2026'
        assert ACTION_CARD_STATUS_RUNNING in card._status_label.styleSheet()
        assert not card._log_output.isHidden()
        assert card._log_expanded

    @staticmethod
    def test_set_executing_changes_border_style() -> None:
        """set_executing applies the executing card style."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        assert ACTION_CARD_EXECUTING_STYLE in card.styleSheet()

    @staticmethod
    def test_append_stdout() -> None:
        """append_output with stdout stream adds coloured text."""
        card = ActionCard()
        card.populate(_make_action())
        card.append_output('Processing package', 'stdout')
        html = card._log_output.toHtml()
        assert LOG_COLOR_STDOUT in html
        assert 'Processing package' in html

    @staticmethod
    def test_append_stderr() -> None:
        """append_output with stderr stream uses amber colour."""
        card = ActionCard()
        card.populate(_make_action())
        card.append_output('warning: something', 'stderr')
        html = card._log_output.toHtml()
        assert LOG_COLOR_STDERR in html
        assert 'warning: something' in html

    @staticmethod
    def test_append_html_escaping() -> None:
        """Special HTML characters are escaped in output."""
        card = ActionCard()
        card.populate(_make_action())
        card.append_output('<script>alert("xss")</script>', 'stdout')
        html = card._log_output.toHtml()
        assert '&lt;script&gt;' in html

    @staticmethod
    def test_set_result_success() -> None:
        """Successful result shows 'Done' with success message in log."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        result = _make_result(success=True, message='Installed ruff-0.8.0')
        card.set_result(result)
        assert card.status_text() == 'Done'
        assert ACTION_CARD_STATUS_DONE in card._status_label.styleSheet()
        assert ACTION_CARD_STYLE in card.styleSheet()
        html = card._log_output.toHtml()
        assert LOG_COLOR_SUCCESS in html
        assert 'Installed ruff-0.8.0' in html

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

    @staticmethod
    def test_toggle_log_visibility() -> None:
        """Clicking the card toggles log visibility."""
        card = ActionCard()
        card.populate(_make_action())
        card.set_executing()
        assert card._log_expanded
        assert not card._log_output.isHidden()

        card._toggle_log()
        assert not card._log_expanded
        assert card._log_output.isHidden()

        card._toggle_log()
        assert card._log_expanded
        assert not card._log_output.isHidden()


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
    def test_populate_skips_command_actions() -> None:
        """Populate skips actions with kind=None."""
        card_list = ActionCardList()
        a1 = _make_action(package='pkg1')
        a2 = _make_action(package='pkg2')
        a2.kind = None  # bare command
        card_list.populate([a1, a2])
        assert card_list.card_count() == 1

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
    def test_get_card_cross_instance() -> None:
        """get_card works with a different object that has the same content."""
        card_list = ActionCardList()
        original = _make_action(package='numpy', installer='pip')
        card_list.populate([original])

        # Create a separate mock with the same content fields
        duplicate = _make_action(package='numpy', installer='pip')
        assert original is not duplicate

        card = card_list.get_card(duplicate)
        assert card is not None
        assert card._package_label.text() == 'numpy'

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

        assert c1.status_text() == 'Already installed'  # unchanged
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

    @staticmethod
    def test_card_at_out_of_range() -> None:
        """card_at returns None for out-of-range indices."""
        card_list = ActionCardList()
        assert card_list.card_at(0) is None
        assert card_list.card_at(-1) is None


# ---------------------------------------------------------------------------
# action_key — stable identity
# ---------------------------------------------------------------------------


class TestActionKey:
    """Tests for the action_key function."""

    @staticmethod
    def test_same_content_same_key() -> None:
        """Two actions with identical content produce the same key."""
        a = _make_action(package='numpy', installer='pip')
        b = _make_action(package='numpy', installer='pip')
        assert a is not b
        assert action_key(a) == action_key(b)

    @staticmethod
    def test_different_package_different_key() -> None:
        """Actions with different packages produce different keys."""
        a = _make_action(package='numpy')
        b = _make_action(package='scipy')
        assert action_key(a) != action_key(b)

    @staticmethod
    def test_different_installer_different_key() -> None:
        """Actions with different installers produce different keys."""
        a = _make_action(package='numpy', installer='pip')
        b = _make_action(package='numpy', installer='uv')
        assert action_key(a) != action_key(b)

    @staticmethod
    def test_different_kind_different_key() -> None:
        """Actions with different kinds produce different keys."""
        a = _make_action(package='ruff', kind=PluginKind.PACKAGE)
        b = _make_action(package='ruff', kind=PluginKind.TOOL)
        assert action_key(a) != action_key(b)

    @staticmethod
    def test_command_action_key() -> None:
        """Command actions include the command in the key."""
        a = _make_action(command=['echo', 'hello'])
        b = _make_action(command=['echo', 'hello'])
        c = _make_action(command=['echo', 'world'])
        assert action_key(a) == action_key(b)
        assert action_key(a) != action_key(c)


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
    def test_explicit_cli_command() -> None:
        """Actions with cli_command show that instead of the default."""
        card = ActionCard()
        action = _make_action(cli_command=['uv', 'tool', 'install', 'ruff'])
        card.populate(action)
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
    def test_update_command_updates_text() -> None:
        """update_command replaces the command label text."""
        card = ActionCard()
        action = _make_action(package='ruff', installer='pip')
        card.populate(action)
        assert card._command_label.text() == 'pip install ruff'

        resolved = _make_action(cli_command=['uv', 'tool', 'install', 'ruff'])
        card.update_command(resolved)
        assert card._command_label.text() == 'uv tool install ruff'
        assert not card._command_row.isHidden()

    @staticmethod
    def test_update_command_hides_label_when_empty() -> None:
        """update_command hides the row when the resolved action has no command."""
        card = ActionCard()
        action = _make_action(package='ruff', installer='pip')
        card.populate(action)
        assert not card._command_row.isHidden()

        empty_action = _make_action(kind=PluginKind.RUNTIME)
        empty_action.cli_command = None
        empty_action.command = None
        empty_action.package = None
        card.update_command(empty_action)
        assert card._command_row.isHidden()

    @staticmethod
    def test_update_command_noop_on_skeleton() -> None:
        """update_command does nothing when card is a skeleton."""
        card = ActionCard(skeleton=True)
        action = _make_action(cli_command=['uv', 'tool', 'install', 'ruff'])
        # Should not raise — skeleton simply returns early
        card.update_command(action)

    @staticmethod
    def test_copy_button_copies_command(monkeypatch: object) -> None:
        """Clicking the copy button copies the command text to the clipboard."""
        card = ActionCard()
        action = _make_action(cli_command=['uv', 'tool', 'install', 'ruff'])
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
        action = _make_action(cli_command=['uv', 'tool', 'install', 'ruff'])
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
    def test_alphabetical_within_kind() -> None:
        """Same-kind actions are sorted alphabetically by package name."""
        alpha = _make_action(package='alpha')
        beta = _make_action(package='beta')
        assert action_sort_key(alpha) < action_sort_key(beta)

    @staticmethod
    def test_case_insensitive() -> None:
        """Package name comparison is case-insensitive."""
        upper = _make_action(package='Alpha')
        lower = _make_action(package='alpha')
        assert action_sort_key(upper) == action_sort_key(lower)


# ---------------------------------------------------------------------------
# ActionCardList — ordering & scroll
# ---------------------------------------------------------------------------


class TestActionCardListOrdering:
    """Tests for card ordering in ActionCardList."""

    @staticmethod
    def test_cards_sorted_by_kind_then_name() -> None:
        """Cards are sorted by kind priority, then alphabetically."""
        card_list = ActionCardList()
        a_pkg_b = _make_action(kind=PluginKind.PACKAGE, package='beta')
        a_tool = _make_action(kind=PluginKind.TOOL, package='ruff')
        a_pkg_a = _make_action(kind=PluginKind.PACKAGE, package='alpha')
        a_runtime = _make_action(kind=PluginKind.RUNTIME, package='python')

        # Populate in unsorted order
        card_list.populate([a_pkg_b, a_tool, a_pkg_a, a_runtime])

        # Execution-phase order: RUNTIME(0) → PACKAGE(1) → TOOL(2)
        expected = ['python', 'alpha', 'beta', 'ruff']
        assert card_list.card_count() == len(expected)
        for i, name in enumerate(expected):
            card = card_list.card_at(i)
            assert card is not None
            assert card._package_label.text() == name

    @staticmethod
    def test_bare_commands_excluded() -> None:
        """Actions with kind=None are excluded from the card list."""
        card_list = ActionCardList()
        pkg = _make_action(kind=PluginKind.PACKAGE, package='requests')
        cmd = _make_action(kind=None, package='run-something')
        card_list.populate([pkg, cmd])
        assert card_list.card_count() == 1

    @staticmethod
    def test_scroll_to_card_bottom_exists() -> None:
        """scroll_to_card_bottom method exists and is callable."""
        card_list = ActionCardList()
        assert callable(card_list.scroll_to_card_bottom)


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
        assert card.status_text() == 'Already latest'
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

        assert card_installed.status_text() == 'Already installed'
        assert card_latest.status_text() == 'Already latest'
        # Both use the satisfied stylesheet
        assert ACTION_CARD_STATUS_SATISFIED in card_installed._status_label.styleSheet()
        assert ACTION_CARD_STATUS_SATISFIED in card_latest._status_label.styleSheet()
