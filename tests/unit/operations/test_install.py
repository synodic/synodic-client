"""Tests for operations.install module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from porringer.schema import ProgressEvent, SetupParameters

from synodic_client.operations.install import execute_install, preview_manifest
from synodic_client.operations.schema import ActionInfo, PreviewResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest_parsed_event(*, name: str = '', description: str = '', manifest_path: str = '') -> MagicMock:
    """Build a mock ManifestParsedEvent."""
    from porringer.schema import ManifestMetadata, ManifestParsedEvent  # noqa: PLC0415

    event = MagicMock(spec=ManifestParsedEvent)
    event.manifest.metadata = ManifestMetadata(name=name, description=description)
    event.manifest.manifest_path = manifest_path or None
    return event


def _make_manifest_loaded_event(actions: list[MagicMock] | None = None) -> MagicMock:
    """Build a mock ManifestLoadedEvent."""
    from porringer.schema import ManifestLoadedEvent  # noqa: PLC0415

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

        async def _empty_stream(*_a: object, **_kw: object):  # noqa: ANN202
            return
            yield  # make it an async generator  # noqa: RET503

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

        async def _stream(*_a: object, **_kw: object):  # noqa: ANN202
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

        async def _capture_stream(params: SetupParameters, **_kw: object):  # noqa: ANN202
            captured_params.append(params)
            return
            yield  # noqa: RET503

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
        from porringer.schema import (  # noqa: PLC0415
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

        async def _stream(*_a: object, **_kw: object):  # noqa: ANN202
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

        async def _empty(*_a: object, **_kw: object):  # noqa: ANN202
            return
            yield  # noqa: RET503

        api.sync.execute_stream = _empty

        async def _collect() -> list[tuple[str, ProgressEvent]]:
            results = []
            async for stage, event in execute_install(api, Path('/m.json')):
                results.append((stage, event))
            return results

        results = asyncio.run(_collect())
        assert results == []
