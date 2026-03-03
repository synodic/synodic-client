r"""Windows auto-startup registration via the registry.

Manages a value under ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
so the application launches automatically when the user logs in.

Windows also maintains a parallel
``HKCU\...\Explorer\StartupApproved\Run`` key where each entry is a
12-byte ``REG_BINARY`` value.  Byte 0 controls the enabled state:

* ``0x02`` — **enabled** (Windows will honour the ``Run`` entry).
* ``0x03`` — **disabled** (entry hidden from startup by Task Manager /
  Settings → Startup Apps).

When registering or removing auto-startup we synchronise *both* keys
so that a user toggling the setting in-app overrides any prior
Task-Manager disable.

Other platforms are stubbed with no-op implementations, matching the
approach in :mod:`synodic_client.protocol`.
"""

import logging
import sys

logger = logging.getLogger(__name__)

STARTUP_VALUE_NAME = 'SynodicClient'
"""Registry value name used in the ``Run`` key."""

RUN_KEY_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'

STARTUP_APPROVED_KEY_PATH = r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
"""Registry key where Windows stores per-entry enabled/disabled flags."""

# 12-byte REG_BINARY payloads for the StartupApproved value.
_APPROVED_ENABLED: bytes = b'\x02' + b'\x00' * 11
_APPROVED_DISABLED_BYTE: int = 0x03


if sys.platform == 'win32':
    import winreg

    def register_startup(exe_path: str) -> None:
        r"""Register the application to start automatically on login.

        Writes a value to ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
        pointing to *exe_path* **and** writes an *enabled* flag to the
        corresponding ``StartupApproved\Run`` key so that a previous
        Task-Manager disable is overridden.

        Calling this repeatedly is safe and will update the path (useful
        after Velopack relocates the executable).

        Args:
            exe_path: Absolute path to the application executable.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            logger.info('Registered auto-startup -> %s', exe_path)
        except OSError:
            logger.exception('Failed to register auto-startup')

        # Ensure Windows considers the entry enabled even if the user
        # previously disabled it via Task Manager.
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_KEY_PATH) as key:
                winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_BINARY, _APPROVED_ENABLED)
            logger.debug('Wrote StartupApproved enabled flag')
        except OSError:
            logger.exception('Failed to write StartupApproved enabled flag')

    def remove_startup() -> None:
        """Remove the auto-startup registration.

        Removes both the ``Run`` value and any ``StartupApproved`` flag.
        Silently succeeds if the values do not exist.
        """
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            logger.info('Removed auto-startup registration')
        except FileNotFoundError:
            logger.debug('Auto-startup registration not found, nothing to remove')
        except OSError:
            logger.exception('Failed to remove auto-startup registration')

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_KEY_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            logger.debug('Removed StartupApproved flag')
        except FileNotFoundError:
            logger.debug('StartupApproved flag not found, nothing to remove')
        except OSError:
            logger.exception('Failed to remove StartupApproved flag')

    def is_startup_registered() -> bool:
        """Check whether auto-startup is both present **and** enabled.

        Returns ``True`` only when the ``Run`` value exists and Windows
        has not disabled it via ``StartupApproved\Run``.

        Returns:
            ``True`` if the application will auto-start on login.
        """
        # 1. Check the Run key exists at all.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
                winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
        except FileNotFoundError:
            return False
        except OSError:
            logger.exception('Failed to query auto-startup registration')
            return False

        # 2. Check the StartupApproved override.  If the key/value is
        #    absent the entry is considered enabled (Windows only writes
        #    this key when the user explicitly disables/enables via Task
        #    Manager or Settings).
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, STARTUP_APPROVED_KEY_PATH, 0, winreg.KEY_QUERY_VALUE
            ) as key:
                data, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
                if isinstance(data, bytes) and len(data) >= 1 and data[0] == _APPROVED_DISABLED_BYTE:
                    logger.debug('Auto-startup is disabled via StartupApproved')
                    return False
        except FileNotFoundError:
            # No approval override → treat as enabled.
            pass
        except OSError:
            logger.exception('Failed to query StartupApproved flag')

        return True

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
