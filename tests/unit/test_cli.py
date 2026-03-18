"""Tests for the CLI entry point."""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip('PySide6.QtWidgets', reason='PySide6 requires system Qt libraries')

from typer.testing import CliRunner

from synodic_client.cli import app
from synodic_client.operations.schema import (
    ConfigKeyInfo,
    DownloadResult,
    ProjectInfo,
    UpdateCheckResult,
    UpdateResult,
)

runner = CliRunner()

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


class TestCli:
    """Tests for the synodic-c CLI."""

    @staticmethod
    def test_version() -> None:
        """Verify --version prints the version string."""
        result = runner.invoke(app, ['--version'])
        assert result.exit_code == 0
        assert 'synodic-client' in result.output

    @staticmethod
    def test_help() -> None:
        """Verify --help shows usage information."""
        result = runner.invoke(app, ['--help'])
        assert result.exit_code == 0
        assert '--uri' in _strip_ansi(result.output)

    @staticmethod
    def test_launches_application_without_uri() -> None:
        """Verify invoking with no args calls application(uri=None, dev_mode=False)."""
        with patch('synodic_client.application.qt.application') as mock_app:
            result = runner.invoke(app, [])
            assert result.exit_code == 0
            mock_app.assert_called_once_with(uri=None, dev_mode=False, debug=False)

    @staticmethod
    def test_launches_application_with_uri() -> None:
        """Verify invoking with --uri passes it to application()."""
        test_uri = 'synodic://install?manifest=https://example.com/foo.json'
        with patch('synodic_client.application.qt.application') as mock_app:
            result = runner.invoke(app, ['--uri', test_uri])
            assert result.exit_code == 0
            mock_app.assert_called_once_with(uri=test_uri, dev_mode=False, debug=False)

    @staticmethod
    def test_launches_application_with_dev_flag() -> None:
        """Verify --dev flag sets dev_mode=True."""
        with patch('synodic_client.application.qt.application') as mock_app:
            result = runner.invoke(app, ['--dev'])
            assert result.exit_code == 0
            mock_app.assert_called_once_with(uri=None, dev_mode=True, debug=False)


# ---------------------------------------------------------------------------
# Project subcommands
# ---------------------------------------------------------------------------


class TestProjectCli:
    """Tests for synodic-c project sub-commands."""

    @staticmethod
    def test_project_list() -> None:
        """Project list renders projects."""
        projects = [
            ProjectInfo(path='/a', name='a', exists=True, has_manifest=True),
        ]
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch('synodic_client.operations.project.list_projects', return_value=projects),
        ):
            result = runner.invoke(app, ['project', 'list'])
            assert result.exit_code == 0
            assert '/a' in result.output

    @staticmethod
    def test_project_list_json() -> None:
        """Project list --json returns valid JSON."""
        projects = [
            ProjectInfo(path='/a', name='a', exists=True, has_manifest=False),
        ]
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch('synodic_client.operations.project.list_projects', return_value=projects),
        ):
            result = runner.invoke(app, ['project', 'list', '--json'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, list)
            assert data[0]['path'] == '/a'

    @staticmethod
    def test_project_add_not_a_directory() -> None:
        """Project add with a bad path exits with code 1."""
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch('synodic_client.operations.project.add_project', side_effect=NotADirectoryError('Not a directory')),
        ):
            result = runner.invoke(app, ['project', 'add', '/nonexistent'])
            assert result.exit_code == 1

    @staticmethod
    def test_project_remove() -> None:
        """Project remove delegates and prints confirmation."""
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch('synodic_client.operations.project.remove_project') as mock_remove,
        ):
            result = runner.invoke(app, ['project', 'remove', '/tmp/foo'])
            assert result.exit_code == 0
            assert 'Removed' in result.output
            mock_remove.assert_called_once()


# ---------------------------------------------------------------------------
# Tool subcommands
# ---------------------------------------------------------------------------


