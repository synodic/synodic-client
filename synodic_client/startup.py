r"""Windows auto-startup registration via the registry.

Manages a value under ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
so the application launches automatically when the user logs in.

Other platforms are stubbed with no-op implementations, matching the
approach in :mod:`synodic_client.protocol`.
"""

import logging
import sys

logger = logging.getLogger(__name__)

STARTUP_VALUE_NAME = 'SynodicClient'
"""Registry value name used in the ``Run`` key."""

_RUN_KEY_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'


if sys.platform == 'win32':
    import winreg

    def register_startup(exe_path: str) -> None:
        """Register the application to start automatically on login.

        Writes a value to ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
        pointing to *exe_path*.  Calling this repeatedly is safe and will
        update the path (useful after Velopack relocates the executable).

        Args:
            exe_path: Absolute path to the application executable.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            logger.info('Registered auto-startup -> %s', exe_path)
        except OSError:
            logger.exception('Failed to register auto-startup')

    def remove_startup() -> None:
        """Remove the auto-startup registration.

        Silently succeeds if the value does not exist.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            logger.info('Removed auto-startup registration')
        except FileNotFoundError:
            logger.debug('Auto-startup registration not found, nothing to remove')
        except OSError:
            logger.exception('Failed to remove auto-startup registration')

    def is_startup_registered() -> bool:
        """Check whether the auto-startup value is currently present.

        Returns:
            ``True`` if the ``Run`` key contains the startup value.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
                winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
                return True
        except FileNotFoundError:
            return False
        except OSError:
            logger.exception('Failed to query auto-startup registration')
            return False

else:

    def register_startup(exe_path: str) -> None:
        """Register auto-startup (no-op on non-Windows).

        Args:
            exe_path: Absolute path to the application executable.
        """
        logger.warning('Auto-startup registration is only supported on Windows (current: %s)', sys.platform)

    def remove_startup() -> None:
        """Remove auto-startup registration (no-op on non-Windows)."""
        logger.warning('Auto-startup removal is only supported on Windows (current: %s)', sys.platform)

    def is_startup_registered() -> bool:
        """Check auto-startup registration (always ``False`` on non-Windows).

        Returns:
            ``False``.
        """
        return False
