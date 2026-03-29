"""Tests for operations.install module."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

from porringer.schema import ProgressEvent, SetupParameters

from synodic_client.operations.install import (
    execute_install,
    execute_post_sync,
    load_manifest_actions,
    preview_manifest,
)
from synodic_client.operations.schema import ActionInfo, PreviewResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_parsed_event(*, name: str = '', description: str = '', manifest_path: str = '') -> MagicMock:
    """Build a mock ManifestParsedEvent."""
    from porringer.schema import ManifestMetadata, ManifestParsedEvent

    event = MagicMock(spec=ManifestParsedEvent)
    event.manifest.metadata = ManifestMetadata(name=name, description=description)
    event.manifest.manifest_path = manifest_path or None
    return event


def _make_manifest_loaded_event(actions: list[MagicMock] | None = None) -> MagicMock:
    """Build a mock ManifestLoadedEvent."""
    from porringer.schema import ManifestLoadedEvent

    event = MagicMock(spec=ManifestLoadedEvent)
    event.manifest.actions = actions or []
    return event


def _make_action(
    *,
    description: str = '',
    kind_name: str | None = None,
    package_name: str | None = None,
    constraint: str | None = None,
    installer: str | None = None,
) -> MagicMock:
    """Build a mock manifest action."""
    action = MagicMock()
    action.description = description
    action.kind.name = kind_name
    if kind_name is None:
        action.kind = None
    action.installer = installer
    if package_name is not None:
        action.package.name = package_name
        action.package.constraint = constraint
    else:
        action.package = None
    action.distro = None
    return action


# ---------------------------------------------------------------------------
# preview_manifest
# ---------------------------------------------------------------------------


class TestPreviewManifest:
    """Tests for preview_manifest()."""

    @staticmethod
    def test_empty_stream() -> None:
        """No events → empty PreviewResult."""
        api = MagicMock()

        async def _empty_stream(*_a: object, **_kw: object):
            return
            yield  # make it an async generator

        api.sync.execute_stream = _empty_stream

        result = asyncio.run(preview_manifest(api, 'https://example.com/manifest.json'))
        assert isinstance(result, PreviewResult)
        assert result.actions == []
        assert not result.project_name

    @staticmethod
    def test_parses_metadata_and_actions() -> None:
        """Extracts project name, description, and actions from events."""
        parsed_event = _make_manifest_parsed_event(
            name='My Project',
            description='A test project',
            manifest_path='/tmp/manifest.json',
        )
        action = _make_action(
            description='Install requests',
            kind_name='INSTALL',
            package_name='requests',
            constraint='>=2.0',
            installer='pip',
        )
        loaded_event = _make_manifest_loaded_event(actions=[action])

        api = MagicMock()

        async def _stream(*_a: object, **_kw: object):
            yield parsed_event
            yield loaded_event

        api.sync.execute_stream = _stream

        result = asyncio.run(preview_manifest(api, 'https://example.com/manifest.json'))
        assert result.project_name == 'My Project'
        assert result.description == 'A test project'
        assert result.manifest_key == '/tmp/manifest.json'
        assert len(result.actions) == 1
        assert result.actions[0] == ActionInfo(
            description='Install requests',
            kind='INSTALL',
            package='requests',
            constraint='>=2.0',
            installer='pip',
        )

    @staticmethod
    def test_passes_parameters_correctly() -> None:
        """Verifies SetupParameters are constructed with correct args."""
        api = MagicMock()
        captured_params: list[SetupParameters] = []

        async def _capture_stream(params: SetupParameters, **_kw: object):
            captured_params.append(params)
            return
            yield

        api.sync.execute_stream = _capture_stream

        asyncio.run(
            preview_manifest(
                api,
                'https://example.com/m.json',
                project_directory=Path('/proj'),
                prerelease_packages={'alpha-pkg'},
            )
        )

        assert len(captured_params) == 1
        p = captured_params[0]
        assert p.paths == ['https://example.com/m.json']
        assert p.dry_run is True
        assert p.project_directory == Path('/proj')
        assert p.prerelease_packages == {'alpha-pkg'}


# ---------------------------------------------------------------------------
# execute_install
# ---------------------------------------------------------------------------


class TestExecuteInstall:
    """Tests for execute_install()."""

    @staticmethod
    def test_yields_stage_event_tuples() -> None:
        """Yields (stage, event) tuples for different event types."""
        from porringer.schema import (
            ActionCompletedEvent,
            ActionStartedEvent,
            ManifestLoadedEvent,
            SubActionProgressEvent,
        )

        loaded = MagicMock(spec=ManifestLoadedEvent)
        started = MagicMock(spec=ActionStartedEvent)
        progress = MagicMock(spec=SubActionProgressEvent)
        completed = MagicMock(spec=ActionCompletedEvent)
        other = MagicMock()  # no spec → falls through to 'other'

        api = MagicMock()

        async def _stream(*_a: object, **_kw: object):
            yield loaded
            yield started
            yield progress
            yield completed
            yield other

        api.sync.execute_stream = _stream

        async def _collect() -> list[tuple[str, ProgressEvent]]:
            results = []
            async for stage, event in execute_install(api, Path('/m.json')):
                results.append((stage, event))
            return results

        results = asyncio.run(_collect())
        expected_count = 5
        assert len(results) == expected_count
        assert results[0] == ('manifest_loaded', loaded)
        assert results[1] == ('action_started', started)
        assert results[2] == ('sub_progress', progress)
        assert results[3] == ('action_completed', completed)
        assert results[4] == ('other', other)

    @staticmethod
    def test_empty_stream() -> None:
        """No events → no yields."""
        api = MagicMock()

        async def _empty(*_a: object, **_kw: object):
            return
            yield

        api.sync.execute_stream = _empty

        async def _collect() -> list[tuple[str, ProgressEvent]]:
            results = []
            async for stage, event in execute_install(api, Path('/m.json')):
                results.append((stage, event))
            return results

        results = asyncio.run(_collect())
        assert results == []

    @staticmethod
    def test_exclude_post_sync(tmp_path: Path) -> None:
        """exclude_post_sync=True strips post_sync from manifest before execution."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text(
            json.dumps({
                'version': '1',
                'actions': [{'description': 'install something'}],
                'post_sync': [{'command': 'echo hello'}],
            }),
            encoding='utf-8',
        )

        api = MagicMock()
        captured_params: list[SetupParameters] = []
        captured_manifest_data: list[dict] = []

        async def _capture(params: SetupParameters, **_kw: object):
            captured_params.append(params)
            # Read the temp manifest before it's cleaned up
            assert isinstance(params.paths, (list, tuple))
            path = Path(str(params.paths[0]))
            captured_manifest_data.append(json.loads(path.read_text(encoding='utf-8')))
            return
            yield

        api.sync.execute_stream = _capture

        async def _run() -> list:
            return [item async for item in execute_install(api, manifest, exclude_post_sync=True)]

        asyncio.run(_run())

        assert len(captured_params) == 1
        # The effective path should differ from the original (temp file)
        paths = captured_params[0].paths
        assert isinstance(paths, (list, tuple))
        used_path = paths[0]
        assert str(used_path) != str(manifest)
        # The temp file should have had empty post_sync
        assert captured_manifest_data[0]['post_sync'] == []

    @staticmethod
    def test_exclude_post_sync_no_post_sync(tmp_path: Path) -> None:
        """exclude_post_sync=True with no post_sync uses original manifest."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text(
            json.dumps({'version': '1', 'actions': []}),
            encoding='utf-8',
        )

        api = MagicMock()
        captured_params: list[SetupParameters] = []

        async def _capture(params: SetupParameters, **_kw: object):
            captured_params.append(params)
            return
            yield

        api.sync.execute_stream = _capture

        async def _run() -> list:
            return [item async for item in execute_install(api, manifest, exclude_post_sync=True)]

        asyncio.run(_run())

        assert len(captured_params) == 1
        # Should use original path since there's no post_sync to strip
        paths = captured_params[0].paths
        assert isinstance(paths, (list, tuple))
        used_path = Path(str(paths[0]))
        assert used_path == manifest


# ---------------------------------------------------------------------------
# execute_post_sync
# ---------------------------------------------------------------------------


class TestExecutePostSync:
    """Tests for execute_post_sync()."""

    @staticmethod
    def test_yields_events_from_post_sync_manifest(tmp_path: Path) -> None:
        """Extracts post_sync, executes, and yields events."""
        from porringer.schema import ManifestLoadedEvent

        manifest = tmp_path / 'porringer.json'
        manifest.write_text(
            json.dumps({
                'version': '1',
                'actions': [{'description': 'install something'}],
                'post_sync': [{'command': 'echo hello'}],
            }),
            encoding='utf-8',
        )

        loaded = MagicMock(spec=ManifestLoadedEvent)
        api = MagicMock()

        async def _stream(params: SetupParameters, **_kw: object):
            yield loaded

        api.sync.execute_stream = _stream

        async def _collect() -> list[tuple[str, ProgressEvent]]:
            return [(s, e) async for s, e in execute_post_sync(api, manifest)]

        results = asyncio.run(_collect())
        assert len(results) == 1
        assert results[0] == ('manifest_loaded', loaded)

    @staticmethod
    def test_no_post_sync_yields_nothing(tmp_path: Path) -> None:
        """No post_sync entries → yields nothing."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text(
            json.dumps({'version': '1', 'actions': []}),
            encoding='utf-8',
        )

        api = MagicMock()

        async def _collect() -> list[tuple[str, ProgressEvent]]:
            return [(s, e) async for s, e in execute_post_sync(api, manifest)]

        results = asyncio.run(_collect())
        assert results == []