class TestToolCli:
    """Tests for synodic-c tool sub-commands."""

    @staticmethod
    def test_tool_check() -> None:
        """Tool check renders available updates."""
        api = MagicMock()
        api.cache.list_directories.return_value = []
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, api, None)),
            patch(
                'synodic_client.operations.tool.check_tool_updates',
                new_callable=AsyncMock,
                return_value={'pip': {'requests': '2.32'}},
            ),
        ):
            result = runner.invoke(app, ['tool', 'check'])
            assert result.exit_code == 0

    @staticmethod
    def test_tool_update() -> None:
        """Tool update renders an UpdateResult."""
        update_result = UpdateResult(plugin='pip', packages_updated=['requests'])
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch(
                'synodic_client.operations.tool.update_tool',
                new_callable=AsyncMock,
                return_value=update_result,
            ),
        ):
            result = runner.invoke(app, ['tool', 'update', 'pip'])
            assert result.exit_code == 0

    @staticmethod
    def test_tool_update_json_with_versions() -> None:
        """Tool update --json serialises sets, tuples, and version_map."""
        update_result = UpdateResult(
            plugin='pip',
            packages_updated=['requests'],
            updated_packages={'requests'},
            version_map={'requests': ('2.31.0', '2.32.0')},
        )
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch(
                'synodic_client.operations.tool.update_tool',
                new_callable=AsyncMock,
                return_value=update_result,
            ),
        ):
            result = runner.invoke(app, ['tool', 'update', 'pip', '--json'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data['updated_packages'] == ['requests']
            assert data['version_map'] == {'requests': ['2.31.0', '2.32.0']}

    @staticmethod
    def test_tool_remove_json() -> None:
        """Tool remove --json returns valid JSON with success."""
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch(
                'synodic_client.operations.tool.remove_package',
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = runner.invoke(app, ['tool', 'remove', 'pip', 'requests', '--json'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data['success'] is True


# ---------------------------------------------------------------------------
# Config subcommands
# ---------------------------------------------------------------------------


class TestConfigCli:
    """Tests for synodic-c config sub-commands."""

    @staticmethod
    def test_config_get_unknown_key() -> None:
        """Config get with unknown key exits code 1."""
        with patch(
            'synodic_client.operations.config.get_config_value',
            side_effect=KeyError("Unknown config key: 'nonexistent_key_xyz'"),
        ):
            result = runner.invoke(app, ['config', 'get', 'nonexistent_key_xyz'])
            assert result.exit_code == 1
            assert 'Unknown config key' in result.output

    @staticmethod
    def test_config_set_unknown_key() -> None:
        """Config set with unknown key exits code 1."""
        with patch('synodic_client.operations.config.set_config', side_effect=KeyError('Unknown config key')):
            result = runner.invoke(app, ['config', 'set', 'bad_key', 'value'])
            assert result.exit_code == 1

    @staticmethod
    def test_config_list() -> None:
        """Config list renders key=value lines."""
        keys = {
            'theme': ConfigKeyInfo(name='theme', type_hint='str', current_value='dark'),
        }
        with patch('synodic_client.operations.config.list_config_keys', return_value=keys):
            result = runner.invoke(app, ['config', 'list'])
            assert result.exit_code == 0
            assert 'theme' in result.output
            assert 'dark' in result.output


# ---------------------------------------------------------------------------
# Update subcommands
# ---------------------------------------------------------------------------


class TestUpdateCli:
    """Tests for synodic-c update sub-commands."""

    @staticmethod
    def test_update_check_json() -> None:
        """Update check --json returns valid JSON."""
        check_result = UpdateCheckResult(available=True, current_version='1.0', version='2.0')
        with (
            patch('synodic_client.cli.context.get_services', return_value=(MagicMock(), None, None)),
            patch(
                'synodic_client.operations.update.check_self_update',
                new_callable=AsyncMock,
                return_value=check_result,
            ),
        ):
            result = runner.invoke(app, ['update', 'check', '--json'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data['available'] is True

    @staticmethod
    def test_update_download() -> None:
        """Update download renders the download result."""
        dl_result = DownloadResult(success=True, version='2.0')
        with (
            patch('synodic_client.cli.context.get_services', return_value=(MagicMock(), None, None)),
            patch(
                'synodic_client.operations.update.download_self_update',
                new_callable=AsyncMock,
                return_value=dl_result,
            ),
        ):
            result = runner.invoke(app, ['update', 'download'])
            assert result.exit_code == 0

    @staticmethod
    def test_update_apply() -> None:
        """Update apply calls apply_self_update."""
        with (
            patch('synodic_client.cli.context.get_services', return_value=(MagicMock(), None, None)),
            patch('synodic_client.operations.update.apply_self_update') as mock_apply,
        ):
            result = runner.invoke(app, ['update', 'apply'])
            assert result.exit_code == 0
            assert 'applied' in result.output.lower()
            mock_apply.assert_called_once()


# ---------------------------------------------------------------------------
# Debug subcommands
# ---------------------------------------------------------------------------


class TestDebugCli:
    """Tests for synodic-c debug sub-commands."""

    @staticmethod
    def test_debug_state_live() -> None:
        """Debug state --live prints JSON from IPC."""
        response = json.dumps({'app': {'version': '1.0.0'}})
        with (
            patch('synodic_client.application.instance.SingleInstance') as mock_si,
            patch('synodic_client.config.set_dev_mode'),
        ):
            mock_si.send_debug_command.return_value = response
            result = runner.invoke(app, ['debug', 'state', '--live'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data['app']['version'] == '1.0.0'

    @staticmethod
    def test_debug_actions_live() -> None:
        """Debug actions --live prints the actions dict."""
        response = json.dumps({'actions': {'check_update': 'Trigger check.'}})
        with (
            patch('synodic_client.application.instance.SingleInstance') as mock_si,
            patch('synodic_client.config.set_dev_mode'),
        ):
            mock_si.send_debug_command.return_value = response
            result = runner.invoke(app, ['debug', 'actions', '--live'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert 'actions' in data

    @staticmethod
    def test_debug_action_with_arg_live() -> None:
        """Debug action --live sends action:<name>:<arg>."""
        response = json.dumps({'ok': True})
        with (
            patch('synodic_client.application.instance.SingleInstance') as mock_si,
            patch('synodic_client.config.set_dev_mode'),
        ):
            mock_si.send_debug_command.return_value = response
            result = runner.invoke(app, ['debug', 'action', 'add_project', '/tmp/foo', '--live'])
            assert result.exit_code == 0
            mock_si.send_debug_command.assert_called_once_with('action:add_project:/tmp/foo')

    @staticmethod
    def test_debug_error_response_exits_1_live() -> None:
        """An error response from IPC causes exit code 1."""
        response = json.dumps({'error': 'not found'})
        with (
            patch('synodic_client.application.instance.SingleInstance') as mock_si,
            patch('synodic_client.config.set_dev_mode'),
        ):
            mock_si.send_debug_command.return_value = response
            result = runner.invoke(app, ['debug', 'state', '--live'])
            assert result.exit_code == 1

    @staticmethod
    def test_debug_actions_headless() -> None:
        """Debug actions (headless default) returns the actions dict."""
        with patch('synodic_client.config.set_dev_mode'):
            result = runner.invoke(app, ['debug', 'actions'])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert 'actions' in data
        assert 'project_status' in data['actions']

    @staticmethod
    def test_debug_state_headless() -> None:
        """Debug state (headless default) returns app and config sections."""
        with (
            patch('synodic_client.cli.context.get_services') as mock_services,
            patch('synodic_client.config.set_dev_mode'),
            patch('synodic_client.config.is_dev_mode', return_value=False),
        ):
            mock_client = MagicMock()
            mock_client.version = '1.2.3'
            mock_porringer = MagicMock()
            mock_porringer.cache.list_directories.return_value = []
            mock_config = MagicMock(spec=[])  # empty spec to make dataclasses.asdict work
            mock_services.return_value = (mock_client, mock_porringer, mock_config)

            # dataclasses.asdict requires a real dataclass; patch it
            with patch('synodic_client.cli.debug.dataclasses') as mock_dc:
                mock_dc.asdict.return_value = {'channel': 'stable'}
                result = runner.invoke(app, ['debug', 'state'])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data['app']['version'] == '1.2.3'
        assert data['app']['headless'] is True

    @staticmethod
    def test_debug_gui_only_action_headless() -> None:
        """GUI-only actions without --live return an error."""
        with patch('synodic_client.config.set_dev_mode'):
            result = runner.invoke(app, ['debug', 'action', 'show_main'])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert '--live' in data['error']


# ---------------------------------------------------------------------------
# Install subcommand
# ---------------------------------------------------------------------------


class TestInstallCli:
    """Tests for synodic-c install sub-command."""

    @staticmethod
    def test_install_success(tmp_path) -> None:
        """Install runs execute_install and prints summary."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{"version":"1","packages":{},"tools":{}}', encoding='utf-8')

        api = MagicMock()

        async def _empty_stream(*_a, **_kw):
            return
            yield  # async generator

        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, api, None)),
            patch(
                'synodic_client.operations.install.resolve_manifest_path',
                new_callable=AsyncMock,
                return_value=(manifest, None),
            ),
            patch('synodic_client.operations.install.execute_install', return_value=_empty_stream()),
            patch('synodic_client.operations.install.execute_post_sync', return_value=_empty_stream()),
        ):
            result = runner.invoke(app, ['install', str(manifest)])
            assert result.exit_code == 0

    @staticmethod
    def test_install_missing_manifest() -> None:
        """Install with missing manifest exits with code 1."""
        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)),
            patch(
                'synodic_client.operations.install.resolve_manifest_path',
                new_callable=AsyncMock,
                side_effect=FileNotFoundError('Manifest not found'),
            ),
        ):
            result = runner.invoke(app, ['install', '/nonexistent/porringer.json'])
            assert result.exit_code == 1
            assert 'not found' in result.output.lower()

    @staticmethod
    def test_install_json_output(tmp_path) -> None:
        """Install --json returns valid JSON."""
        manifest = tmp_path / 'porringer.json'
        manifest.write_text('{"version":"1","packages":{},"tools":{}}', encoding='utf-8')

        api = MagicMock()

        async def _empty_stream(*_a, **_kw):
            return
            yield

        with (
            patch('synodic_client.cli.context.get_services', return_value=(None, api, None)),
            patch(
                'synodic_client.operations.install.resolve_manifest_path',
                new_callable=AsyncMock,
                return_value=(manifest, None),
            ),
            patch('synodic_client.operations.install.execute_install', return_value=_empty_stream()),
            patch('synodic_client.operations.install.execute_post_sync', return_value=_empty_stream()),
        ):
            result = runner.invoke(app, ['install', str(manifest), '--json'])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert 'summary' in data

    @staticmethod
    def test_install_bad_strategy() -> None:
        """Invalid --strategy exits with code 1."""
        with patch('synodic_client.cli.context.get_services', return_value=(None, MagicMock(), None)):
            result = runner.invoke(app, ['install', '/tmp/m.json', '--strategy', 'BOGUS'])
            assert result.exit_code == 1
            assert 'Unknown strategy' in result.output
