"""Tests for the configuration resolution module."""

import json
from pathlib import Path
from unittest.mock import patch

from synodic_client.config import GlobalConfiguration, LocalConfiguration
from synodic_client.resolution import merge_config, resolve_config, resolve_update_config, update_and_resolve
from synodic_client.updater import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    GITHUB_REPO_URL,
    UpdateChannel,
)


class TestMergeConfig:
    """Tests for merge_config."""

    @staticmethod
    def test_returns_global_when_no_local() -> None:
        """Verify global config is returned unchanged when local is None."""
        global_cfg = GlobalConfiguration(update_source='/system', update_channel='stable')
        result = merge_config(global_cfg, None)
        assert result.update_source == '/system'
        assert result.update_channel == 'stable'

    @staticmethod
    def test_local_overrides_global() -> None:
        """Verify local fields override global values."""
        global_cfg = GlobalConfiguration(update_source='/system', update_channel='stable')
        local_cfg = LocalConfiguration(update_source='/local')
        result = merge_config(global_cfg, local_cfg)
        assert result.update_source == '/local'
        assert result.update_channel == 'stable'

    @staticmethod
    def test_local_none_fields_do_not_override() -> None:
        """Verify local None fields preserve global values."""
        global_cfg = GlobalConfiguration(update_source='/system', update_channel='stable')
        local_cfg = LocalConfiguration()
        result = merge_config(global_cfg, local_cfg)
        assert result.update_source == '/system'
        assert result.update_channel == 'stable'

    @staticmethod
    def test_full_override() -> None:
        """Verify all local fields override when set."""
        global_cfg = GlobalConfiguration(update_source='/system', update_channel='stable')
        local_cfg = LocalConfiguration(update_source='/local', update_channel='dev')
        result = merge_config(global_cfg, local_cfg)
        assert result.update_source == '/local'
        assert result.update_channel == 'dev'


class TestResolveConfig:
    """Tests for resolve_config (loads and merges both layers)."""

    @staticmethod
    def test_returns_defaults_when_no_files(tmp_path: Path) -> None:
        """Verify defaults when no config files exist."""
        with (
            patch('synodic_client.config._portable_config_path', return_value=None),
            patch('synodic_client.config.config_dir', return_value=tmp_path),
        ):
            config = resolve_config()
        assert config.update_source is None
        assert config.update_channel is None

    @staticmethod
    def test_loads_global_file(tmp_path: Path) -> None:
        """Verify loading a valid global config file."""
        data = {'update_source': 'https://example.com/releases', 'update_channel': 'dev'}
        (tmp_path / 'config.json').write_text(json.dumps(data), encoding='utf-8')

        with (
            patch('synodic_client.config._portable_config_path', return_value=None),
            patch('synodic_client.config.config_dir', return_value=tmp_path),
        ):
            config = resolve_config()

        assert config.update_source == 'https://example.com/releases'
        assert config.update_channel == 'dev'

    @staticmethod
    def test_returns_defaults_on_corrupt_json(tmp_path: Path) -> None:
        """Verify defaults when config file contains invalid JSON."""
        (tmp_path / 'config.json').write_text('not json', encoding='utf-8')

        with (
            patch('synodic_client.config._portable_config_path', return_value=None),
            patch('synodic_client.config.config_dir', return_value=tmp_path),
        ):
            config = resolve_config()

        assert config == GlobalConfiguration()

    @staticmethod
    def test_local_overrides_global_per_field(tmp_path: Path) -> None:
        """Verify local config overrides global on a per-field basis."""
        local_data = {'update_source': '/local/releases'}
        local_path = tmp_path / 'local' / 'config.json'
        local_path.parent.mkdir()
        local_path.write_text(json.dumps(local_data), encoding='utf-8')

        system_dir = tmp_path / 'system'
        system_dir.mkdir()
        system_data = {'update_source': '/system/releases', 'update_channel': 'stable'}
        (system_dir / 'config.json').write_text(json.dumps(system_data), encoding='utf-8')

        with (
            patch('synodic_client.config._portable_config_path', return_value=local_path),
            patch('synodic_client.config.config_dir', return_value=system_dir),
        ):
            config = resolve_config()

        assert config.update_source == '/local/releases'
        assert config.update_channel == 'stable'

    @staticmethod
    def test_falls_back_to_global_when_no_portable(tmp_path: Path) -> None:
        """Verify global config is used when no portable config exists."""
        system_data = {'update_source': '/system/releases', 'update_channel': 'stable'}
        (tmp_path / 'config.json').write_text(json.dumps(system_data), encoding='utf-8')

        with (
            patch('synodic_client.config._portable_config_path', return_value=None),
            patch('synodic_client.config.config_dir', return_value=tmp_path),
        ):
            config = resolve_config()

        assert config.update_source == '/system/releases'
        assert config.update_channel == 'stable'

    @staticmethod
    def test_falls_back_to_global_on_corrupt_portable(tmp_path: Path) -> None:
        """Verify global config is used when portable config is corrupt."""
        portable_path = tmp_path / 'portable' / 'config.json'
        portable_path.parent.mkdir()
        portable_path.write_text('not valid json', encoding='utf-8')

        system_dir = tmp_path / 'system'
        system_dir.mkdir()
        system_data = {'update_source': '/system/releases'}
        (system_dir / 'config.json').write_text(json.dumps(system_data), encoding='utf-8')

        with (
            patch('synodic_client.config._portable_config_path', return_value=portable_path),
            patch('synodic_client.config.config_dir', return_value=system_dir),
        ):
            config = resolve_config()

        assert config.update_source == '/system/releases'

    @staticmethod
    def test_portable_takes_precedence(tmp_path: Path) -> None:
        """Verify portable config values override system config."""
        portable_data = {'update_source': '/portable/releases', 'update_channel': 'dev'}
        portable_path = tmp_path / 'config.json'
        portable_path.write_text(json.dumps(portable_data), encoding='utf-8')

        system_dir = tmp_path / 'system'
        system_dir.mkdir()
        system_data = {'update_source': '/system/releases', 'update_channel': 'stable'}
        (system_dir / 'config.json').write_text(json.dumps(system_data), encoding='utf-8')

        with (
            patch('synodic_client.config._portable_config_path', return_value=portable_path),
            patch('synodic_client.config.config_dir', return_value=system_dir),
        ):
            config = resolve_config()

        assert config.update_source == '/portable/releases'
        assert config.update_channel == 'dev'


