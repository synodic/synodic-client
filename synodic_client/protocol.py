r"""URI protocol handler registration for the ``synodic://`` scheme.

On Windows this writes registry keys under ``HKCU\Software\Classes\synodic``
so that clicking a ``synodic://`` link in a browser or file manager launches the
Synodic Client with the URI as an argument.

Other platforms are stubbed with no-op implementations.
"""

import logging
import sys

logger = logging.getLogger(__name__)

PROTOCOL_NAME = 'synodic'
_PROTOCOL_DESCRIPTION = 'Synodic Client Protocol'


if sys.platform == 'win32':
    import ctypes
    import winreg

    # Bind RegDeleteTreeW for recursive registry key deletion in a single call.
    _reg_delete_tree = ctypes.windll.advapi32.RegDeleteTreeW
    _reg_delete_tree.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _reg_delete_tree.restype = ctypes.c_long

    _ERROR_FILE_NOT_FOUND = 2

    def register_protocol(exe_path: str) -> None:
        """Register the ``synodic://`` URI protocol handler.

        Args:
            exe_path: Absolute path to the application executable.
        """
        key_path = f'Software\\Classes\\{PROTOCOL_NAME}'

        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, '', 0, winreg.REG_SZ, _PROTOCOL_DESCRIPTION)
                winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')

            command_path = f'{key_path}\\shell\\open\\command'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as key:
                winreg.SetValueEx(key, '', 0, winreg.REG_SZ, f'"{exe_path}" "%1"')

            logger.info('Registered synodic:// protocol handler -> %s', exe_path)
        except OSError:
            logger.exception('Failed to register synodic:// protocol handler')

    def remove_protocol() -> None:
        """Remove the ``synodic://`` URI protocol handler registration."""
        key_path = f'Software\\Classes\\{PROTOCOL_NAME}'

        result = _reg_delete_tree(winreg.HKEY_CURRENT_USER, key_path)
        if result == 0:
            logger.info('Removed synodic:// protocol handler registration')
        elif result == _ERROR_FILE_NOT_FOUND:
            logger.debug('Protocol handler registration not found, nothing to remove')
        else:
            logger.error('Failed to remove synodic:// protocol handler (error code %d)', result)

else:

    def register_protocol(exe_path: str) -> None:
        """Register the ``synodic://`` URI protocol handler (no-op on non-Windows).

        Args:
            exe_path: Absolute path to the application executable.
        """
        logger.warning('Protocol registration is only supported on Windows (current: %s)', sys.platform)

    def remove_protocol() -> None:
        """Remove the ``synodic://`` URI protocol handler registration (no-op on non-Windows)."""
        logger.warning('Protocol removal is only supported on Windows (current: %s)', sys.platform)
