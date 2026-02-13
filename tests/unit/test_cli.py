"""Tests for the CLI entry point."""

from unittest.mock import patch

from typer.testing import CliRunner

from synodic_client.cli import app

runner = CliRunner()


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
        assert 'synodic://' in result.output.lower() or 'uri' in result.output.lower()

    @staticmethod
    def test_launches_application_without_uri() -> None:
        """Verify invoking with no args calls application(uri=None, dev_mode=False)."""
        with patch('synodic_client.cli.application') as mock_app:
            result = runner.invoke(app, [])
            assert result.exit_code == 0
            mock_app.assert_called_once_with(uri=None, dev_mode=False)

    @staticmethod
    def test_launches_application_with_uri() -> None:
        """Verify invoking with a URI passes it to application()."""
        test_uri = 'synodic://install?manifest=https://example.com/foo.json'
        with patch('synodic_client.cli.application') as mock_app:
            result = runner.invoke(app, [test_uri])
            assert result.exit_code == 0
            mock_app.assert_called_once_with(uri=test_uri, dev_mode=False)

    @staticmethod
    def test_launches_application_with_dev_flag() -> None:
        """Verify --dev flag sets dev_mode=True."""
        with patch('synodic_client.cli.application') as mock_app:
            result = runner.invoke(app, ['--dev'])
            assert result.exit_code == 0
            mock_app.assert_called_once_with(uri=None, dev_mode=True)
