"""Self-update orchestration controller.

Owns the full update lifecycle — check → download → apply — and the
periodic auto-update timer.  Extracted from :class:`TrayScreen` so
that tray, settings, and banner concerns are cleanly separated from
the update state-machine.

The controller is the sole writer to an :class:`UpdateModel`; views
observe the model via Qt signals and never receive imperative calls
from the controller.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from synodic_client.application.theme import (
    UPDATE_STATUS_AVAILABLE_STYLE,
    UPDATE_STATUS_CHECKING_STYLE,
    UPDATE_STATUS_ERROR_STYLE,
    UPDATE_STATUS_UP_TO_DATE_STYLE,
)
from synodic_client.application.update_model import UpdateModel
from synodic_client.application.workers import check_for_update, download_update
from synodic_client.resolution import (
    ResolvedConfig,
    resolve_update_config,
)
from synodic_client.schema import UpdateInfo
from synodic_client.startup import sync_startup

if TYPE_CHECKING:
    from synodic_client.application.config_store import ConfigStore
    from synodic_client.client import Client

logger = logging.getLogger(__name__)


class UpdateController:
    """Manages the self-update lifecycle: check → download → apply.

    The controller is the sole writer to the :class:`UpdateModel`.
    Views connect to the model's signals; the controller never calls
    view methods directly.

    Parameters
    ----------
    app:
        The running ``QApplication`` (needed for ``quit()`` on auto-apply).
    client:
        The Synodic Client service facade.
    model:
        The shared :class:`UpdateModel` that views observe.
    store:
        The centralised :class:`ConfigStore`.
    """

    def __init__(
        self,
        app: QApplication,
        client: Client,
        model: UpdateModel,
        *,
        store: ConfigStore,
    ) -> None:
        """Initialise the controller and start the periodic timer.

        Args:
            app: The running ``QApplication``.
            client: The Synodic Client service facade.
            model: The shared :class:`UpdateModel`.
            store: The centralised :class:`ConfigStore`.
        """
        self._app = app
        self._client = client
        self._model = model
        self._store = store
        self._is_user_active: Callable[[], bool] = lambda: False
        self._update_task: asyncio.Task[None] | None = None
        self._pending_version: str | None = None
        self._failed_version: str | None = None

        # Derive auto-apply preference from config
        self._auto_apply: bool = store.config.auto_apply

        # Track update-relevant config fields to avoid reinitialising
        # on every config save (e.g. timestamp-only changes).
        self._update_config_key = self._extract_update_key(store.config)

        # Periodic auto-update timer
        self._auto_update_timer: QTimer | None = None
        self._restart_auto_update_timer()

        # React to config changes from any source
        self._store.changed.connect(self._on_config_changed)

    def set_user_active_predicate(self, predicate: Callable[[], bool]) -> None:
        """Set the predicate used to defer auto-apply when the user is active.

        Args:
            predicate: Returns ``True`` when the user has a visible window.
        """
        self._is_user_active = predicate

    def shutdown(self) -> None:
        """Stop timers and cancel in-flight tasks for a clean exit."""
        if self._auto_update_timer is not None:
            self._auto_update_timer.stop()
            self._auto_update_timer = None
        if self._update_task is not None and not self._update_task.done():
            self._update_task.cancel()
            self._update_task = None
        logger.info('UpdateController shut down')

    def _set_task(self, coro: Coroutine[Any, Any, None]) -> None:
        """Cancel any in-flight task and start *coro* as the active task."""
        if self._update_task is not None and not self._update_task.done():
            self._update_task.cancel()
        self._update_task = asyncio.create_task(coro)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _can_auto_apply(self) -> bool:
        """Return whether a downloaded update should be applied automatically.

        Auto-apply is suppressed when the user has a visible window so
        the application is never force-restarted during active use.
        """
        return self._auto_apply and not self._is_user_active()

    def _persist_check_timestamp(self) -> None:
        """Persist the current time as *last_client_update* and refresh the label."""
        ts = datetime.now(UTC).isoformat()
        self._store.update(last_client_update=ts)
        self._model.set_last_checked(ts)

    def _report_error(self, message: str, *, silent: bool) -> None:
        """Show an error to the user or log it, depending on *silent*.

        Always updates the settings status line.  When not *silent*,
        also transitions the model to the ERROR phase so the banner
        displays the error.
        """
        self._model.set_status('Check failed', UPDATE_STATUS_ERROR_STYLE)
        if silent:
            logger.warning('%s', message)
        else:
            self._model.set_error(message)

    # ------------------------------------------------------------------
    # Timer management
    # ------------------------------------------------------------------

    def _restart_auto_update_timer(self) -> None:
        """Start (or restart) the periodic auto-update timer from config."""
        config = resolve_update_config(self._store.config)

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

    def request_check(self) -> None:
        """Handle a user-initiated update check (from settings button)."""
        self._do_check(silent=False)

    def request_retry(self) -> None:
        """Handle a banner retry — clear the failed version lock and re-check."""
        self._failed_version = None
        self.check_now(silent=True)

    def request_apply(self) -> None:
        """Handle a user-initiated apply/restart."""
        self._apply_update(silent=False)

    def _on_config_changed(self, config: object) -> None:
        """React to a config change — reinitialise the updater and timers.

        Only reinitialises when update-relevant fields change (channel,
        source, interval, auto-apply).  Timestamp-only changes (e.g.
        ``last_client_update``) are ignored to prevent an infinite
        check → persist → reinitialise → check loop.
        """
        if not isinstance(config, ResolvedConfig):
            return
        self._auto_apply = config.auto_apply

        new_key = self._extract_update_key(config)
        if new_key == self._update_config_key:
            return
        self._update_config_key = new_key

        self._reinitialize_updater(config)
        self.check_now(silent=True)

    # ------------------------------------------------------------------
    # Updater re-initialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_update_key(config: ResolvedConfig) -> tuple[object, ...]:
        """Return a hashable tuple of the fields that affect the updater."""
        return (
            config.update_source,
            config.update_channel,
            config.auto_update_interval_minutes,
            config.auto_apply,
        )

    def _reinitialize_updater(self, config: ResolvedConfig) -> None:
        """Re-derive update settings and restart the updater and timer.

        Cancels any in-flight check/download task and clears cached
        state so the new updater starts with a clean slate.
        """
        if self._update_task is not None and not self._update_task.done():
            self._update_task.cancel()
            self._update_task = None
        self._pending_version = None
        self._failed_version = None

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
            self._model.set_check_button_enabled(True)
            if not silent:
                self._model.set_error('Updater is not initialized.')
            return

        # Always disable the button; only show "Checking…" when no
        # download is already pending (to preserve the ready state).
        self._model.set_check_button_enabled(False)
        if self._pending_version is None:
            self._model.set_restart_visible(False)
            self._model.set_status('Checking\u2026', UPDATE_STATUS_CHECKING_STYLE)

        self._set_task(self._async_check(silent=silent))

    async def _async_check(self, *, silent: bool) -> None:
        """Run the update check coroutine and route results."""
        try:
            result = await check_for_update(self._client)
            self._on_check_finished(result, silent=silent)
        except asyncio.CancelledError:
            logger.debug('Update check cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Update check failed')
            self._on_check_error(str(exc), silent=silent)

    def _on_check_finished(self, result: UpdateInfo | None, *, silent: bool = False) -> None:
        """Route the update-check result."""
        self._model.set_check_button_enabled(True)

        if result is None:
            self._report_error('Failed to check for updates.', silent=silent)
            return

        if result.error:
            self._report_error(result.error, silent=silent)
            return

        # Successful check — refresh the "last updated" timestamp
        self._persist_check_timestamp()

        if not result.available:
            self._model.set_status('Up to date', UPDATE_STATUS_UP_TO_DATE_STYLE)
            if not silent:
                logger.info('No updates available (current: %s)', result.current_version)
            else:
                logger.debug('Automatic update check: no update available')
            return

        version = str(result.latest_version)

        # Already downloaded — restore the ready state without re-downloading
        if version == self._pending_version:
            self._show_ready(version)
            return

        # Skip re-downloading a version that already failed (auto-check only).
        # A manual retry via the banner clears ``_failed_version``.
        if silent and version == self._failed_version:
            logger.debug('Skipping download of previously failed version %s', version)
            return

        # New update available — download it
        self._model.set_status(f'v{version} available', UPDATE_STATUS_AVAILABLE_STYLE)
        self._model.set_downloading(version)
        self._start_download(version, silent=silent)

    def _on_check_error(self, error: str, *, silent: bool = False) -> None:
        """Handle unexpected exception during update check."""
        self._model.set_check_button_enabled(True)
        self._report_error(f'Update check error: {error}', silent=silent)

    # ------------------------------------------------------------------
    # Download flow
    # ------------------------------------------------------------------

    def _start_download(self, version: str, *, silent: bool = False) -> None:
        """Start downloading the update in the background."""
        self._set_task(self._async_download(version, silent=silent))

    async def _async_download(self, version: str, *, silent: bool = False) -> None:
        """Run the download coroutine and route results."""
        try:
            success = await download_update(
                self._client,
                on_progress=self._on_download_progress,
            )
            self._on_download_finished(success, version, silent=silent)
        except asyncio.CancelledError:
            logger.debug('Update download cancelled (shutdown)')
            raise
        except Exception as exc:
            logger.exception('Update download failed')
            self._on_download_error(str(exc), silent=silent)

    def _on_download_progress(self, percentage: int) -> None:
        """Broadcast download progress to the model."""
        self._model.set_progress(percentage)

    def _on_download_finished(self, success: bool, version: str, *, silent: bool = False) -> None:
        """Handle download completion."""
        if not success:
            self._failed_version = version
            self._model.set_status('Download failed', UPDATE_STATUS_ERROR_STYLE)
            if not silent:
                self._model.set_error('Download failed. Please try again later.')
            else:
                logger.warning('Download failed for %s (silent)', version)
            return

        self._persist_check_timestamp()

        self._pending_version = version

        if self._can_auto_apply():
            # Silently apply and restart — no banner, no user interaction
            logger.info('Auto-applying update v%s', version)
            self._apply_update(silent=True)
            return

        self._show_ready(version)

    def _show_ready(self, version: str) -> None:
        """Present the *ready to restart* state via the model."""
        self._model.set_status(f'v{version} ready', UPDATE_STATUS_UP_TO_DATE_STYLE)
        self._model.set_restart_visible(True)
        self._model.set_ready(version)

    def _on_download_error(self, error: str, *, silent: bool = False) -> None:
        """Handle download error."""
        if not silent:
            self._model.set_error(f'Download error: {error}')
        else:
            logger.warning('Download error (silent): %s', error)

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

        if self._pending_version is None:
            self._report_error('No downloaded update to apply — please check for updates again.', silent=silent)
            return

        try:
            # Re-register the startup entry with the current exe path so
            # the registry value stays valid even if Velopack relocates
            # the binary during the update.  The relaunched process will
            # overwrite it again via run_startup_preamble, but this
            # ensures the entry is never stale between the update and
            # the next launch.
            sync_startup(sys.executable, auto_start=self._store.config.auto_start)

            self._client.apply_update_on_exit(restart=True, silent=silent)
            self._pending_version = None
            logger.info('Update scheduled — restarting application')
            self._app.quit()
        except Exception as e:
            logger.error('Failed to apply update: %s', e)
            self._model.set_error(f'Failed to apply update: {e}')
