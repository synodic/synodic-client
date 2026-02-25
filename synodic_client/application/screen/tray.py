"""Tray screen for the application."""

import asyncio
import logging
from collections.abc import Callable

from porringer.api import API
from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSystemTrayIcon,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen.screen import MainWindow
from synodic_client.application.screen.settings import SettingsWindow
from synodic_client.application.workers import ToolUpdateWorker, UpdateCheckWorker, UpdateDownloadWorker
from synodic_client.client import Client
from synodic_client.config import GlobalConfiguration
from synodic_client.resolution import (
    resolve_config,
    resolve_enabled_plugins,
    resolve_update_config,
    update_and_resolve,
)
from synodic_client.updater import UpdateInfo

logger = logging.getLogger(__name__)


class TrayScreen:
    """Tray screen for the application."""

    def __init__(
        self,
        app: QApplication,
        client: Client,
        window: MainWindow,
        config: GlobalConfiguration | None = None,
    ) -> None:
        """Initialize the tray icon.

        Args:
            app: The running ``QApplication``.
            client: The Synodic Client service.
            window: The main application window.
            config: Optional pre-resolved configuration.  When ``None``,
                the configuration is resolved from disk on demand.
        """
        self._app = app
        self._client = client
        self._window = window
        self._config = config
        self._runner: QThread | None = None
        self._tool_runner: QThread | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._pending_update_info: UpdateInfo | None = None
        self._download_cancelled = False

        self.tray_icon = app_icon()

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)
        self.tray.messageClicked.connect(self._on_notification_clicked)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setVisible(True)

        self._build_menu(app, window)

        # Settings window (created once, shown/hidden on demand)
        self._settings_window = SettingsWindow(self._resolve_config())
        self._settings_window.settings_changed.connect(self._on_settings_changed)
        self._settings_window.check_updates_requested.connect(self._on_check_updates)

        # MainWindow gear button → open settings
        window.settings_requested.connect(self._show_settings)

        # Periodic auto-update checking
        self._auto_update_timer: QTimer | None = None
        self._restart_auto_update_timer()

        # Periodic tool update checking
        self._tool_update_timer: QTimer | None = None
        self._restart_tool_update_timer()

        # Connect PluginsView signals when available
        plugins_view = window.plugins_view
        if plugins_view is not None:
            plugins_view.update_all_requested.connect(self._on_tool_update)
            plugins_view.plugin_update_requested.connect(self._on_single_plugin_update)

    def _build_menu(self, app: QApplication, window: MainWindow) -> None:
        """Build the tray context menu."""
        self.menu = QMenu()

        self.open_action = QAction('Open', self.menu)
        self.menu.addAction(self.open_action)
        self.open_action.triggered.connect(window.show)

        self.menu.addSeparator()

        self.update_action = QAction('Check for Updates...', self.menu)
        self.update_action.triggered.connect(self._on_check_updates)
        self.menu.addAction(self.update_action)

        self.menu.addSeparator()

        self.settings_action = QAction('Settings\u2026', self.menu)
        self.settings_action.triggered.connect(self._show_settings)
        self.menu.addAction(self.settings_action)

        self.menu.addSeparator()

        self.quit_action = QAction('Quit', self.menu)
        self.quit_action.triggered.connect(app.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)

    # -- Config helpers --

    def _resolve_config(self) -> GlobalConfiguration:
        """Return the injected config or resolve from disk."""
        if self._config is not None:
            return self._config
        return resolve_config()

    def _restart_timer(
        self,
        current: QTimer | None,
        interval_minutes: int,
        slot: Callable[[], None],
        label: str,
    ) -> QTimer | None:
        """Stop *current* and return a new periodic timer, or ``None``.

        Args:
            current: The existing timer to stop (may be ``None``).
            interval_minutes: Interval in minutes.  ``0`` disables.
            slot: The callable to invoke on each tick.
            label: Human-readable name for log messages.

        Returns:
            A running ``QTimer``, or ``None`` when disabled.
        """
        if current is not None:
            current.stop()

        if interval_minutes <= 0:
            logger.info('%s is disabled', label)
            return None

        timer = QTimer()
        timer.setInterval(interval_minutes * 60 * 1000)
        timer.timeout.connect(slot)
        timer.start()
        logger.info('%s enabled (every %d minute(s))', label, interval_minutes)
        return timer

    def _restart_auto_update_timer(self) -> None:
        """Start (or restart) the periodic auto-update timer from config."""
        config = resolve_update_config(self._resolve_config())
        self._auto_update_timer = self._restart_timer(
            self._auto_update_timer,
            config.auto_update_interval_minutes,
            self._on_auto_check_updates,
            'Automatic update checking',
        )

    def _restart_tool_update_timer(self) -> None:
        """Start (or restart) the periodic tool update timer from config."""
        config = resolve_update_config(self._resolve_config())
        self._tool_update_timer = self._restart_timer(
            self._tool_update_timer,
            config.tool_update_interval_minutes,
            self._on_tool_update,
            'Automatic tool updating',
        )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (e.g. double-click)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _show_settings(self) -> None:
        """Show the settings window."""
        self._settings_window.show()

    def _on_settings_changed(self) -> None:
        """React to a change made in the settings window."""
        config = self._resolve_config()
        self._reinitialize_updater(config)

    def _reinitialize_updater(self, config: GlobalConfiguration) -> None:
        """Re-derive update settings and restart the updater and timers."""
        update_cfg = update_and_resolve(config)
        self._client.initialize_updater(update_cfg)
        self._restart_auto_update_timer()
        self._restart_tool_update_timer()
        logger.info('Updater re-initialized (channel: %s, source: %s)', update_cfg.channel.name, update_cfg.repo_url)

    def _reset_update_action(self) -> None:
        """Restore the 'Check for Updates' action to its idle state."""
        self.update_action.setEnabled(True)
        self.update_action.setText('Check for Updates...')

    def _close_progress(self) -> None:
        """Close and discard the download progress dialog, if open."""
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

    def _on_check_updates(self) -> None:
        """Handle manual check for updates action."""
        self._do_check_updates(silent=False)

    def _on_auto_check_updates(self) -> None:
        """Handle automatic (periodic) check for updates.

        Failures and no-update results are logged silently without
        showing Windows notifications.
        """
        self._do_check_updates(silent=True)

    def _do_check_updates(self, *, silent: bool) -> None:
        """Run an update check.

        Args:
            silent: When ``True``, suppress notifications for failures
                and no-update results.  Notifications are still shown
                when an update *is* available.
        """
        if self._client.updater is None:
            if not silent:
                self.tray.showMessage(
                    'Update Error',
                    'Updater is not initialized.',
                    QSystemTrayIcon.MessageIcon.Warning,
                )
            return

        # Disable both the tray action and the settings button while checking
        self.update_action.setEnabled(False)
        self.update_action.setText('Checking for Updates...')
        self._settings_window._check_updates_btn.setEnabled(False)
        self._settings_window.set_update_status('Checking\u2026')

        worker = UpdateCheckWorker(self._client)
        worker.finished.connect(lambda result: self._on_update_check_finished(result, silent=silent))
        worker.error.connect(lambda error: self._on_update_check_error(error, silent=silent))

        self._runner = worker
        self._runner.start()

    def _on_update_check_finished(self, result: UpdateInfo | None, *, silent: bool = False) -> None:
        """Handle update check completion."""
        self._reset_update_action()
        self._settings_window.reset_check_updates_button()

        if result is None:
            self._settings_window.set_update_status('Check failed')
            if not silent:
                self.tray.showMessage(
                    'Update Check Failed',
                    'Failed to check for updates. Please try again later.',
                    QSystemTrayIcon.MessageIcon.Warning,
                )
            else:
                logger.warning('Automatic update check failed (no result)')
            return

        if result.error:
            self._settings_window.set_update_status(result.error)
            if not silent:
                # Distinguish informational messages (no releases for channel)
                # from genuine failures.
                is_no_releases = 'No releases found' in result.error
                title = 'No Updates Available' if is_no_releases else 'Update Check Failed'
                icon = (
                    QSystemTrayIcon.MessageIcon.Information if is_no_releases else QSystemTrayIcon.MessageIcon.Warning
                )
                self.tray.showMessage(title, result.error, icon)
            else:
                logger.warning('Automatic update check failed: %s', result.error)
            return

        if not result.available:
            self._settings_window.set_update_status(
                f'Up to date ({result.current_version})',
            )
            if not silent:
                self.tray.showMessage(
                    'No Updates Available',
                    f'You are running the latest version ({result.current_version}).',
                    QSystemTrayIcon.MessageIcon.Information,
                )
            else:
                logger.debug('Automatic update check: no update available')
            return

        # Update available - always show notification, clicking it starts download
        self._pending_update_info = result
        self._settings_window.set_update_status(
            f'Update available: {result.latest_version}',
        )
        self.tray.showMessage(
            'Update Available',
            f'Version {result.latest_version} is available (current: {result.current_version}).\nClick to download.',
            QSystemTrayIcon.MessageIcon.Information,
        )

    def _on_update_check_error(self, error: str, *, silent: bool = False) -> None:
        """Handle update check error."""
        self._reset_update_action()
        self._settings_window.reset_check_updates_button()
        self._settings_window.set_update_status(f'Error: {error}')

        if not silent:
            self.tray.showMessage(
                'Update Check Error',
                f'An error occurred: {error}',
                QSystemTrayIcon.MessageIcon.Critical,
            )
        else:
            logger.warning('Automatic update check error: %s', error)

    # -- Tool update helpers --

    def _on_tool_update(self) -> None:
        """Trigger a background re-sync of manifest-declared tools."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Tool update skipped: porringer not available')
            return

        logger.info('Starting periodic tool update check')
        asyncio.ensure_future(self._do_tool_update(porringer))

    async def _do_tool_update(self, porringer: API) -> None:
        """Resolve enabled plugins off-thread, then start the update worker."""
        loop = asyncio.get_running_loop()
        config = self._resolve_config()
        all_plugins = await loop.run_in_executor(None, lambda: porringer.plugin.list())  # noqa: PLW0108
        all_names = [p.name for p in all_plugins if p.installed]
        enabled = resolve_enabled_plugins(config, all_names)

        worker = ToolUpdateWorker(porringer, plugins=enabled)
        worker.finished.connect(self._on_tool_update_finished)
        worker.error.connect(self._on_tool_update_error)

        self._tool_runner = worker
        self._tool_runner.start()

    def _on_single_plugin_update(self, plugin_name: str) -> None:
        """Upgrade a single plugin across all cached projects."""
        porringer = self._window.porringer
        if porringer is None:
            logger.warning('Single plugin update skipped: porringer not available')
            return

        logger.info('Starting update for plugin: %s', plugin_name)

        worker = ToolUpdateWorker(porringer, plugins=[plugin_name])
        worker.finished.connect(self._on_tool_update_finished)
        worker.error.connect(self._on_tool_update_error)

        self._tool_runner = worker
        self._tool_runner.start()

    def _on_tool_update_finished(self, count: int) -> None:
        """Handle tool update completion."""
        logger.info('Tool update completed: %d manifest(s) processed', count)
        self._window.show()

    def _on_tool_update_error(self, error: str) -> None:
        """Handle tool update error."""
        logger.error('Tool update failed: %s', error)
        self.tray.showMessage(
            'Tool Update Error',
            f'An error occurred during tool update: {error}',
            QSystemTrayIcon.MessageIcon.Warning,
        )

    def _on_notification_clicked(self) -> None:
        """Handle notification click - starts download if update is pending."""
        if self._pending_update_info is not None and self._pending_update_info.available:
            self._pending_update_info = None
            self._start_download()

    def _start_download(self) -> None:
        """Start downloading the update."""
        # Create progress dialog
        self._progress_dialog = QProgressDialog(
            'Downloading update...',
            'Cancel',
            0,
            100,
            self._window,
        )
        self._progress_dialog.setWindowTitle('Downloading Update')
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.canceled.connect(self._on_download_cancelled)
        self._download_cancelled = False
        self._progress_dialog.show()

        worker = UpdateDownloadWorker(self._client)
        worker.finished.connect(self._on_download_finished)
        worker.progress.connect(self._on_download_progress)
        worker.error.connect(self._on_download_error)

        self._runner = worker
        self._runner.start()

    def _on_download_cancelled(self) -> None:
        """Handle cancel button on the download progress dialog."""
        self._download_cancelled = True
        self._close_progress()
        logger.info('Update download cancelled by user')

    def _on_download_progress(self, percentage: int) -> None:
        """Handle download progress update."""
        if self._progress_dialog and not self._download_cancelled:
            self._progress_dialog.setValue(percentage)
            self._progress_dialog.setLabelText(f'Downloading update... {percentage}%')

    def _on_download_finished(self, success: bool) -> None:
        """Handle download completion."""
        self._close_progress()

        if self._download_cancelled:
            return

        if not success:
            self.tray.showMessage(
                'Download Failed',
                'Failed to download the update. Please try again later.',
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        # Prompt to apply update - keep as dialog since it needs user choice
        reply = QMessageBox.question(
            self._window if self._window.isVisible() else None,
            'Download Complete',
            'The update has been downloaded.\n\n'
            'Would you like to install it now?\n'
            'The application will restart after installation.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._apply_update()

    def _on_download_error(self, error: str) -> None:
        """Handle download error."""
        self._close_progress()

        self.tray.showMessage(
            'Download Error',
            f'An error occurred while downloading: {error}',
            QSystemTrayIcon.MessageIcon.Critical,
        )

    def _apply_update(self) -> None:
        """Apply the downloaded update."""
        if self._client.updater is None:
            return

        try:
            # Schedule update to apply on exit, then quit the app
            self._client.apply_update_on_exit(restart=True)

            self.tray.showMessage(
                'Update Ready',
                'The update will be applied when the application closes.\nThe application will restart automatically.',
                QSystemTrayIcon.MessageIcon.Information,
            )
            self._app.quit()

        except Exception as e:
            self.tray.showMessage(
                'Update Failed',
                f'Failed to apply the update: {e}',
                QSystemTrayIcon.MessageIcon.Warning,
            )
