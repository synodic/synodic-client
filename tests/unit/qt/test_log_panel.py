"""Tests for the execution log panel widgets and run_install callback signals."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from porringer.schema import (
    ActionCompletedEvent,
    ActionStartedEvent,
    ManifestLoadedEvent,
    SetupResults,
    SkipReason,
    SubActionProgress,
    SubActionProgressEvent,
)

from synodic_client.application.screen.install_workers import run_install
from synodic_client.application.screen.log_panel import (
    CHEVRON_DOWN,
    CHEVRON_RIGHT,
    ActionLogSection,
    ExecutionLogPanel,
)
from synodic_client.application.screen.schema import InstallCallbacks
from synodic_client.application.theme import (
    LOG_COLOR_ERROR,
    LOG_COLOR_PHASE,
    LOG_COLOR_STDERR,
    LOG_COLOR_STDOUT,
    LOG_COLOR_SUCCESS,
    LOG_STATUS_FAILED,
    LOG_STATUS_RUNNING,
    LOG_STATUS_SKIPPED,
    LOG_STATUS_SUCCESS,
)

from .conftest import make_action, make_result

_EXPECTED_SECTION_COUNT = 2


def _output_html(section: ActionLogSection) -> str:
    """Return the full HTML content of a section's output text edit."""
    return section._output.toHtml()


# ---------------------------------------------------------------------------
# ActionLogSection
# ---------------------------------------------------------------------------


