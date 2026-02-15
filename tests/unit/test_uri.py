"""Tests for URI parsing in the qt application module."""

from synodic_client.application.uri import parse_uri


class TestParseUri:
    """Tests for parse_uri."""

    @staticmethod
    def test_parses_action_from_netloc() -> None:
        """Verify the action is extracted from the URI netloc."""
        result = parse_uri('synodic://install?manifest=https://example.com')
        assert result['action'] == 'install'

    @staticmethod
    def test_parses_query_parameters() -> None:
        """Verify query parameters are included in the result."""
        result = parse_uri('synodic://install?manifest=https://example.com/foo.json')
        assert result['manifest'] == ['https://example.com/foo.json']

    @staticmethod
    def test_parses_multiple_query_values() -> None:
        """Verify multiple values for the same key are collected into a list."""
        result = parse_uri('synodic://install?manifest=https://a.com/a.json&manifest=https://b.com/b.json')
        assert result['manifest'] == ['https://a.com/a.json', 'https://b.com/b.json']

    @staticmethod
    def test_action_only_uri() -> None:
        """Verify a URI with no query string returns just the action."""
        result = parse_uri('synodic://update')
        assert result == {'action': 'update'}

    @staticmethod
    def test_unknown_action() -> None:
        """Verify unknown actions are returned as-is."""
        result = parse_uri('synodic://unknown?foo=bar')
        assert result['action'] == 'unknown'
        assert result['foo'] == ['bar']
