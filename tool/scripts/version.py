"""Print project version in PEP 440 and SemVer formats.

Outputs ``version=<pep440>`` and ``installer-version=<semver>`` lines,
one per line.  In CI these can be appended directly to ``$GITHUB_OUTPUT``.

Usage examples:
    pdm run version
    pdm run python -m tool.scripts.version
"""

from synodic_client import __version__
from synodic_client.updater import pep440_to_semver


def main() -> None:
    """Entry point for the version script."""
    semver = pep440_to_semver(__version__)
    print(f'version={__version__}')
    print(f'installer-version={semver}')


if __name__ == '__main__':
    main()
