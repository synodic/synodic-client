r"""URI protocol handler registration for the ``synodic://`` scheme.

On Windows this writes registry keys under ``HKCU\Software\Classes\synodic``
so that clicking a ``synodic://`` link in a browser or file manager launches the
Synodic Client with the URI as an argument.

Other platforms are stubbed with no-op implementations.
"""

import logging
import sys

if sys.platform == 'win32':
    import winreg

logger = logging.getLogger(__name__)

PROTOCOL_NAME = 'synodic'
_PROTOCOL_DESCRIPTION = 'Synodic Client Protocol'


def register_protocol(exe_path: str) -> None:
    """Register the ``synodic://`` URI protocol handler.

    Args:
        exe_path: Absolute path to the application executable.
    """
    if sys.platform != 'win32':
        logger.warning('Protocol registration is only supported on Windows (current: %s)', sys.platform)
        return

    key_path = f'Software\\Classes\\{PROTOCOL_NAME}'

    try:
        # Create the protocol key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, _PROTOCOL_DESCRIPTION)
            winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')

        # Create the shell\open\command key with the exe path
        command_path = f'{key_path}\\shell\\open\\command'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as key:
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, f'"{exe_path}" "%1"')

        logger.info('Registered synodic:// protocol handler -> %s', exe_path)
    except OSError:
        logger.exception('Failed to register synodic:// protocol handler')


def remove_protocol() -> None:
    """Remove the ``synodic://`` URI protocol handler registration."""
    if sys.platform != 'win32':
        logger.warning('Protocol removal is only supported on Windows (current: %s)', sys.platform)
        return

    key_path = f'Software\\Classes\\{PROTOCOL_NAME}'

    try:
        _delete_key_recursive(winreg.HKEY_CURRENT_USER, key_path)
        logger.info('Removed synodic:// protocol handler registration')
    except FileNotFoundError:
        logger.debug('Protocol handler registration not found, nothing to remove')
    except OSError:
        logger.exception('Failed to remove synodic:// protocol handler')


def _delete_key_recursive(root: int, key_path: str) -> None:
    """Recursively delete a registry key and all its subkeys.

    Args:
        root: Registry root (e.g. ``winreg.HKEY_CURRENT_USER``).
        key_path: Path to the key to delete.
    """
    with winreg.OpenKey(root, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
        # Enumerate and delete all subkeys first
        while True:
            try:
                subkey_name = winreg.EnumKey(key, 0)
                _delete_key_recursive(root, f'{key_path}\\{subkey_name}')
            except OSError:
                break

    winreg.DeleteKey(root, key_path)
