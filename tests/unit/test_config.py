"""Tests for the persistent configuration module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from synodic_client.config import (
    BuildConfig,
    UserConfig,
    config_dir,
    load_user_config,
    save_user_config,
    set_dev_mode,
)


class TestBuildConfig:
    """Tests for the BuildConfig model."""

    @staticmethod
    def test_defaults() -> None:
        """Verify default values for a fresh config."""
        config = BuildConfig()
        assert config.update_source is None
        assert config.update_channel is None

    @staticmethod
    def test_with_values() -> None:
        """Verify config accepts explicit values."""
        config = BuildConfig(update_source='/path/to/releases', update_channel='dev')
        assert config.update_source == '/path/to/releases'
        assert config.update_channel == 'dev'


class TestUserConfig:
    """Tests for the UserConfig model."""

    @staticmethod
    def test_defaults() -> None:
        """Verify default values for a fresh config."""
        config = UserConfig()
        assert config.update_source is None
        assert config.update_channel is None
        assert config.auto_update_interval_minutes is None
        assert config.tool_update_interval_minutes is None
        assert config.plugin_auto_update is None
        assert config.prerelease_packages is None
        assert config.auto_apply is None
        assert config.auto_start is None
        assert config.debug_logging is None

    @staticmethod
    def test_prerelease_packages_round_trip() -> None:
        """Verify prerelease_packages survives JSON round-trip."""
        packages = {'/some/path': ['alpha', 'beta'], 'https://example.com/manifest.json': ['gamma']}
        original = UserConfig(prerelease_packages=packages)
        data = json.loads(original.model_dump_json())
        restored = UserConfig.model_validate(data)
        assert restored.prerelease_packages == packages

    @staticmethod
    def test_plugin_auto_update_round_trip() -> None:
        """Verify plugin_auto_update survives JSON round-trip."""
        mapping = {'pipx': False, 'pip': True}
        original = UserConfig(plugin_auto_update=mapping)
        data = json.loads(original.model_dump_json())
        restored = UserConfig.model_validate(data)
        assert restored.plugin_auto_update == mapping

    @staticmethod
    def test_plugin_auto_update_nested_dict_round_trip() -> None:
        """Verify nested per-package dict survives JSON round-trip."""
        mapping: dict[str, bool | dict[str, bool]] = {
            'uv': {'cppython': True, 'ruff': False},
            'pip': False,
        }
        original = UserConfig(plugin_auto_update=mapping)
        data = json.loads(original.model_dump_json())
        restored = UserConfig.model_validate(data)
        assert restored.plugin_auto_update == mapping

    @staticmethod
    def test_auto_start_round_trip() -> None:
        """Verify auto_start survives JSON round-trip."""
        for value in (True, False, None):
            original = UserConfig(auto_start=value)
            data = json.loads(original.model_dump_json())
            restored = UserConfig.model_validate(data)
            assert restored.auto_start is value

    @staticmethod
    def test_json_round_trip() -> None:
        """Verify config can round-trip through JSON."""
        original = UserConfig(update_source='https://example.com', update_channel='stable')
        data = json.loads(original.model_dump_json())
        restored = UserConfig.model_validate(data)
        assert restored == original

    @staticmethod
    def test_extra_fields_ignored() -> None:
        """Verify unrecognized fields do not cause errors."""
        data = {'update_source': None, 'update_channel': None, 'unknown_field': 42}
        config = UserConfig.model_validate(data)
        assert config.update_source is None


class TestConfigDir:
    """Tests for the config_dir helper."""

    @staticmethod
    @pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows only')
    def test_windows_uses_localappdata() -> None:
        """Verify config dir uses LOCALAPPDATA on Windows."""
        with patch.dict('os.environ', {'LOCALAPPDATA': 'C:\\Users\\Test\\AppData\\Local'}):
            result = config_dir()
        assert result == Path('C:\\Users\\Test\\AppData\\Local\\Synodic')

    @staticmethod
    @pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows only')
    def test_windows_fallback_without_env() -> None:
        """Verify fallback when LOCALAPPDATA is not set."""
        with patch.dict('os.environ', {'LOCALAPPDATA': ''}):
            result = config_dir()
        # Should still produce a path ending in Synodic
        assert result.name == 'Synodic'

    @staticmethod
    @pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows only')
    def test_dev_mode_uses_separate_dir() -> None:
        """Verify config dir is namespaced when dev mode is active."""
        set_dev_mode(True)
        try:
            with patch.dict('os.environ', {'LOCALAPPDATA': 'C:\\Users\\Test\\AppData\\Local'}):
                result = config_dir()
            assert result == Path('C:\\Users\\Test\\AppData\\Local\\Synodic-Dev')
        finally:
            set_dev_mode(False)


class TestSaveUserConfig:
    """Tests for save_user_config."""

    @staticmethod
    def test_creates_file(tmp_path: Path) -> None:
        """Verify config is saved to disk."""
        config = UserConfig(update_source='/my/releases', update_channel='stable')

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            save_user_config(config)

        saved_path = tmp_path / 'config.json'
        assert saved_path.exists()

        data = json.loads(saved_path.read_text(encoding='utf-8'))
        assert data['update_source'] == '/my/releases'
        assert data['update_channel'] == 'stable'

    @staticmethod
    def test_saves_all_fields(tmp_path: Path) -> None:
        """Verify save_user_config writes all fields (no sparse serialization)."""
        config = UserConfig(update_channel='dev')

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            save_user_config(config)

        data = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
        # All fields should be present, not just user-set ones
        assert data['update_channel'] == 'dev'
        assert 'update_source' in data
        assert 'auto_update_interval_minutes' in data

    @staticmethod
    def test_creates_directory(tmp_path: Path) -> None:
        """Verify save_user_config creates the directory if missing."""
        nested = tmp_path / 'nested' / 'dir'
        config = UserConfig()

        with patch('synodic_client.config.config_dir', return_value=nested):
            save_user_config(config)

        assert (nested / 'config.json').exists()

    @staticmethod
    def test_overwrites_existing(tmp_path: Path) -> None:
        """Verify save_user_config overwrites an existing file."""
        config_path = tmp_path / 'config.json'
        config_path.write_text('{}', encoding='utf-8')

        config = UserConfig(update_source='http://new-source')

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            save_user_config(config)

        data = json.loads(config_path.read_text(encoding='utf-8'))
        assert data['update_source'] == 'http://new-source'

    @staticmethod
    def test_save_load_round_trip(tmp_path: Path) -> None:
        """Verify saved config can be loaded back identically."""
        original = UserConfig(update_channel='dev', auto_start=False)

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            save_user_config(original)

        data = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
        loaded = UserConfig.model_validate(data)
        assert loaded.update_channel == 'dev'
        assert loaded.auto_start is False
        assert loaded.update_source is None


class TestUserConfigRecovery:
    """Tests for the wrap validator that recovers invalid fields."""

    @staticmethod
    def test_single_corrupt_field_preserves_others() -> None:
        """One invalid field is discarded; all other fields survive."""
        data = {
            'update_channel': 'dev',
            'auto_start': False,
            'auto_update_interval_minutes': 'not_an_int',  # corrupt
        }
        config = UserConfig.model_validate(data)
        assert config.update_channel == 'dev'
        assert config.auto_start is False
        assert config.auto_update_interval_minutes is None  # reset to default

    @staticmethod
    def test_multiple_corrupt_fields() -> None:
        """Multiple invalid fields are discarded; valid fields survive."""
        data = {
            'update_channel': 'stable',
            'auto_update_interval_minutes': 'bad',
            'auto_apply': 'not_a_bool',
            'debug_logging': 42,  # int coerces to bool in Pydantic — this is valid
            'auto_start': False,
        }
        config = UserConfig.model_validate(data)
        assert config.update_channel == 'stable'
        assert config.auto_start is False
        # The corrupt fields revert to defaults
        assert config.auto_update_interval_minutes is None
        assert config.auto_apply is None

    @staticmethod
    def test_all_fields_corrupt() -> None:
        """When every known field is invalid, result is equivalent to UserConfig()."""
        data = {
            'update_source': 123,  # str field, int won't coerce
            'update_channel': [],
            'auto_update_interval_minutes': 'bad',
            'tool_update_interval_minutes': 'bad',
            'auto_apply': 'nope',
            'auto_start': 'nope',
            'debug_logging': 'nope',
            'plugin_auto_update': 'bad',
            'prerelease_packages': 42,
            'last_client_update': [],
            'last_tool_updates': 'bad',
        }
        config = UserConfig.model_validate(data)
        assert config == UserConfig()

    @staticmethod
    def test_valid_data_unchanged() -> None:
        """Fully valid data passes through the wrap validator without modification."""
        data = {
            'update_channel': 'dev',
            'auto_start': True,
            'auto_update_interval_minutes': 10,
        }
        expected_interval = 10
        config = UserConfig.model_validate(data)
        assert config.update_channel == 'dev'
        assert config.auto_start is True
        assert config.auto_update_interval_minutes == expected_interval


class TestLoadUserConfigRecovery:
    """Integration tests: load_user_config with corrupt files on disk."""

    @staticmethod
    def test_corrupt_field_recovered_from_disk(tmp_path: Path) -> None:
        """A config file with one bad field loads with that field reset to default."""
        config_data = {
            'update_channel': 'dev',
            'auto_start': False,
            'auto_update_interval_minutes': 'not_a_number',
        }
        (tmp_path / 'config.json').write_text(json.dumps(config_data), encoding='utf-8')

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            config = load_user_config()

        assert config.update_channel == 'dev'
        assert config.auto_start is False
        assert config.auto_update_interval_minutes is None

    @staticmethod
    def test_invalid_json_returns_defaults(tmp_path: Path) -> None:
        """Completely invalid JSON returns a default UserConfig."""
        (tmp_path / 'config.json').write_text('{{not valid json', encoding='utf-8')

        with patch('synodic_client.config.config_dir', return_value=tmp_path):
            config = load_user_config()

        assert config == UserConfig()
