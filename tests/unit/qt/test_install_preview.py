"""Tests for the install preview window and URI-based install flow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from porringer.schema import (
    ActionCompletedEvent,
    DiscoveredPluginEntry,
    DownloadResult,
    ManifestLoadedEvent,
    ManifestParsedEvent,
    PluginsDiscoveredEvent,
    SetupActionResult,
    SetupResults,
    SkipReason,
)
from porringer.schema.plugin import PluginKind

from synodic_client.application.screen import (
    ACTION_KIND_LABELS,
    SKIP_REASON_LABELS,
    format_cli_command,
    skip_reason_label,
)
from synodic_client.application.screen.install_workers import run_install, run_preview
from synodic_client.application.screen.schema import InstallConfig, PreviewCallbacks, PreviewConfig
from synodic_client.application.uri import normalize_manifest_key, resolve_local_path

_DOWNLOAD_PATCH = 'synodic_client.application.screen.install_workers.API.download'
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
        return action

    def test_prefers_cli_command_from_result(self) -> None:
        """Verify result cli_command takes precedence over command and fallback."""
        action = self._make_action()
        result = MagicMock()
        result.cli_command = ('uv', 'pip', 'install', 'requests')
        assert format_cli_command(action, result=result) == 'uv pip install requests'

    def test_falls_back_to_command(self) -> None:
        """Verify command is used when cli_command is absent."""
        action = self._make_action(
            kind='TOOL',
            command=('echo', 'hello'),
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
    """Tests for run_install coroutine."""

    @staticmethod
    def test_worker_emits_finished_on_success() -> None:
        """Verify coroutine returns results on success."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        action = MagicMock()
        manifest = SetupResults(actions=[action])
        manifest_event = ManifestLoadedEvent(manifest=manifest)

        result = MagicMock(spec=SetupActionResult)
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
            action_index=0,
        )

        async def mock_stream(*args, **kwargs):
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        results = asyncio.run(run_install(porringer, manifest_path))

        assert results.actions == manifest.actions

    @staticmethod
    def test_worker_emits_error_on_failure() -> None:
        """Verify coroutine raises on exception."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        async def mock_stream(*args, **kwargs):
            if False:
                yield  # pragma: no cover — establishes async generator protocol
            msg = 'boom'
            raise RuntimeError(msg)

        porringer.sync.execute_stream = mock_stream

        with pytest.raises(RuntimeError, match='boom'):
            asyncio.run(run_install(porringer, manifest_path))

    @staticmethod
    def test_worker_passes_prerelease_packages() -> None:
        """Verify prerelease_packages is forwarded to SetupParameters."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        manifest = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=manifest)

        captured_params: list[Any] = []

        async def mock_stream(params: Any, **kwargs: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        asyncio.run(
            run_install(
                porringer,
                manifest_path,
                InstallConfig(prerelease_packages={'cppython'}),
            ),
        )

        assert len(captured_params) == 1
        assert captured_params[0].prerelease_packages == {'cppython'}

    @staticmethod
    def test_worker_omits_prerelease_when_none() -> None:
        """Verify prerelease_packages defaults to None."""
        porringer = MagicMock()
        manifest_path = Path('/tmp/test/porringer.json')

        manifest = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=manifest)

        captured_params: list[Any] = []

        async def mock_stream(params: Any, **kwargs: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        asyncio.run(run_install(porringer, manifest_path))

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
    """Tests for run_preview with local manifest files."""

    @staticmethod
    def test_local_manifest_skips_download(tmp_path: Path) -> None:
        """Verify run_preview skips download for local files."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        expected = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=expected)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        results: list[tuple[object, str, str]] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_preview_ready=lambda r, p, t: results.append((r, p, t)),
                ),
            ),
        )

        assert len(results) == 1
        assert results[0][0] is expected
        # download should NOT have been called
        porringer.sync.download.assert_not_called()

    @staticmethod
    def test_local_manifest_not_found(tmp_path: Path) -> None:
        """Verify run_preview raises error for missing local file."""
        path = str(tmp_path / 'nonexistent' / 'porringer.json')
        porringer = MagicMock()

        with pytest.raises(FileNotFoundError, match='not found'):
            asyncio.run(run_preview(porringer, path))


class TestPreviewWorker:
    """Tests for run_preview download and preview flow."""

    @staticmethod
    def test_emits_error_on_download_failure(monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify run_preview raises when download fails."""
        porringer = MagicMock()

        async def _mock_download(params: Any, progress_callback: Any = None) -> DownloadResult:
            return DownloadResult(
                success=False,
                path=None,
                verified=False,
                size=0,
                message='Network error',
            )

        monkeypatch.setattr(_DOWNLOAD_PATCH, _mock_download)

        with pytest.raises(RuntimeError, match='Network error'):
            asyncio.run(run_preview(porringer, 'https://example.com/bad.json'))

    @staticmethod
    def test_emits_preview_ready_on_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Verify run_preview invokes on_preview_ready with SetupResults."""
        porringer = MagicMock()

        dest = tmp_path / 'porringer.json'
        dest.write_text('{}')

        async def _mock_download(params: Any, progress_callback: Any = None) -> DownloadResult:
            return DownloadResult(
                success=True,
                path=dest,
                verified=True,
                size=100,
                message='OK',
            )

        monkeypatch.setattr(_DOWNLOAD_PATCH, _mock_download)

        expected = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=expected)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        results: list[tuple[object, str, str]] = []

        asyncio.run(
            run_preview(
                porringer,
                'https://example.com/good.json',
                callbacks=PreviewCallbacks(
                    on_preview_ready=lambda r, p, t: results.append((r, p, t)),
                ),
            ),
        )

        assert len(results) == 1
        assert results[0][0] is expected


class TestPreviewWorkerSignals:
    """Tests for run_preview callback invocation and dry-run status check."""

    @staticmethod
    def test_emits_preview_ready_and_finished(tmp_path: Path) -> None:
        """Verify coroutine invokes on_preview_ready for a local manifest."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action = MagicMock()
        action.kind = PluginKind.PACKAGE
        preview = SetupResults(actions=[action])

        # Dry-run stream yields manifest loaded then one completed event
        manifest_event = ManifestLoadedEvent(manifest=preview)
        result = SetupActionResult(action=action, success=True, skipped=False, skip_reason=None)
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
            action_index=0,
        )

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        ready_calls: list[tuple[object, str, str]] = []
        checked: list[tuple[int, SetupActionResult]] = []
        finished = False

        async def _run() -> None:
            nonlocal finished
            await run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_preview_ready=lambda p, m, t: ready_calls.append((p, m, t)),
                    on_action_checked=lambda row, r: checked.append((row, r)),
                ),
            )
            finished = True

        asyncio.run(_run())

        assert len(ready_calls) == 1
        assert ready_calls[0][0] is preview
        assert len(checked) == 1
        assert checked[0] == (0, result)
        assert finished

    @staticmethod
    def test_emits_finished_for_empty_actions(tmp_path: Path) -> None:
        """Verify coroutine completes normally with no actions."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        finished = False

        async def _run() -> None:
            nonlocal finished
            await run_preview(porringer, str(manifest))
            finished = True

        asyncio.run(_run())
        assert finished

    @staticmethod
    def test_action_checked_maps_correct_rows(tmp_path: Path) -> None:
        """Verify on_action_checked receives correct row indices via content-based matching."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action_a = MagicMock()
        action_a.kind = PluginKind.RUNTIME
        action_b = MagicMock()
        action_b.kind = PluginKind.PACKAGE
        preview = SetupResults(actions=[action_a, action_b])

        manifest_event = ManifestLoadedEvent(manifest=preview)
        result_b = SetupActionResult(
            action=action_b, success=True, skipped=True, skip_reason=SkipReason.ALREADY_INSTALLED
        )
        result_a = SetupActionResult(action=action_a, success=True, skipped=False, skip_reason=None)

        # Stream returns in execution order (b before a), not preview order
        event_b = ActionCompletedEvent(
            action=action_b,
            result=result_b,
            action_index=1,
        )
        event_a = ActionCompletedEvent(
            action=action_a,
            result=result_a,
            action_index=0,
        )

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield event_b
            yield event_a

        porringer.sync.execute_stream = mock_stream

        checked: list[tuple[int, SetupActionResult]] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_action_checked=lambda row, r: checked.append((row, r)),
                ),
            ),
        )

        assert len(checked) == _EXPECTED_CHECKED_COUNT
        # action_b is at index 1 in preview, action_a at index 0
        assert checked[0] == (1, result_b)
        assert checked[1] == (0, result_a)

    @staticmethod
    def test_emits_error_when_dry_run_fails(tmp_path: Path) -> None:
        """Verify coroutine raises when dry-run fails."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            if False:
                yield  # pragma: no cover — establishes async generator protocol
            msg = 'dry-run boom'
            raise RuntimeError(msg)

        porringer.sync.execute_stream = mock_stream

        with pytest.raises(RuntimeError, match='dry-run boom'):
            asyncio.run(run_preview(porringer, str(manifest)))

    @staticmethod
    def test_emits_plugins_queried(tmp_path: Path) -> None:
        """Verify on_plugins_queried is invoked with plugin presence mapping."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        plugins_event = PluginsDiscoveredEvent(
            discovered_plugins=(
                DiscoveredPluginEntry(name='pip', available=True, capabilities=frozenset(), kind=PluginKind.PACKAGE),
                DiscoveredPluginEntry(name='uv', available=False, capabilities=frozenset(), kind=PluginKind.PACKAGE),
            ),
        )
        manifest_event = ManifestLoadedEvent(manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield plugins_event
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        plugin_data: list[dict[str, bool]] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_plugins_queried=plugin_data.append,
                ),
            ),
        )

        assert len(plugin_data) == 1
        assert plugin_data[0] == {'pip': True, 'uv': False}

    @staticmethod
    def test_plugins_queried_emitted_before_preview_ready(tmp_path: Path) -> None:
        """Verify on_plugins_queried fires before on_preview_ready."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        plugins_event = PluginsDiscoveredEvent(
            discovered_plugins=(),
        )
        manifest_event = ManifestLoadedEvent(manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield plugins_event
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        order: list[str] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_plugins_queried=lambda _: order.append('plugins'),
                    on_preview_ready=lambda *_: order.append('preview'),
                ),
            ),
        )

        assert order == ['plugins', 'preview']

    @staticmethod
    def test_emits_manifest_parsed(tmp_path: Path) -> None:
        """Verify on_manifest_parsed is invoked from MANIFEST_PARSED events."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        parsed_event = ManifestParsedEvent(
            manifest=preview,
        )
        loaded_event = ManifestLoadedEvent(manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield parsed_event
            yield loaded_event

        porringer.sync.execute_stream = mock_stream

        parsed_data: list[Any] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_manifest_parsed=lambda *a: parsed_data.append(a),
                ),
            ),
        )

        assert len(parsed_data) == 1

    @staticmethod
    def test_two_phase_signal_order(tmp_path: Path) -> None:
        """Verify the full two-phase callback order: parsed → plugins → ready."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()

        preview = SetupResults(actions=[])
        parsed_event = ManifestParsedEvent(
            manifest=preview,
        )
        plugins_event = PluginsDiscoveredEvent(
            discovered_plugins=(
                DiscoveredPluginEntry(name='pip', available=True, capabilities=frozenset(), kind=PluginKind.PACKAGE),
            ),
        )
        loaded_event = ManifestLoadedEvent(manifest=preview)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield parsed_event
            yield plugins_event
            yield loaded_event

        porringer.sync.execute_stream = mock_stream

        order: list[str] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                callbacks=PreviewCallbacks(
                    on_manifest_parsed=lambda *_: order.append('parsed'),
                    on_plugins_queried=lambda _: order.append('plugins'),
                    on_preview_ready=lambda *_: order.append('ready'),
                ),
            ),
        )

        assert order == ['parsed', 'plugins', 'ready']


class TestPreviewWorkerPrerelease:
    """Tests for run_preview passing prerelease config to porringer."""

    @staticmethod
    def test_passes_prerelease_packages(tmp_path: Path) -> None:
        """Verify prerelease_packages are forwarded to SetupParameters."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any, **kwargs: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                config=PreviewConfig(
                    prerelease_packages={'some-pkg'},
                ),
            ),
        )

        assert len(captured_params) == 1
        assert captured_params[0].prerelease_packages == {'some-pkg'}

    @staticmethod
    def test_defaults_prerelease_none(tmp_path: Path) -> None:
        """Verify prerelease_packages defaults to None."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any, **kwargs: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        asyncio.run(run_preview(porringer, str(manifest)))

        assert len(captured_params) == 1
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
        manifest_event = ManifestLoadedEvent(manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any, **kwargs: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                config=PreviewConfig(project_directory=manifest.parent),
            ),
        )

        assert len(captured_params) == 1
        assert captured_params[0].project_directory == tmp_path

    @staticmethod
    def test_directory_path_forwarded_directly(tmp_path: Path) -> None:
        """When a directory is selected its path is forwarded as-is."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        preview = SetupResults(actions=[])
        manifest_event = ManifestLoadedEvent(manifest=preview)

        captured_params: list[Any] = []

        async def mock_stream(params: Any, **kwargs: Any) -> Any:
            captured_params.append(params)
            yield manifest_event

        porringer.sync.execute_stream = mock_stream

        asyncio.run(
            run_preview(
                porringer,
                str(tmp_path),
                config=PreviewConfig(project_directory=tmp_path),
            ),
        )

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
        return action

    def test_scm_already_installed_emits_correct_result(self, tmp_path: Path) -> None:
        """An SCM action with ALREADY_INSTALLED is surfaced via on_action_checked."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{}')

        porringer = MagicMock()
        action = self._make_scm_action()
        preview = SetupResults(actions=[action])

        manifest_event = ManifestLoadedEvent(manifest=preview)
        result = SetupActionResult(
            action=action,
            success=True,
            skipped=True,
            skip_reason=SkipReason.ALREADY_INSTALLED,
        )
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
            action_index=0,
        )

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        checked: list[tuple[int, SetupActionResult]] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                config=PreviewConfig(project_directory=tmp_path),
                callbacks=PreviewCallbacks(
                    on_action_checked=lambda row, r: checked.append((row, r)),
                ),
            ),
        )

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

        manifest_event = ManifestLoadedEvent(manifest=preview)
        result = SetupActionResult(
            action=action,
            success=True,
            skipped=False,
            skip_reason=None,
        )
        completed_event = ActionCompletedEvent(
            action=action,
            result=result,
            action_index=0,
        )

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            yield manifest_event
            yield completed_event

        porringer.sync.execute_stream = mock_stream

        checked: list[tuple[int, SetupActionResult]] = []

        asyncio.run(
            run_preview(
                porringer,
                str(manifest),
                config=PreviewConfig(project_directory=tmp_path),
                callbacks=PreviewCallbacks(
                    on_action_checked=lambda row, r: checked.append((row, r)),
                ),
            ),
        )

        assert len(checked) == 1
        assert checked[0][1].skipped is False
        assert checked[0][1].skip_reason is None
