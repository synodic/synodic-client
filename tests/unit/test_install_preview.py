"""Tests for the install preview window and URI-based install flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from porringer.schema import (
    CancellationToken,
    DownloadResult,
    SetupActionType,
    SetupResults,
    ThreadSafeProgressAdapter,
)

from synodic_client.application.qt import parse_uri
from synodic_client.application.screen.install import (
    ACTION_TYPE_LABELS,
    InstallWorker,
    PreviewWorker,
    resolve_local_path,
)


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
        action_type: str = 'INSTALL_PACKAGE',
        description: str = 'Install test',
        plugin: str = 'pip',
        package: str = 'requests',
    ) -> MagicMock:
        """Create a mock SetupAction."""
        action = MagicMock()
        action.action_type = getattr(SetupActionType, action_type)
        action.description = description
        action.plugin = plugin
        action.package = package
        action.command = None
        action.cli_command = None
        return action

    @staticmethod
    def test_action_type_labels() -> None:
        """Verify action type label mapping covers all types."""
        for action_type in SetupActionType:
            assert action_type in ACTION_TYPE_LABELS


class TestInstallWorker:
    """Tests for InstallWorker signal emission."""

    @staticmethod
    def test_worker_emits_finished_on_success() -> None:
        """Verify worker emits finished signal with results."""
        porringer = MagicMock()
        expected = SetupResults(actions=[])

        # Make execute_single_async an awaitable that returns expected
        async def mock_execute(*args, **kwargs):  # noqa: ANN002, ANN003
            return expected

        porringer.update.execute_single_async = mock_execute

        adapter = MagicMock(spec=ThreadSafeProgressAdapter)
        token = CancellationToken()

        worker = InstallWorker(porringer, [], Path('/tmp/test'), adapter, token)

        received: list[SetupResults] = []
        worker.finished.connect(received.append)
        worker.run()

        assert len(received) == 1
        assert received[0] is expected

    @staticmethod
    def test_worker_emits_error_on_failure() -> None:
        """Verify worker emits error signal on exception."""
        porringer = MagicMock()

        async def mock_execute(*args, **kwargs):  # noqa: ANN002, ANN003
            msg = 'boom'
            raise RuntimeError(msg)

        porringer.update.execute_single_async = mock_execute

        adapter = MagicMock(spec=ThreadSafeProgressAdapter)
        token = CancellationToken()

        worker = InstallWorker(porringer, [], Path('/tmp/test'), adapter, token)

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
    def test_absolute_path_returns_path() -> None:
        """Absolute OS paths should resolve."""
        result = resolve_local_path('C:\\Users\\test\\porringer.json')
        assert result is not None
        assert result == Path('C:\\Users\\test\\porringer.json')

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
        porringer.update.preview_single.return_value = expected

        worker = PreviewWorker(porringer, str(manifest))

        results: list[tuple[object, str, str]] = []
        worker.finished.connect(lambda r, p, t: results.append((r, p, t)))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is expected
        # download should NOT have been called
        porringer.update.download.assert_not_called()

    @staticmethod
    def test_local_manifest_not_found() -> None:
        """Verify PreviewWorker emits error for missing local file."""
        porringer = MagicMock()
        worker = PreviewWorker(porringer, 'C:\\nonexistent\\porringer.json')

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
        porringer.update.download.return_value = DownloadResult(
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
    def test_emits_finished_on_success() -> None:
        """Verify PreviewWorker emits finished with SetupResults."""
        porringer = MagicMock()
        porringer.update.download.return_value = DownloadResult(
            success=True,
            path=Path('/tmp/test/porringer.json'),
            verified=True,
            size=100,
            message='OK',
        )
        expected = SetupResults(actions=[])
        porringer.update.preview_single.return_value = expected

        worker = PreviewWorker(porringer, 'https://example.com/good.json')

        results: list[tuple[object, str, str]] = []
        worker.finished.connect(lambda r, p, t: results.append((r, p, t)))
        worker.run()

        assert len(results) == 1
        assert results[0][0] is expected