class TestActionLogSection:
    """Tests for ActionLogSection widget."""

    @staticmethod
    def test_initial_status_shows_running() -> None:
        """Section header starts with 'Running…' status."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        assert section._status_label.text() == 'Running…'
        assert LOG_STATUS_RUNNING in section._status_label.styleSheet()

    @staticmethod
    def test_initial_chevron_is_down() -> None:
        """Section starts expanded with the down-pointing chevron."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        assert section._chevron.text() == CHEVRON_DOWN
        assert section._expanded is True
        assert not section._output.isHidden()

    @staticmethod
    def test_toggle_collapses_and_expands() -> None:
        """Toggling collapses the output, toggling again restores it."""
        action = make_action()
        section = ActionLogSection(action, index=1)

        section._toggle()
        assert not section._expanded
        assert section._output.isHidden()
        assert section._chevron.text() == CHEVRON_RIGHT

        section._toggle()
        assert section._expanded
        assert not section._output.isHidden()
        assert section._chevron.text() == CHEVRON_DOWN

    @staticmethod
    def test_append_stdout_output() -> None:
        """Stdout lines are coloured with the stdout colour."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('hello world', 'stdout')

        html = _output_html(section)
        assert LOG_COLOR_STDOUT in html
        assert 'hello world' in html

    @staticmethod
    def test_append_stderr_output() -> None:
        """Stderr lines use the stderr/amber colour."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('warning: something', 'stderr')

        html = _output_html(section)
        assert LOG_COLOR_STDERR in html
        assert 'warning: something' in html

    @staticmethod
    def test_append_output_none_stream_uses_phase_colour() -> None:
        """Lines with stream=None use the phase/muted colour."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('Verifying checksums', None)

        html = _output_html(section)
        assert LOG_COLOR_PHASE in html
        assert 'Verifying checksums' in html

    @staticmethod
    def test_append_phase_uses_phase_colour() -> None:
        """Phase messages (stream=None) use the muted grey colour."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('downloading', None)

        html = _output_html(section)
        assert LOG_COLOR_PHASE in html
        assert 'downloading' in html

    @staticmethod
    def test_html_escaping_in_output() -> None:
        """Special HTML characters are escaped in output lines."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('<script>alert("xss")</script>', 'stdout')

        html = _output_html(section)
        # HTML entities should have been escaped
        assert '&lt;script&gt;' in html
        assert '<script>' not in html.replace('&lt;script&gt;', '')

    @staticmethod
    def test_html_escaping_in_phase() -> None:
        """Special HTML characters are escaped in phase messages."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('Step <1> & "done"', None)

        html = _output_html(section)
        assert '&lt;1&gt;' in html
        assert '&amp;' in html

    @staticmethod
    def test_set_result_success() -> None:
        """Successful result sets 'Done' status with green colour."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        result = make_result(action=action, success=True, message='Installed ruff-0.8.0')

        section.set_result(result)

        assert section._status_label.text() == 'Done'
        assert LOG_STATUS_SUCCESS in section._status_label.styleSheet()
        html = _output_html(section)
        assert LOG_COLOR_SUCCESS in html
        assert 'Installed ruff-0.8.0' in html

    @staticmethod
    def test_set_result_success_default_message() -> None:
        """Successful result without message shows default text."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        result = make_result(action=action, success=True)

        section.set_result(result)

        html = _output_html(section)
        assert 'Completed successfully' in html

    @staticmethod
    def test_set_result_failure() -> None:
        """Failed result sets 'Failed' status with red colour."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        result = make_result(action=action, success=False, message='Network timeout')

        section.set_result(result)

        assert section._status_label.text() == 'Failed'
        assert LOG_STATUS_FAILED in section._status_label.styleSheet()
        html = _output_html(section)
        assert LOG_COLOR_ERROR in html
        assert 'Network timeout' in html

    @staticmethod
    def test_set_result_failure_default_message() -> None:
        """Failed result without message shows 'Unknown error'."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        result = make_result(action=action, success=False)

        section.set_result(result)

        html = _output_html(section)
        assert 'Unknown error' in html

    @staticmethod
    def test_set_result_skipped() -> None:
        """Skipped result sets the skip reason as status text."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        result = make_result(
            action=action,
            success=True,
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
        )

        section.set_result(result)

        assert section._status_label.text() == 'Already installed'
        assert LOG_STATUS_SKIPPED in section._status_label.styleSheet()
        html = _output_html(section)
        assert 'Skipped' in html

    @staticmethod
    def test_multiple_output_lines_accumulate() -> None:
        """Multiple append_output calls accumulate in the text edit."""
        action = make_action()
        section = ActionLogSection(action, index=1)
        section.append_output('line 1', 'stdout')
        section.append_output('line 2', 'stderr')
        section.append_output('line 3', 'stdout')

        plain = section._output.toPlainText()
        assert 'line 1' in plain
        assert 'line 2' in plain
        assert 'line 3' in plain


# ---------------------------------------------------------------------------
# ExecutionLogPanel
# ---------------------------------------------------------------------------


class TestExecutionLogPanel:
    """Tests for ExecutionLogPanel container widget."""

    @staticmethod
    def test_add_section_returns_section() -> None:
        """add_section returns an ActionLogSection widget."""
        panel = ExecutionLogPanel()
        action = make_action()
        section = panel.add_section(action)
        assert isinstance(section, ActionLogSection)

    @staticmethod
    def test_add_section_increments_index() -> None:
        """Section indices increment with each add_section call."""
        panel = ExecutionLogPanel()
        a1 = make_action(description='First', package='first')
        a2 = make_action(description='Second', package='second')

        panel.add_section(a1)
        panel.add_section(a2)

        assert panel._section_count == _EXPECTED_SECTION_COUNT

    @staticmethod
    def test_get_section_returns_correct_section() -> None:
        """get_section finds the section by the same action object."""
        panel = ExecutionLogPanel()
        action = make_action()
        expected = panel.add_section(action)

        found = panel.get_section(action)
        assert found is expected

    @staticmethod
    def test_get_section_returns_none_for_unknown() -> None:
        """get_section returns None for actions not in the panel."""
        panel = ExecutionLogPanel()
        action = make_action()
        assert panel.get_section(action) is None

    @staticmethod
    def test_on_sub_progress_with_output() -> None:
        """on_sub_progress routes output lines to the correct section."""
        panel = ExecutionLogPanel()
        action = make_action()
        panel.add_section(action)

        progress = SubActionProgress(
            action=action,
            phase='installing',
            output='Collecting requests',
            stream='stdout',
        )
        panel.on_sub_progress(action, progress)

        section = panel.get_section(action)
        assert section is not None
        plain = section._output.toPlainText()
        assert 'Collecting requests' in plain

    @staticmethod
    def test_on_sub_progress_with_phase_message() -> None:
        """on_sub_progress routes phase messages when no output is set."""
        panel = ExecutionLogPanel()
        action = make_action()
        panel.add_section(action)

        progress = SubActionProgress(
            action=action,
            phase='verifying',
            message='Verifying checksums…',
        )
        panel.on_sub_progress(action, progress)

        section = panel.get_section(action)
        assert section is not None
        plain = section._output.toPlainText()
        assert 'Verifying checksums' in plain

    @staticmethod
    def test_on_sub_progress_ignores_unknown_action() -> None:
        """on_sub_progress does nothing when the action has no section."""
        panel = ExecutionLogPanel()
        action = make_action()
        progress = SubActionProgress(action=action, phase='installing')

        # Should not raise
        panel.on_sub_progress(action, progress)

    @staticmethod
    def test_on_action_completed_updates_section() -> None:
        """on_action_completed calls set_result on the correct section."""
        panel = ExecutionLogPanel()
        action = make_action()
        panel.add_section(action)

        result = make_result(action=action, success=True, message='Done')
        panel.on_action_completed(action, result)

        section = panel.get_section(action)
        assert section is not None
        assert section._status_label.text() == 'Done'

    @staticmethod
    def test_on_action_completed_ignores_unknown_action() -> None:
        """on_action_completed does nothing for unknown actions."""
        panel = ExecutionLogPanel()
        action = make_action()
        result = make_result(action=action, success=True)

        # Should not raise
        panel.on_action_completed(action, result)

    @staticmethod
    def test_clear_removes_all_sections() -> None:
        """clear() removes all sections and resets the counter."""
        panel = ExecutionLogPanel()
        a1 = make_action(description='First', package='first')
        a2 = make_action(description='Second', package='second')
        panel.add_section(a1)
        panel.add_section(a2)

        panel.clear()

        assert panel._section_count == 0
        assert len(panel._sections) == 0
        assert panel.get_section(a1) is None
        assert panel.get_section(a2) is None

    @staticmethod
    def test_multiple_actions_tracked_independently() -> None:
        """Different actions get independent sections with separate output."""
        panel = ExecutionLogPanel()
        a1 = make_action(description='First', package='first')
        a2 = make_action(description='Second', package='second')
        panel.add_section(a1)
        panel.add_section(a2)

        panel.on_sub_progress(
            a1,
            SubActionProgress(action=a1, phase='installing', output='line for a1', stream='stdout'),
        )
        panel.on_sub_progress(
            a2,
            SubActionProgress(action=a2, phase='installing', output='line for a2', stream='stderr'),
        )

        s1 = panel.get_section(a1)
        s2 = panel.get_section(a2)
        assert s1 is not None
        assert s2 is not None
        assert 'line for a1' in s1._output.toPlainText()
        assert 'line for a2' in s2._output.toPlainText()
        assert 'line for a2' not in s1._output.toPlainText()
        assert 'line for a1' not in s2._output.toPlainText()


# ---------------------------------------------------------------------------
# run_install callback tests for action_started / sub_progress signals
# ---------------------------------------------------------------------------


class TestRunInstallCallbackSignals:
    """Tests for run_install action_started and sub_progress callbacks."""

    @staticmethod
    def test_emits_action_started() -> None:
        """Verify run_install invokes on_action_started when ACTION_STARTED event arrives."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        action = make_action()
        manifest = SetupResults(actions=[action])

        manifest_event = ManifestLoadedEvent(manifest=manifest)
        started_event = ActionStartedEvent(action=action)
        result = make_result(action=action)
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
        )

        async def mock_stream(*args, **kwargs):
            yield manifest_event
            yield started_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        started_actions: list[object] = []

        asyncio.run(
            run_install(
                porringer,
                manifest_path,
                callbacks=InstallCallbacks(on_action_started=started_actions.append),
            ),
        )

        assert len(started_actions) == 1
        assert started_actions[0] is action

    @staticmethod
    def test_emits_sub_progress() -> None:
        """Verify run_install invokes on_sub_progress when SUB_ACTION_PROGRESS event arrives."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        action = make_action()
        manifest = SetupResults(actions=[action])
        sub = SubActionProgress(
            action=action,
            phase='downloading',
            output='Downloading ruff-0.8.0.whl',
            stream='stderr',
        )

        manifest_event = ManifestLoadedEvent(manifest=manifest)
        sub_event = SubActionProgressEvent(
            action=action,
            sub_action=sub,
        )
        result = make_result(action=action)
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
        )

        async def mock_stream(*args, **kwargs):
            yield manifest_event
            yield sub_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        received: list[tuple[object, object]] = []

        asyncio.run(
            run_install(
                porringer,
                manifest_path,
                callbacks=InstallCallbacks(
                    on_sub_progress=lambda a, s: received.append((a, s)),
                ),
            ),
        )

        assert len(received) == 1
        assert received[0][0] is action
        assert received[0][1] is sub

    @staticmethod
    def test_non_sub_progress_events_ignored_by_sub_callback() -> None:
        """Verify non-SubActionProgressEvent events don't trigger sub_progress callback."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        action = make_action()
        manifest = SetupResults(actions=[action])

        manifest_event = ManifestLoadedEvent(manifest=manifest)
        # ActionStartedEvent should not trigger sub_progress callback
        started_event = ActionStartedEvent(action=action)
        result = make_result(action=action)
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
        )

        async def mock_stream(*args, **kwargs):
            yield manifest_event
            yield started_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        received: list[tuple[object, object]] = []

        asyncio.run(
            run_install(
                porringer,
                manifest_path,
                callbacks=InstallCallbacks(
                    on_sub_progress=lambda a, s: received.append((a, s)),
                ),
            ),
        )

        assert len(received) == 0

    @staticmethod
    def test_non_started_events_ignored_by_started_callback() -> None:
        """Verify non-ActionStartedEvent events don't trigger action_started callback."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        action = make_action()
        manifest = SetupResults(actions=[action])

        manifest_event = ManifestLoadedEvent(manifest=manifest)
        result = make_result(action=action)
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
        )

        async def mock_stream(*args, **kwargs):
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        started_actions: list[object] = []

        asyncio.run(
            run_install(
                porringer,
                manifest_path,
                callbacks=InstallCallbacks(on_action_started=started_actions.append),
            ),
        )

        assert len(started_actions) == 0
