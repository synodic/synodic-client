"""Tests for the install preview window and URI-based install flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from porringer.schema import (
    CancellationToken,
    DownloadResult,
    PluginKind,
    ProgressEvent,
    ProgressEventKind,
    SetupActionResult,
    SetupResults,
    SkipReason,
)

from synodic_client.application.screen import (
    ACTION_KIND_LABELS,
    SKIP_REASON_LABELS,
    skip_reason_label,
)
from synodic_client.application.screen.install import (
    InstallWorker,
    PreviewWorker,
    format_cli_command,
    resolve_local_path,
)
from synodic_client.application.uri import parse_uri


class TestParseUriInstall:
    """Tests for parsing install URIs."""

    @staticmethod
    def test_install_action_parsed() -> None:
        """Verify the action is 'install' for an install URI."""
        result = parse_uri('synodic://install?manifest=https://example.com/porringer.json')
        assert result['action'] == 'install'

    @staticmethod
    def test_manifest_key_present() -> None:
        """Verify the manifest query parameter is extracted."""
        result = parse_uri('synodic://install?manifest=https://example.com/porringer.json')
        assert 'manifest' in result
        assert isinstance(result['manifest'], list)
        assert result['manifest'][0] == 'https://example.com/porringer.json'

    @staticmethod
    def test_multiple_manifests() -> None:
        """Verify multiple manifest values are captured."""
        result = parse_uri('synodic://install?manifest=https://a.com/a.json&manifest=https://b.com/b.json')
        manifests = result['manifest']
        assert isinstance(manifests, list)
        assert len(manifests) == 2  # noqa: PLR2004

    @staticmethod
    def test_unknown_action() -> None:
        """Verify unknown actions are still parsed without error."""
        result = parse_uri('synodic://unknown?foo=bar')
        assert result['action'] == 'unknown'


class TestInstallPreviewWindow:
    """Tests for InstallPreviewWindow table population logic."""

    @staticmethod
    def _make_action(
        kind: str = 'PACKAGE',
        description: str = 'Install test',
        installer: str = 'pip',
        package: str = 'requests',
    ) -> MagicMock:
        """Create a mock SetupAction."""
        action = MagicMock()
        action.kind = getattr(PluginKind, kind)
        action.description = description
        action.installer = installer
        action.package = package
        action.command = None
        action.cli_command = None
        return action

    @staticmethod
    def test_action_kind_labels() -> None:
        """Verify action kind label mapping covers all kinds plus None."""
        for plugin_kind in PluginKind:
            assert plugin_kind in ACTION_KIND_LABELS
        assert None in ACTION_KIND_LABELS

    @staticmethod
    def test_skip_reason_labels() -> None:
        """Verify skip reason label mapping covers all reasons."""
        for reason in SkipReason:
            assert reason in SKIP_REASON_LABELS

    @staticmethod
    def test_skip_reason_label_human_readable() -> None:
        """Verify skip reason labels are human-readable, not raw enum names."""
        assert skip_reason_label(SkipReason.ALREADY_INSTALLED) == 'Already installed'
        assert skip_reason_label(None) == 'Skipped'


class TestFormatCliCommand:
    """Tests for format_cli_command helper."""

    @staticmethod
    def _make_action(**overrides: Any) -> MagicMock:
        """Create a mock SetupAction with optional attribute overrides."""
        defaults: dict[str, Any] = {
            'kind': 'PACKAGE',
            'description': 'Install test',
            'installer': 'pip',
            'package': 'requests',
            'cli_command': None,
            'command': None,
        }
        defaults.update(overrides)
        action = MagicMock()
        kind = defaults['kind']
        action.kind = getattr(PluginKind, kind) if isinstance(kind, str) else kind
        action.description = defaults['description']
        action.installer = defaults['installer']
        action.package = defaults['package']
        action.command = defaults['command']
        action.cli_command = defaults['cli_command']
        return action

    def test_prefers_cli_command(self) -> None:
        """Verify cli_command takes precedence over command and fallback."""
        action = self._make_action(cli_command=['uv', 'pip', 'install', 'requests'])
        assert format_cli_command(action) == 'uv pip install requests'

    def test_falls_back_to_command(self) -> None:
        """Verify command is used when cli_command is absent."""
        action = self._make_action(
            kind='TOOL',
            command=['echo', 'hello'],
        )
        assert format_cli_command(action) == 'echo hello'

    def test_synthesises_package_command(self) -> None:
        """Verify package actions synthesise installer + package."""
        action = self._make_action(installer='pip', package='ruff')
        assert format_cli_command(action) == 'pip install ruff'

    def test_synthesises_default_installer(self) -> None:
        """Verify pip is used as default installer for package actions."""
        action = self._make_action(installer=None, package='ruff')
        assert format_cli_command(action) == 'pip install ruff'

    def test_description_fallback(self) -> None:
        """Verify description is returned when nothing else is available."""
        action = self._make_action(
            kind='TOOL',
            description='Custom step',
            package=None,
        )
        assert format_cli_command(action) == 'Custom step'


class TestInstallWorker:
    """Tests for InstallWorker signal emission."""

    @staticmethod
    def test_worker_emits_finished_on_success() -> None:
        """Verify worker emits finished signal with results."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        action = MagicMock()
        manifest = SetupResults(actions=[action])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=manifest)

        result = MagicMock(spec=SetupActionResult)
        completed_event = ProgressEvent(
            kind=ProgressEventKind.ACTION_COMPLETED,
            action=action,
            result=result,
        )

        async def mock_stream(*args, **kwargs):  # noqa: ANN002, ANN003
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        token = CancellationToken()
        worker = InstallWorker(porringer, manifest_path, token)

        received: list[SetupResults] = []
        worker.finished.connect(received.append)
        worker.run()

        assert len(received) == 1
        assert received[0].actions == manifest.actions

    @staticmethod
    def test_worker_emits_error_on_failure() -> None:
        """Verify worker emits error signal on exception."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        async def mock_stream(*args, **kwargs):  # noqa: ANN002, ANN003
            if False:
                yield  # pragma: no cover — establishes async generator protocol
            msg = 'boom'
            raise RuntimeError(msg)

        porringer.sync.execute_stream = mock_stream

        token = CancellationToken()
        worker = InstallWorker(porringer, manifest_path, token)

        errors: list[str] = []
        worker.error.connect(errors.append)
        worker.run()

        assert len(errors) == 1
        assert 'boom' in errors[0]


class TestResolveLocalPath:
    """Tests for _resolve_local_path helper."""

    @staticmethod
    def test_http_url_returns_none() -> None:
        """HTTP URLs should not resolve to a local path."""
        assert resolve_local_path('https://example.com/porringer.json') is None

    @staticmethod
    def test_absolute_path_returns_path(tmp_path: Path) -> None:
        """Absolute OS paths should resolve."""
        path = str(tmp_path / 'porringer.json')
        result = resolve_local_path(path)
        assert result is not None
        assert result == Path(path)

    @staticmethod
    def test_file_uri_returns_path() -> None:
        """file:// URIs should resolve to a local path."""
        result = resolve_local_path('file:///C:/Users/test/porringer.json')
        assert result is not None
        assert 'porringer.json' in str(result)

    @staticmethod
    def test_existing_relative_path(tmp_path: Path) -> None:
        """Relative paths that exist on disk should resolve."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')
        result = resolve_local_path(str(manifest))
        assert result is not None


class TestPreviewWorkerLocal:
    """Tests for PreviewWorker with local manifest files."""

    @staticmethod
    def test_local_manifest_skips_download(tmp_path: Path) -> None:
        """Verify PreviewWorker skips download for local files."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        expected = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=expected)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        results: list[tuple[object, str, str]] = []
        worker.preview_ready.connect(lambda r, p, t: results.append((r, p, t)))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is expected
        # download should NOT have been called
        porringer.sync.download.assert_not_called()

    @staticmethod
    def test_local_manifest_not_found(tmp_path: Path) -> None:
        """Verify PreviewWorker emits error for missing local file."""
        path = str(tmp_path / 'nonexistent' / 'porringer.json')
        porringer = MagicMock()
        worker = PreviewWorker(porringer, path)

        errors: list[str] = []
        worker.error.connect(errors.append)
        worker.run()

        assert len(errors) == 1
        assert 'not found' in errors[0].lower()