class TestResolveUpdateConfig:
    """Tests for resolve_update_config."""

    @staticmethod
    def test_dev_channel_from_config() -> None:
        """Verify dev channel is set from config."""
        config = GlobalConfiguration(update_channel='dev')
        result = resolve_update_config(config)
        assert result.channel == UpdateChannel.DEVELOPMENT

    @staticmethod
    def test_stable_channel_from_config() -> None:
        """Verify stable channel is set from config."""
        config = GlobalConfiguration(update_channel='stable')
        result = resolve_update_config(config)
        assert result.channel == UpdateChannel.STABLE

    @staticmethod
    def test_default_channel_unfrozen() -> None:
        """Verify default channel is DEVELOPMENT when not frozen."""
        config = GlobalConfiguration()
        with patch('synodic_client.resolution.sys') as mock_sys:
            del mock_sys.frozen  # Ensure frozen is not set
            result = resolve_update_config(config)
        assert result.channel == UpdateChannel.DEVELOPMENT

    @staticmethod
    def test_custom_source() -> None:
        """Verify custom update source is used."""
        config = GlobalConfiguration(update_source='https://custom.example.com')
        result = resolve_update_config(config)
        assert result.repo_url == 'https://custom.example.com'

    @staticmethod
    def test_default_source() -> None:
        """Verify default GITHUB_REPO_URL is used when source is None."""
        config = GlobalConfiguration()
        result = resolve_update_config(config)
        assert result.repo_url == GITHUB_REPO_URL

    @staticmethod
    def test_default_auto_update_interval() -> None:
        """Verify default auto-update interval in minutes."""
        config = GlobalConfiguration()
        result = resolve_update_config(config)
        assert result.auto_update_interval_minutes == DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_custom_auto_update_interval() -> None:
        """Verify custom auto-update interval is passed through."""
        custom = DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES * 2
        config = GlobalConfiguration(auto_update_interval_minutes=custom)
        result = resolve_update_config(config)
        assert result.auto_update_interval_minutes == custom

    @staticmethod
    def test_default_tool_update_interval() -> None:
        """Verify default tool update interval in minutes."""
        config = GlobalConfiguration()
        result = resolve_update_config(config)
        assert result.tool_update_interval_minutes == DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_custom_tool_update_interval() -> None:
        """Verify custom tool update interval is passed through."""
        custom = DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES * 2
        config = GlobalConfiguration(tool_update_interval_minutes=custom)
        result = resolve_update_config(config)
        assert result.tool_update_interval_minutes == custom

    @staticmethod
    def test_disabled_intervals() -> None:
        """Verify zero disables both intervals."""
        config = GlobalConfiguration(auto_update_interval_minutes=0, tool_update_interval_minutes=0)
        result = resolve_update_config(config)
        assert result.auto_update_interval_minutes == 0
        assert result.tool_update_interval_minutes == 0


class TestUpdateAndResolve:
    """Tests for update_and_resolve."""

    @staticmethod
    def test_saves_and_resolves(tmp_path: Path) -> None:
        """Verify config is saved and an UpdateConfig is returned."""
        config = GlobalConfiguration(update_source='/my/source', update_channel='dev')

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            result = update_and_resolve(config)

        assert result.channel == UpdateChannel.DEVELOPMENT
        assert result.repo_url == '/my/source'

        # Verify file was saved
        saved = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
        assert saved['update_source'] == '/my/source'
        assert saved['update_channel'] == 'dev'
