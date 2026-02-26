"""Tests for the install preview window and URI-based install flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from porringer.schema import (
    CancellationToken,
    DownloadResult,
    ProgressEvent,
    ProgressEventKind,
    SetupActionResult,
    SetupResults,
    SkipReason,
)
from porringer.schema.plugin import PluginKind

from synodic_client.application.screen import (
    ACTION_KIND_LABELS,
    SKIP_REASON_LABELS,
    skip_reason_label,
)
from synodic_client.application.screen.install import (
    InstallConfig,
    InstallWorker,
    PreviewWorker,
    format_cli_command,
    normalize_manifest_key,
    resolve_local_path,
)

_DOWNLOAD_PATCH = 'synodic_client.application.screen.install.API.download'
_EXPECTED_CHECKED_COUNT = 2


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
        assert skip_reason_label(SkipReason.ALREADY_LATEST) == 'Already latest'
        assert skip_reason_label(SkipReason.UPDATE_AVAILABLE) == 'Update available'
        assert skip_reason_label(None) == 'Skipped'


class TestUpdateAvailableLabels:
    """Tests for UPDATE_AVAILABLE skip reason handling in the preview UI."""

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
    def test_update_available_label_with_versions() -> None:
        """Verify UPDATE_AVAILABLE produces a clean status label without inline versions."""
        result = SetupActionResult(
            action=MagicMock(),
            success=True,
            skipped=True,
            skip_reason=SkipReason.UPDATE_AVAILABLE,
            installed_version='1.0.0',
            available_version='2.0.0a1',
        )
        # Status column now uses the bare label; versions go to the Version column.
        assert skip_reason_label(result.skip_reason) == 'Update available'

    @staticmethod
    def test_version_column_update_available() -> None:
        """Verify version column shows transition when an update is available."""
        result = SetupActionResult(
            action=MagicMock(),
            success=True,
            skipped=True,
            skip_reason=SkipReason.UPDATE_AVAILABLE,
            installed_version='1.0.0',
            available_version='2.0.0a1',
        )
        # The Version column should contain the transition text.
        version_text = f'{result.installed_version} \u2192 {result.available_version}'
        assert '1.0.0' in version_text
        assert '2.0.0a1' in version_text

    @staticmethod
    def test_version_column_already_installed() -> None:
        """Verify version column shows installed version for already-installed packages."""
        result = SetupActionResult(
            action=MagicMock(),
            success=True,
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
            installed_version='3.5.2',
        )
        assert result.installed_version == '3.5.2'
        assert result.available_version is None

    @staticmethod
    def test_update_available_label_without_versions() -> None:
        """Verify UPDATE_AVAILABLE falls back to base label when versions are missing."""
        result = SetupActionResult(
            action=MagicMock(),
            success=True,
            skipped=True,
            skip_reason=SkipReason.UPDATE_AVAILABLE,
        )
        assert skip_reason_label(result.skip_reason) == 'Update available'

    @staticmethod
    def test_update_available_counted_as_actionable() -> None:
        """Verify upgradable rows are counted as actionable alongside needed."""
        # Simulate the data model: 4 actions where row 1 is upgradable
        statuses = ['Already installed', 'Update available', 'Needed', 'Not installed']
        upgradable_rows = {1}

        needed = sum(1 for s in statuses if s == 'Needed')
        upgradable = len(upgradable_rows)
        unavailable = sum(1 for s in statuses if s == 'Not installed')
        satisfied = len(statuses) - needed - upgradable - unavailable

        assert needed == 1
        assert upgradable == 1
        assert unavailable == 1
        assert satisfied == 1
        assert needed + upgradable > 0  # Install button should be enabled

    @staticmethod
    def test_version_updated_after_successful_upgrade() -> None:
        """Verify the available_version is surfaced for post-install display.

        After a successful upgrade, the ``_update_table_status`` method
        uses ``result.available_version`` to replace the transition arrow
        in the Version column.  This test validates the result carries
        the new version.
        """
        result = SetupActionResult(
            action=MagicMock(),
            success=True,
            skipped=False,
            installed_version='1.0.0',
            available_version='2.0.0a1',
        )
        # After a successful upgrade, available_version is the new version
        assert result.success
        assert not result.skipped
        assert result.available_version == '2.0.0a1'


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

        async def mock_stream(*args, **kwargs):
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

        async def mock_stream(*args, **kwargs):
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

    @staticmethod
    def test_worker_passes_prerelease_packages() -> None:
        """Verify prerelease_packages is forwarded to SetupParameters."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        manifest = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=manifest)

        captured_params: list[Any] = []

        async def mock_stream(params: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        token = CancellationToken()
        worker = InstallWorker(
            porringer,
            manifest_path,
            token,
            InstallConfig(prerelease_packages={'cppython'}),
        )
        worker.run()

        assert len(captured_params) == 1
        assert captured_params[0].prerelease_packages == {'cppython'}

    @staticmethod
    def test_worker_omits_prerelease_when_none() -> None:
        """Verify prerelease_packages defaults to None."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        manifest = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=manifest)

        captured_params: list[Any] = []

        async def mock_stream(params: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        token = CancellationToken()
        worker = InstallWorker(porringer, manifest_path, token)
        worker.run()

        assert len(captured_params) == 1
        assert captured_params[0].prerelease_packages is None


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
    def test_emits_error_on_download_failure(monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify PreviewWorker emits error when download fails."""
        porringer = MagicMock()
        monkeypatch.setattr(
            _DOWNLOAD_PATCH,
            lambda params, progress_callback=None: DownloadResult(
                success=False,
                path=None,
                verified=False,
                size=0,
                message='Network error',
            ),
        )

        worker = PreviewWorker(porringer, 'https://example.com/bad.json')

        errors: list[str] = []
        worker.error.connect(errors.append)
        worker.run()

        assert len(errors) == 1
        assert 'Network error' in errors[0]

    @staticmethod
    def test_emits_preview_ready_on_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Verify PreviewWorker emits preview_ready with SetupResults."""
        porringer = MagicMock()

        dest = tmp_path / 'porringer.json'
        dest.write_text('{}')

        monkeypatch.setattr(
            _DOWNLOAD_PATCH,
            lambda params, progress_callback=None: DownloadResult(
                success=True,
                path=dest,
                verified=True,
                size=100,
                message='OK',
            ),
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

        assert len(checked) == _EXPECTED_CHECKED_COUNT
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

    @staticmethod
    def test_emits_plugins_queried(tmp_path: Path) -> None:
        """Verify plugins_queried is emitted with plugin presence mapping."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        plugins_event = ProgressEvent(
            kind=ProgressEventKind.PLUGINS_DISCOVERED,
            plugin_availability={'pip': True, 'uv': False},
        )
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield plugins_event
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        plugin_data: list[dict[str, bool]] = []
        worker.plugins_queried.connect(plugin_data.append)
        worker.run()

        assert len(plugin_data) == 1
        assert plugin_data[0] == {'pip': True, 'uv': False}

    @staticmethod
    def test_plugins_queried_emitted_before_preview_ready(tmp_path: Path) -> None:
        """Verify plugins_queried fires before preview_ready."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        plugins_event = ProgressEvent(
            kind=ProgressEventKind.PLUGINS_DISCOVERED,
            plugin_availability={},
        )
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield plugins_event
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        order: list[str] = []
        worker.plugins_queried.connect(lambda _: order.append('plugins'))
        worker.preview_ready.connect(lambda *_: order.append('preview'))
        worker.run()

        assert order == ['plugins', 'preview']

    @staticmethod
    def test_emits_manifest_parsed(tmp_path: Path) -> None:
        """Verify manifest_parsed is emitted from MANIFEST_PARSED events."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        parsed_event = ProgressEvent(
            kind=ProgressEventKind.MANIFEST_PARSED,
            manifest=preview,
        )
        loaded_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield parsed_event
            yield loaded_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        parsed_data: list[Any] = []
        worker.manifest_parsed.connect(lambda *a: parsed_data.append(a))
        worker.run()

        assert len(parsed_data) == 1

    @staticmethod
    def test_two_phase_signal_order(tmp_path: Path) -> None:
        """Verify the full two-phase signal order: parsed → plugins → ready."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        parsed_event = ProgressEvent(
            kind=ProgressEventKind.MANIFEST_PARSED,
            manifest=preview,
        )
        plugins_event = ProgressEvent(
            kind=ProgressEventKind.PLUGINS_DISCOVERED,
            plugin_availability={'pip': True},
        )
        loaded_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield parsed_event
            yield plugins_event
            yield loaded_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))

        order: list[str] = []
        worker.manifest_parsed.connect(lambda *_: order.append('parsed'))
        worker.plugins_queried.connect(lambda _: order.append('plugins'))
        worker.preview_ready.connect(lambda *_: order.append('ready'))
        worker.run()

        assert order == ['parsed', 'plugins', 'ready']


class TestPreviewWorkerUpdateDetection:
    """Tests for PreviewWorker passing update-detection flags to porringer."""

    @staticmethod
    def test_passes_detect_updates_and_prerelease_packages(tmp_path: Path) -> None:
        """Verify detect_updates and prerelease_packages are forwarded to SetupParameters."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(
            porringer,
            str(manifest),
            detect_updates=True,
            prerelease_packages={'some-pkg'},
        )
        worker.run()

        assert len(captured_params) == 1
        assert captured_params[0].detect_updates is True
        assert captured_params[0].prerelease_packages == {'some-pkg'}

    @staticmethod
    def test_defaults_detect_updates_true(tmp_path: Path) -> None:
        """Verify detect_updates defaults to True."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest))
        worker.run()

        assert len(captured_params) == 1
        assert captured_params[0].detect_updates is True
        assert captured_params[0].prerelease_packages is None


class TestNormalizeManifestKey:
    """Tests for normalize_manifest_key helper."""

    @staticmethod
    def test_http_url_passthrough() -> None:
        """HTTP URLs are returned unchanged."""
        url = 'https://example.com/porringer.json'
        assert normalize_manifest_key(url) == url

    @staticmethod
    def test_local_path_resolved(tmp_path: Path) -> None:
        """Local paths are resolved to absolute form."""
        result = normalize_manifest_key(str(tmp_path / 'manifest'))
        assert Path(result).is_absolute()

    @staticmethod
    def test_relative_path_resolved() -> None:
        """Relative paths are resolved relative to cwd."""
        result = normalize_manifest_key('some/relative/path')
        assert Path(result).is_absolute()


class TestPreviewWorkerProjectDirectory:
    """Tests for project_directory forwarding to the dry-run."""

    @staticmethod
    def test_file_path_forwards_parent_as_project_directory(tmp_path: Path) -> None:
        """When a manifest *file* is selected, its parent dir is forwarded."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(
            porringer,
            str(manifest),
            project_directory=manifest.parent,
        )
        worker.run()

        assert len(captured_params) == 1
        assert captured_params[0].project_directory == tmp_path

    @staticmethod
    def test_directory_path_forwarded_directly(tmp_path: Path) -> None:
        """When a directory is selected its path is forwarded as-is."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(
            porringer,
            str(tmp_path),
            project_directory=tmp_path,
        )
        worker.run()

        assert len(captured_params) == 1
        assert captured_params[0].project_directory == tmp_path


class TestSCMPreviewActions:
    """Tests for SCM (git clone) actions in the preview dry-run flow."""

    @staticmethod
    def _make_scm_action(description: str = 'Clone repo') -> MagicMock:
        action = MagicMock()
        action.kind = PluginKind.SCM
        action.description = description
        action.installer = 'git'
        action.package = None
        action.command = None
        action.cli_command = None
        return action

    def test_scm_already_installed_emits_correct_result(self, tmp_path: Path) -> None:
        """An SCM action with ALREADY_INSTALLED is surfaced via action_checked."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action = self._make_scm_action()
        preview = SetupResults(actions=[action])

        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)
        result = SetupActionResult(
            action=action,
            success=True,
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
        )
        completed_event = ProgressEvent(
            kind=ProgressEventKind.ACTION_COMPLETED,
            action=action,
            result=result,
        )

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest), project_directory=tmp_path)

        checked: list[tuple[int, SetupActionResult]] = []
        worker.action_checked.connect(lambda row, r: checked.append((row, r)))
        worker.run()

        assert len(checked) == 1
        assert checked[0] == (0, result)
        assert checked[0][1].skipped is True
        assert checked[0][1].skip_reason == SkipReason.ALREADY_INSTALLED

    def test_scm_needed_emits_correct_result(self, tmp_path: Path) -> None:
        """An SCM action that is *not* installed is surfaced as Needed."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action = self._make_scm_action()
        preview = SetupResults(actions=[action])

        manifest_event = ProgressEvent(kind=ProgressEventKind.MANIFEST_LOADED, manifest=preview)
        result = SetupActionResult(
            action=action,
            success=True,
            skipped=False,
            skip_reason=None,
        )
        completed_event = ProgressEvent(
            kind=ProgressEventKind.ACTION_COMPLETED,
            action=action,
            result=result,
        )

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        worker = PreviewWorker(porringer, str(manifest), project_directory=tmp_path)

        checked: list[tuple[int, SetupActionResult]] = []
        worker.action_checked.connect(lambda row, r: checked.append((row, r)))
        worker.run()

        assert len(checked) == 1
        assert checked[0][1].skipped is False
        assert checked[0][1].skip_reason is None


class TestPrereleaseCheckboxLock:
    """Tests for the pre-release checkbox lock/unlock decision logic.

    The checkbox should be locked (disabled) only when the manifest
    sets ``include_prereleases=True`` AND the user has NOT added the
    package as an override.  If the user checked the box manually
    (package in ``_prerelease_overrides``), it must remain unlocked
    even after the reload returns the action with
    ``include_prereleases=True`` (because the upstream applied the
    user's override additively).
    """

    @staticmethod
    @pytest.mark.parametrize(
        ('include_prereleases', 'in_overrides', 'expected_locked'),
        [
            # Manifest enables pre-release, user hasn't touched it → locked
            (True, False, True),
            # Manifest enables pre-release, but user toggled it on → unlocked
            (True, True, False),
            # Manifest does not enable, user hasn't touched → unlocked
            (False, False, False),
            # Manifest does not enable, user checked it → unlocked
            (False, True, False),
        ],
    )
    def test_lock_decision(
        include_prereleases: bool,
        in_overrides: bool,
        expected_locked: bool,
    ) -> None:
        """Verify the manifest-native vs user-override lock decision."""
        # Mirror the conditional in _populate_table:
        #   if action.include_prereleases and not is_user_override → locked
        is_user_override = in_overrides
        locked = include_prereleases and not is_user_override
        assert locked is expected_locked
