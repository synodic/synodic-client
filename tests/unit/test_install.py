"""Installation tests"""

from importlib.metadata import entry_points
from pathlib import Path

from packaging.version import Version

from synodic_client.client import Client


class TestInstall:
    """Install tests"""

    @staticmethod
    def test_version() -> None:
        """Verify that the imported package version can be read"""
        client = Client()

        # The test should be running inside a PDM virtual environment which means that
        #   the package has the version metadata
        version = client.version

        assert version >= Version('0.0.0')

    @staticmethod
    def test_package() -> None:
        """Verify that the proper package is selected"""
        client = Client()
        assert client.package == 'synodic_client'

    @staticmethod
    def test_entrypoints() -> None:
        """Verify the entrypoints can be loaded"""
        entries = entry_points(name='synodic-client')
        for entry in entries:
            assert entry.load()

    @staticmethod
    def test_icon_exists() -> None:
        """Verifies that the icon file used exists."""
        client = Client()
        with client.resource(Client.icon) as icon_path:
            assert icon_path.exists()

    @staticmethod
    def test_data() -> None:
        """Verify that all the files in 'static' can be read"""
        client = Client()

        directory = Path('data')

        assert directory.is_dir()

        paths = directory.rglob('*')

        for file in paths:
            file_string = str(file.name)
            with client.resource(file_string) as path:
                assert path.absolute() == file.absolute()