class TestPreviewWorker:
    """Tests for PreviewWorker download and preview flow."""

    @staticmethod
    def test_emits_error_on_download_failure() -> None:
        """Verify PreviewWorker emits error when download fails."""
        porringer = MagicMock()
        porringer.sync.download.return_value = DownloadResult(
            success=False,
            path=None,
            verified=False,
            size=0,
            message='Network error',
        )

        worker = PreviewWorker(porringer, 'https://example.com/bad.json')

        errors: list[str] = []
        worker.error.connect(errors.append)
        worker.run()

        assert len(errors) == 1
        assert 'Network error' in errors[0]

    @staticmethod
    def test_emits_preview_ready_on_success() -> None:
        """Verify PreviewWorker emits preview_ready with SetupResults."""
        porringer = MagicMock()
        porringer.sync.download.return_value = DownloadResult(
            success=True,
            path=Path('/tmp/test/porringer.json'),
            verified=True,
            size=100,
            message='OK',
        )
        expected = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=expected)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, 'https://example.com/good.json')

        results: list[tuple[object, str, str]] = []
        worker.preview_ready.connect(lambda r, p, t: results.append((r, p, t)))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is expected


class TestPreviewWorkerSignals:
    """Tests for PreviewWorker signal emission and dry-run status check."""

    @staticmethod
    def test_emits_preview_ready_and_finished(tmp_path: Path) -> None:
        """Verify worker emits preview_ready then finished for a local manifest."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action = MagicMock()
        action.kind = PluginKind.PACKAGE
        preview = SetupResults(actions=[action])

        # Dry-run stream yields manifest loaded then one completed event
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)
        result = SetupActionResult(action=action, success=True, skipped=False, skip_reason=None)
        completed_event = ProgressEvent(kind=ProgressEventKind.ACTION_COMPLETED, action=action, result=result)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        ready_calls: list[tuple[object, str, str]] = []
        checked: list[tuple[int, SetupActionResult]] = []
        finished_count: list[int] = []
        worker.preview_ready.connect(lambda p, m, t: ready_calls.append((p, m, t)))
        worker.action_checked.connect(lambda row, r: checked.append((row, r)))
        worker.finished.connect(lambda: finished_count.append(1))
        worker.run()

        assert len(ready_calls) == 1
        assert ready_calls[0][0] is preview
        assert len(checked) == 1
        assert checked[0] == (0, result)
        assert len(finished_count) == 1

    @staticmethod
    def test_emits_finished_for_empty_actions(tmp_path: Path) -> None:
        """Verify worker emits finished signal even with no actions."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        finished_count: list[int] = []
        worker.finished.connect(lambda: finished_count.append(1))
        worker.run()

        assert len(finished_count) == 1

    @staticmethod
    def test_action_checked_maps_correct_rows(tmp_path: Path) -> None:
        """Verify action_checked emits correct row indices via identity matching."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action_a = MagicMock()
        action_a.kind = PluginKind.RUNTIME
        action_b = MagicMock()
        action_b.kind = PluginKind.PACKAGE
        preview = SetupResults(actions=[action_a, action_b])

        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)
        result_b = SetupActionResult(
            action=action_b, success=True, skipped=True, skip_reason=SkipReason.ALREADY_INSTALLED
        )
        result_a = SetupActionResult(action=action_a, success=True, skipped=False, skip_reason=None)

        # Stream returns in execution order (b before a), not preview order
        event_b = ProgressEvent(kind=ProgressEventKind.ACTION_COMPLETED, action=action_b, result=result_b)
        event_a = ProgressEvent(kind=ProgressEventKind.ACTION_COMPLETED, action=action_a, result=result_a)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield event_b
            yield event_a

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        checked: list[tuple[int, SetupActionResult]] = []
        worker.action_checked.connect(lambda row, r: checked.append((row, r)))
        worker.run()

        assert len(checked) == 2  # noqa: PLR2004
        # action_b is at index 1 in preview, action_a at index 0
        assert checked[0] == (1, result_b)
        assert checked[1] == (0, result_a)

    @staticmethod
    def test_emits_error_when_dry_run_fails(tmp_path: Path) -> None:
        """Verify worker emits error when dry-run raises."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            if False:
                yield  # pragma: no cover — establishes async generator protocol
            msg = 'dry-run boom'
            raise RuntimeError(msg)

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        errors: list[str] = []
        finished_count: list[int] = []
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished_count.append(1))
        worker.run()

        assert len(errors) == 1
        assert 'dry-run boom' in errors[0]
        assert len(finished_count) == 0
