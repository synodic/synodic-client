"""Tests for the configuration resolution module."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from synodic_client.resolution import (
    ResolvedConfig,
    resolve_auto_update_scope,
    resolve_config,
    resolve_update_config,
    seed_user_config_from_build,
    update_user_config,
)
from synodic_client.schema import (
    DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
    DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
    GITHUB_REPO_URL,
    BuildConfig,
    UpdateChannel,
    UserConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolved(**overrides: Any) -> ResolvedConfig:
    """Create a ``ResolvedConfig`` with sensible defaults and optional overrides."""
    defaults: dict[str, Any] = {
        'update_source': None,
        'update_channel': 'stable',
        'auto_update_interval_minutes': DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES,
        'tool_update_interval_minutes': DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES,
        'plugin_auto_update': None,
        'prerelease_packages': None,
        'auto_apply': True,
        'auto_start': True,
        'debug_logging': False,
        'last_client_update': None,
        'last_tool_updates': None,
    }
    defaults.update(overrides)
    return ResolvedConfig(**defaults)


# ---------------------------------------------------------------------------
# seed_user_config_from_build
# ---------------------------------------------------------------------------


class TestSeedUserConfigFromBuild:
    """Tests for seed_user_config_from_build."""

    @staticmethod
    def test_no_build_config_is_noop(tmp_path: Path) -> None:
        """Verify nothing happens when there is no build config."""
        with (
            patch('synodic_client.resolution.load_build_config', return_value=None),
            patch('synodic_client.resolution.save_user_config') as mock_save,
        ):
            seed_user_config_from_build()
        mock_save.assert_not_called()

    @staticmethod
    def test_seeds_both_fields(tmp_path: Path) -> None:
        """Verify build config fields are seeded into user config."""
        build = BuildConfig(update_source='/local', update_channel='dev')
        user = UserConfig()  # all defaults

        with (
            patch('synodic_client.resolution.load_build_config', return_value=build),
            patch('synodic_client.resolution.load_user_config', return_value=user),
            patch('synodic_client.resolution.save_user_config') as mock_save,
        ):
            seed_user_config_from_build()

        mock_save.assert_called_once()
        saved = mock_save.call_args.args[0]
        assert saved.update_source == '/local'
        assert saved.update_channel == 'dev'

    @staticmethod
    def test_does_not_overwrite_user_values() -> None:
        """Verify user-customised values are not overwritten by build."""
        build = BuildConfig(update_source='/local', update_channel='dev')
        user = UserConfig(update_source='/user-source', update_channel='stable')

        with (
            patch('synodic_client.resolution.load_build_config', return_value=build),
            patch('synodic_client.resolution.load_user_config', return_value=user),
            patch('synodic_client.resolution.save_user_config') as mock_save,
        ):
            seed_user_config_from_build()

        # User values should be preserved — nothing to save
        mock_save.assert_not_called()

    @staticmethod
    def test_partial_seed() -> None:
        """Verify only missing fields are seeded."""
        build = BuildConfig(update_source='/local', update_channel='dev')
        user = UserConfig(update_channel='stable')  # channel set, source not

        with (
            patch('synodic_client.resolution.load_build_config', return_value=build),
            patch('synodic_client.resolution.load_user_config', return_value=user),
            patch('synodic_client.resolution.save_user_config') as mock_save,
        ):
            seed_user_config_from_build()

        mock_save.assert_called_once()
        saved = mock_save.call_args.args[0]
        assert saved.update_source == '/local'
        assert saved.update_channel == 'stable'  # user's value preserved


# ---------------------------------------------------------------------------
# resolve_config
# ---------------------------------------------------------------------------


class TestResolveConfig:
    """Tests for resolve_config (returns ResolvedConfig)."""

    @staticmethod
    def test_returns_defaults_when_no_files(tmp_path: Path) -> None:
        """Verify defaults when no config files exist."""
        with patch('synodic_client.resolution.load_user_config', return_value=UserConfig()):
            config = resolve_config()

        assert isinstance(config, ResolvedConfig)
        assert config.update_source is None
        assert config.auto_update_interval_minutes == DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_loads_user_values() -> None:
        """Verify user config values are reflected in resolved config."""
        user = UserConfig(update_source='https://example.com/releases', update_channel='dev')

        with patch('synodic_client.resolution.load_user_config', return_value=user):
            config = resolve_config()

        assert config.update_source == 'https://example.com/releases'
        assert config.update_channel == 'dev'

    @staticmethod
    def test_none_channel_resolves_to_default() -> None:
        """Verify None channel resolves based on frozen state."""
        user = UserConfig()  # update_channel is None

        with (
            patch('synodic_client.resolution.load_user_config', return_value=user),
            patch('synodic_client.resolution.sys') as mock_sys,
        ):
            del mock_sys.frozen  # Not frozen → dev
            config = resolve_config()

        assert config.update_channel == 'dev'

    @staticmethod
    def test_none_intervals_resolve_to_defaults() -> None:
        """Verify None intervals resolve to module defaults."""
        user = UserConfig()

        with patch('synodic_client.resolution.load_user_config', return_value=user):
            config = resolve_config()

        assert config.auto_update_interval_minutes == DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES
        assert config.tool_update_interval_minutes == DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_none_auto_start_resolves_to_true() -> None:
        """Verify None auto_start resolves to True."""
        user = UserConfig()

        with patch('synodic_client.resolution.load_user_config', return_value=user):
            config = resolve_config()

        assert config.auto_start is True


# ---------------------------------------------------------------------------
# update_user_config
# ---------------------------------------------------------------------------


class TestUpdateUserConfig:
    """Tests for update_user_config."""

    @staticmethod
    def test_returns_resolved_config(tmp_path: Path) -> None:
        """Verify update_user_config returns a ResolvedConfig."""
        user = UserConfig(update_channel='stable')

        with (
            patch('synodic_client.resolution.load_user_config', return_value=user),
            patch('synodic_client.resolution.save_user_config') as mock_save,
        ):
            result = update_user_config(update_channel='dev')

        assert isinstance(result, ResolvedConfig)
        assert result.update_channel == 'dev'
        mock_save.assert_called_once()

    @staticmethod
    def test_saves_changed_field() -> None:
        """Verify the changed field is persisted."""
        user = UserConfig(update_channel='stable')

        with (
            patch('synodic_client.resolution.load_user_config', return_value=user),
            patch('synodic_client.resolution.save_user_config') as mock_save,
        ):
            update_user_config(update_channel='dev')

        saved = mock_save.call_args.args[0]
        assert saved.update_channel == 'dev'


# ---------------------------------------------------------------------------
# resolve_auto_update_scope
# ---------------------------------------------------------------------------


class TestResolveAutoUpdateScope:
    """Tests for resolve_auto_update_scope."""

    @staticmethod
    def test_no_mapping_returns_none_pair() -> None:
        """Verify (None, None) when plugin_auto_update is unset."""
        config = _make_resolved()
        plugins, packages = resolve_auto_update_scope(config, ['pip', 'uv'])
        assert plugins is None
        assert packages is None

    @staticmethod
    def test_all_enabled_returns_none_pair() -> None:
        """Verify (None, None) when all entries are True."""
        config = _make_resolved(plugin_auto_update={'pip': True, 'uv': True})
        plugins, packages = resolve_auto_update_scope(config, ['pip', 'uv'])
        assert plugins is None
        assert packages is None

    @staticmethod
    def test_plugin_disabled() -> None:
        """Verify a disabled plugin is excluded."""
        config = _make_resolved(plugin_auto_update={'pip': False})
        plugins, packages = resolve_auto_update_scope(config, ['pip', 'uv'])
        assert plugins is not None
        assert 'pip' not in plugins
        assert 'uv' in plugins
        # No per-package filtering needed
        assert packages is None

    @staticmethod
    def test_nested_dict_filters_packages() -> None:
        """Verify nested dict creates a package allowlist."""
        config = _make_resolved(
            plugin_auto_update={'uv': {'ruff': True, 'mypy': False}},
        )
        plugins, packages = resolve_auto_update_scope(
            config,
            ['uv', 'pip'],
            manifest_packages={'uv': {'ruff', 'black'}},
        )
        # 'uv' is not disabled at plugin level
        assert plugins is None or 'uv' in plugins
        # Package allowlist: ruff = True (explicit), black = True (manifest default),
        # mypy = False (explicit) → only ruff and black
        assert packages is not None
        assert 'ruff' in packages
        assert 'black' in packages
        assert 'mypy' not in packages

    @staticmethod
    def test_mixed_entries() -> None:
        """Verify a mix of bool and dict entries."""
        config = _make_resolved(
            plugin_auto_update={
                'pip': False,
                'uv': {'ruff': True},
            },
        )
        plugins, packages = resolve_auto_update_scope(
            config,
            ['pip', 'uv', 'git'],
        )
        assert plugins is not None
        assert 'pip' not in plugins
        assert 'uv' in plugins
        assert 'git' in plugins
        # 'uv' has a nested dict → package filtering
        assert packages is not None
        assert 'ruff' in packages

    @staticmethod
    def test_composite_keys_ignored() -> None:
        """Runtime-scoped composite keys must not affect global auto-update."""
        config = _make_resolved(
            plugin_auto_update={
                'pip:3.12': False,
                'uv:3.11': {'ruff': False},
            },
        )
        plugins, packages = resolve_auto_update_scope(
            config,
            ['pip', 'uv'],
        )
        # Neither bare plugin should be disabled
        assert plugins is None
        # No per-package filtering from composite keys
        assert packages is None


# ---------------------------------------------------------------------------
# resolve_update_config
# ---------------------------------------------------------------------------


class TestResolveUpdateConfig:
    """Tests for resolve_update_config."""

    @staticmethod
    def test_dev_channel_from_config() -> None:
        """Verify dev channel is set from config."""
        config = _make_resolved(update_channel='dev')
        result = resolve_update_config(config)
        assert result.channel == UpdateChannel.DEVELOPMENT

    @staticmethod
    def test_stable_channel_from_config() -> None:
        """Verify stable channel is set from config."""
        config = _make_resolved(update_channel='stable')
        result = resolve_update_config(config)
        assert result.channel == UpdateChannel.STABLE

    @staticmethod
    def test_custom_source_non_github() -> None:
        """Verify non-GitHub custom source passes through unchanged."""
        config = _make_resolved(update_source='https://custom.example.com')
        result = resolve_update_config(config)
        assert result.repo_url == 'https://custom.example.com'

    @staticmethod
    def test_default_source_dev() -> None:
        """Verify default dev source uses GitHub download path with dev tag."""
        config = _make_resolved(update_channel='dev')
        result = resolve_update_config(config)
        assert result.repo_url == f'{GITHUB_REPO_URL}/releases/download/dev'

    @staticmethod
    def test_default_source_stable() -> None:
        """Verify default stable source uses GitHub latest download path."""
        config = _make_resolved(update_channel='stable')
        result = resolve_update_config(config)
        assert result.repo_url == f'{GITHUB_REPO_URL}/releases/latest/download'

    @staticmethod
    def test_default_auto_update_interval() -> None:
        """Verify default auto-update interval in minutes."""
        config = _make_resolved()
        result = resolve_update_config(config)
        assert result.auto_update_interval_minutes == DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_custom_auto_update_interval() -> None:
        """Verify custom auto-update interval is passed through."""
        custom = DEFAULT_AUTO_UPDATE_INTERVAL_MINUTES * 2
        config = _make_resolved(auto_update_interval_minutes=custom)
        result = resolve_update_config(config)
        assert result.auto_update_interval_minutes == custom

    @staticmethod
    def test_default_tool_update_interval() -> None:
        """Verify default tool update interval in minutes."""
        config = _make_resolved()
        result = resolve_update_config(config)
        assert result.tool_update_interval_minutes == DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES

    @staticmethod
    def test_custom_tool_update_interval() -> None:
        """Verify custom tool update interval is passed through."""
        custom = DEFAULT_TOOL_UPDATE_INTERVAL_MINUTES * 2
        config = _make_resolved(tool_update_interval_minutes=custom)
        result = resolve_update_config(config)
        assert result.tool_update_interval_minutes == custom

    @staticmethod
    def test_disabled_intervals() -> None:
        """Verify zero disables both intervals."""
        config = _make_resolved(auto_update_interval_minutes=0, tool_update_interval_minutes=0)
        result = resolve_update_config(config)
        assert result.auto_update_interval_minutes == 0
        assert result.tool_update_interval_minutes == 0