# ---------------------------------------------------------------------------
# load_manifest_actions
# ---------------------------------------------------------------------------


class TestLoadManifestActions:
    """Tests for load_manifest_actions()."""

    @staticmethod
    def test_fast_path_with_discovered() -> None:
        """Uses async_load_manifest when discovered plugins are provided."""
        api = MagicMock()
        action1 = MagicMock()
        action2 = MagicMock()
        mock_result = MagicMock()
        mock_result.actions = [action1, action2]

        async def _mock_load(*_a, **_kw):
            return mock_result

        api.sync.async_load_manifest = _mock_load

        discovered = MagicMock()

        actions = asyncio.run(
            load_manifest_actions(api, Path('/tmp/manifest.json'), discovered=discovered),
        )
        expected_count = 2
        assert len(actions) == expected_count
        assert actions[0] is action1
        assert actions[1] is action2

    @staticmethod
    def test_legacy_path_without_discovered() -> None:
        """Falls back to execute_stream when no discovered plugins."""
        from porringer.schema import ManifestParsedEvent

        api = MagicMock()
        action = MagicMock()
        parsed_event = MagicMock(spec=ManifestParsedEvent)
        parsed_event.manifest.actions = [action]

        async def _stream(*_a, **_kw):
            yield parsed_event

        api.sync.execute_stream = _stream

        actions = asyncio.run(
            load_manifest_actions(api, Path('/tmp/manifest.json'), project_directory=Path('/proj')),
        )
        assert len(actions) == 1
        assert actions[0] is action

    @staticmethod
    def test_empty_manifest_returns_empty_list() -> None:
        """Empty stream → empty list."""
        api = MagicMock()

        async def _empty(*_a, **_kw):
            return
            yield

        api.sync.execute_stream = _empty

        actions = asyncio.run(load_manifest_actions(api, Path('/tmp/manifest.json')))
        assert actions == []
