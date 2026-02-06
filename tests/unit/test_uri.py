"""Tests for URI finding in the qt application module."""

from synodic_client.application.qt import find_uri


class TestFindUri:
    """Tests for find_uri."""

    @staticmethod
    def test_finds_synodic_uri() -> None:
        """Verify a synodic:// URI is found in args."""
        args = ['--flag', 'synodic://install?manifest=https://example.com']
        assert find_uri(args) == 'synodic://install?manifest=https://example.com'

    @staticmethod
    def test_returns_none_when_absent() -> None:
        """Verify None is returned when no URI is present."""
        args = ['--verbose', 'some-file.txt']
        assert find_uri(args) is None

    @staticmethod
    def test_empty_args() -> None:
        """Verify None for empty args list."""
        assert find_uri([]) is None

    @staticmethod
    def test_case_insensitive() -> None:
        """Verify scheme matching is case-insensitive."""
        args = ['SYNODIC://Install']
        assert find_uri(args) == 'SYNODIC://Install'

    @staticmethod
    def test_returns_first_uri() -> None:
        """Verify only the first URI is returned when multiple are present."""
        args = ['synodic://first', 'synodic://second']
        assert find_uri(args) == 'synodic://first'
