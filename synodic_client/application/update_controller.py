"""Self-update orchestration controller.

Owns the full update lifecycle — check → download → apply — and the
periodic auto-update timer.  Extracted from :class:`TrayScreen` so
that tray, settings, and banner concerns are cleanly separated from
the update state-machine.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from synodic_client.application.screen.update_banner import UpdateBanner
from synodic_client.application.theme import (
    UPDATE_STATUS_AVAILABLE_STYLE,
    UPDATE_STATUS_ERROR_STYLE,
    UPDATE_STATUS_UP_TO_DATE_STYLE,
)
from synodic_client.application.workers import check_for_update, download_update
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_config,
    resolve_update_config,
    update_user_config,
)
from synodic_client.schema import UpdateInfo

if TYPE_CHECKING:
    from synodic_client.application.screen.settings import SettingsWindow
    from synodic_client.client import Client

logger = logging.getLogger(__name__)


class UpdateController:
    """Manages the self-update lifecycle: check → download → apply.

    Parameters
    ----------
    app:
        The running ``QApplication`` (needed for ``quit()`` on auto-apply).
    client:
        The Synodic Client service facade.
    banner:
        The in-app ``UpdateBanner`` widget.
    settings_window:
        The ``SettingsWindow`` (receives status text + colour).
    config:
        Optional pre-resolved configuration.  ``None`` resolves from disk.
    is_user_active:
        Predicate returning ``True`` when the user has a visible window.
        Auto-apply is deferred while active; checks still run normally.
    """

    def __init__(
        self,
        app: QApplication,
        client: Client,
        banner: UpdateBanner,
        *,
        settings_window: SettingsWindow,
        config: ResolvedConfig | None = None,
    ) -> None:
        """Initialise the controller and start the periodic timer.

        Args:
            app: The running ``QApplication``.
            client: The Synodic Client service facade.
            banner: The in-app ``UpdateBanner`` widget.
            settings_window: The settings window for status feedback.
            config: Optional pre-resolved configuration.
        """
        self._app = app
        self._client = client
        self._banner = banner
        self._settings_window = settings_window
        self._config = config
        self._is_user_active: Callable[[], bool] = lambda: False
        self._update_task: asyncio.Task[None] | None = None

        # Derive auto-apply preference from config
        resolved = self._resolve_config()
        self._auto_apply: bool = resolved.auto_apply

        # Periodic auto-update timer
        self._auto_update_timer: QTimer | None = None
        self._restart_auto_update_timer()

        # Wire banner signals
        self._banner.restart_requested.connect(self._apply_update)
        self._banner.retry_requested.connect(lambda: self.check_now(silent=True))

        # Wire settings check-updates button
        self._settings_window.check_updates_requested.connect(self._on_manual_check)
        self._settings_window.restart_requested.connect(self._apply_update)

    def set_user_active_predicate(self, predicate: Callable[[], bool]) -> None:
        """Set the predicate used to defer auto-apply when the user is active.

        Args:
            predicate: Returns ``True`` when the user has a visible window.
        """
        self._is_user_active = predicate

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _resolve_config(self) -> ResolvedConfig:
        """Return the injected config or resolve from disk."""
        if self._config is not None:
            return self._config
        return resolve_config()

    def _can_auto_apply(self) -> bool:
        """Return whether a downloaded update should be applied automatically.

        Auto-apply is suppressed when the user has a visible window so
        the application is never force-restarted during active use.
        """
        return self._auto_apply and not self._is_user_active()

    # ------------------------------------------------------------------
    # Timer management
    # ------------------------------------------------------------------

    def _restart_auto_update_timer(self) -> None:
        """Start (or restart) the periodic auto-update timer from config."""
        config = resolve_update_config(self._resolve_config())

        if self._auto_update_timer is not None:
            self._auto_update_timer.stop()

        interval = config.auto_update_interval_minutes
        if interval <= 0:
            logger.info('Automatic update checking is disabled')
            self._auto_update_timer = None
            return

        timer = QTimer()
        timer.setInterval(interval * 60 * 1000)
        timer.timeout.connect(self._on_auto_check)
        timer.start()
        logger.info('Automatic update checking enabled (every %d minute(s))', interval)
        self._auto_update_timer = timer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_now(self, *, silent: bool = False) -> None:
        """Trigger an update check.

        Args:
            silent: When ``True``, suppress the in-app error banner
                for failures and no-update results.
        """
        self._do_check(silent=silent)

    def on_settings_changed(self, config: ResolvedConfig) -> None:
        """React to a settings change — reinitialise the updater and timers.

        Also triggers an immediate (silent) check so the user gets
        feedback after switching channels.
        """
        self._config = config
        self._auto_apply = config.auto_apply
        self._reinitialize_updater(config)
        self.check_now(silent=True)

    # ------------------------------------------------------------------
    # Updater re-initialisation
    # ------------------------------------------------------------------

    def _reinitialize_updater(self, config: ResolvedConfig) -> None:
        """Re-derive update settings and restart the updater and timer."""
        update_cfg = resolve_update_config(config)
        self._client.initialize_updater(update_cfg)
        self._restart_auto_update_timer()
        logger.info(
            'Updater re-initialized (channel: %s, source: %s)',
            update_cfg.channel.name,
            update_cfg.repo_url,
        )

    # ------------------------------------------------------------------
    # Check flow
    # ------------------------------------------------------------------

    def _on_manual_check(self) -> None:
        """Handle manual check-for-updates (from settings button)."""
        self._do_check(silent=False)

    def _on_auto_check(self) -> None:
        """Handle automatic (periodic) check — silent.

        The check always runs so the settings window can show the
        latest status and the *last updated* timestamp stays current.
        Auto-apply is gated separately by :meth:`_can_auto_apply`.
        """
        self._do_check(silent=True)

    def _do_check(self, *, silent: bool) -> None:
        """Run an update check."""
        if self._client.updater is None:
            if not silent:
                self._banner.show_error('Updater is not initialized.')
            return

        # Show checking state in settings
        self._settings_window.set_checking()

        self._update_task = asyncio.create_task(self._async_check(silent=silent))

    async def _async_check(self, *, silent: bool) -> None:
        """Run the update check coroutine and route results."""
        logger.info('[DIAG] Self-update check starting (silent=%s)', silent)
        try:
            result = await check_for_update(self._client)
            self._on_check_finished(result, silent=silent)
            logger.info('[DIAG] Self-update check completed (silent=%s)', silent)
        except Exception as exc:
            logger.exception('Update check failed')
            self._on_check_error(str(exc), silent=silent)

    def _on_check_finished(self, result: UpdateInfo | None, *, silent: bool = False) -> None:
        """Route the update-check result."""
        self._settings_window.reset_check_updates_button()

        if result is None:
            self._settings_window.set_update_status('Check failed', UPDATE_STATUS_ERROR_STYLE)
            if not silent:
                self._banner.show_error('Failed to check for updates.')
            else:
                logger.warning('Automatic update check failed (no result)')
            return

        if result.error:
            self._settings_window.set_update_status('Check failed', UPDATE_STATUS_ERROR_STYLE)
            if not silent:
                self._banner.show_error(result.error)
            else:
                logger.warning('Automatic update check failed: %s', result.error)
            return

        if not result.available:
            self._settings_window.set_update_status('Up to date', UPDATE_STATUS_UP_TO_DATE_STYLE)
            if not silent:
                logger.info('No updates available (current: %s)', result.current_version)
            else:
                logger.debug('Automatic update check: no update available')
            return

        # Update available — show status and start download
        version = str(result.latest_version)
        self._settings_window.set_update_status(
            f'v{version} available',
            UPDATE_STATUS_AVAILABLE_STYLE,
        )
        self._banner.show_downloading(version)
        self._start_download(version)

    def _on_check_error(self, error: str, *, silent: bool = False) -> None:
        """Handle unexpected exception during update check."""
        self._settings_window.reset_check_updates_button()
        self._settings_window.set_update_status('Check failed', UPDATE_STATUS_ERROR_STYLE)

        if not silent:
            self._banner.show_error(f'Update check error: {error}')
        else:
            logger.warning('Automatic update check error: %s', error)

    # ------------------------------------------------------------------
    # Download flow
    # ------------------------------------------------------------------

    def _start_download(self, version: str) -> None:
        """Start downloading the update in the background."""
        self._update_task = asyncio.create_task(self._async_download(version))

    async def _async_download(self, version: str) -> None:
        """Run the download coroutine and route results."""
        try:
            success = await download_update(
                self._client,
                on_progress=self._banner.show_downloading_progress,
            )
            self._on_download_finished(success, version)
        except Exception as exc:
            logger.exception('Update download failed')
            self._on_download_error(str(exc))

    def _on_download_finished(self, success: bool, version: str) -> None:
        """Handle download completion."""
        if not success:
            self._banner.show_error('Download failed. Please try again later.')
            self._settings_window.set_update_status('Download failed', UPDATE_STATUS_ERROR_STYLE)
            return

        # Persist the client update timestamp
        update_user_config(last_client_update=datetime.now(UTC).isoformat())

        if self._can_auto_apply():
            # Silently apply and restart — no banner, no user interaction
            logger.info('Auto-applying update v%s', version)
            self._settings_window.set_update_status(
                f'v{version} installing\u2026',
                UPDATE_STATUS_AVAILABLE_STYLE,
            )
            self._apply_update(silent=True)
            return

        # Manual mode (or user is active) — show ready banner and let user choose when to restart
        self._banner.show_ready(version)
        self._settings_window.set_update_status(
            f'v{version} ready',
            UPDATE_STATUS_UP_TO_DATE_STYLE,
        )
        self._settings_window.show_restart_button()

    def _on_download_error(self, error: str) -> None:
        """Handle download error — show error banner."""
        self._banner.show_error(f'Download error: {error}')
        self._settings_window.set_update_status('Download failed', UPDATE_STATUS_ERROR_STYLE)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply_update(self, *, silent: bool = False) -> None:
        """Apply the downloaded update and restart.

        Args:
            silent: When ``True``, suppress the Velopack splash window
                by using ``wait_exit_then_apply_updates``.
        """
        if self._client.updater is None:
            return

        try:
            self._client.apply_update_on_exit(restart=True, silent=silent)
            logger.info('Update scheduled — restarting application')
            self._app.quit()
        except Exception as e:
            logger.error('Failed to apply update: %s', e)
            self._banner.show_error(f'Failed to apply update: {e}')
