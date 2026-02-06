"""Tests that run across all example directories.

These validate client-level invariants — not porringer manifest semantics.
"""

import re
from pathlib import Path

from synodic_client.application.qt import find_uri, parse_uri

_URI_PATTERN = re.compile(r'synodic://\S+')


def _extract_uris_from_file(path: Path) -> list[str]:
    """Extract all ``synodic://`` URIs from a text file."""
    text = path.read_text(encoding='utf-8')
    return _URI_PATTERN.findall(text)


def _collect_uris(directory: Path) -> list[str]:
    """Collect every ``synodic://`` URI found in any text file in *directory*."""
    uris: list[str] = []
    for child in directory.iterdir():
        if child.is_file() and child.suffix in {'.md', '.toml', '.json', '.txt'}:
            uris.extend(_extract_uris_from_file(child))
    return uris


class TestExampleStructure:
    """Validate the structure of each example directory."""

    @staticmethod
    def test_has_readme(example_dir: Path) -> None:
        """Every example must include a README."""
        assert (example_dir / 'README.md').exists(), f'{example_dir.name}/ is missing a README.md'


class TestExampleUris:
    """Validate any ``synodic://`` URIs embedded in example files."""

    @staticmethod
    def test_embedded_uris_are_parseable(example_dir: Path) -> None:
        """Every embedded synodic:// URI must be parseable by the client."""
        uris = _collect_uris(example_dir)

        for uri in uris:
            parsed = parse_uri(uri)
            assert 'action' in parsed, f'URI missing action: {uri}'
            assert parsed['action'], f'URI has empty action: {uri}'

    @staticmethod
    def test_find_uri_detects_embedded(example_dir: Path) -> None:
        """Embedded URIs should be discoverable by find_uri."""
        uris = _collect_uris(example_dir)

        for uri in uris:
            assert find_uri([uri]) == uri, f'find_uri failed to detect: {uri}'
