"""Tests for operations.config module."""

import dataclasses
from unittest.mock import patch

import pytest

from synodic_client.operations.config import get_config, list_config_keys, set_config
from synodic_client.operations.schema import ConfigKeyInfo


class TestGetConfig:
    """Tests for get_config()."""

    @staticmethod
    def test_returns_resolved_config() -> None:
        """get_config returns the result of resolve_config()."""
        with patch('synodic_client.operations.config.resolve_config') as mock:
            sentinel = object()
            mock.return_value = sentinel
            assert get_config() is sentinel


class TestSetConfig:
    """Tests for set_config()."""

    @staticmethod
    def test_unknown_key_raises() -> None:
        """Raises KeyError for an invalid config key."""
        with pytest.raises(KeyError, match='Unknown config key'):
            set_config('nonexistent_key_xyz', 'value')

    @staticmethod
    def test_delegates_to_update_user_config() -> None:
        """Calls update_user_config with the correct kwargs."""
        with patch('synodic_client.operations.config.update_user_config') as mock:
            mock_config = object()
            mock.return_value = mock_config
            # Use a known field from ResolvedConfig
            from synodic_client.schema import ResolvedConfig  # noqa: PLC0415

            field_names = [f.name for f in dataclasses.fields(ResolvedConfig)]
            if field_names:
                key = field_names[0]
                result = set_config(key, 'test_value')
                mock.assert_called_once_with(**{key: 'test_value'})
                assert result is mock_config


class TestListConfigKeys:
    """Tests for list_config_keys()."""

    @staticmethod
    def test_returns_all_fields() -> None:
        """Returns a ConfigKeyInfo entry for each ResolvedConfig field."""
        from synodic_client.schema import ResolvedConfig  # noqa: PLC0415

        with patch('synodic_client.operations.config.resolve_config') as mock:
            mock.return_value = ResolvedConfig(
                update_source=None,
                update_channel='stable',
                auto_update_interval_minutes=60,
                tool_update_interval_minutes=60,
                plugin_auto_update=None,
                prerelease_packages=None,
                auto_apply=False,
                auto_start=False,
                debug_logging=False,
                last_client_update=None,
                last_tool_updates=None,
            )
            # Override: use a fresh resolve to build the keys dict
            keys = list_config_keys()
            expected_fields = {f.name for f in dataclasses.fields(ResolvedConfig)}
            assert set(keys.keys()) == expected_fields
            for info in keys.values():
                assert isinstance(info, ConfigKeyInfo)
