"""Tray screen for the application."""

import asyncio
import logging
from pathlib import Path

from porringer.api import API
from porringer.schema import SetupParameters, SyncStrategy
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from synodic_client.application.icon import app_icon
from synodic_client.application.screen.screen import MainWindow
from synodic_client.application.theme import UPDATE_SOURCE_DIALOG_MIN_WIDTH
from synodic_client.client import Client
from synodic_client.config import GlobalConfiguration
from synodic_client.logging import open_log
from synodic_client.resolution import resolve_config, resolve_enabled_plugins, resolve_update_config, update_and_resolve
from synodic_client.updater import GITHUB_REPO_URL, UpdateChannel, UpdateInfo

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """Worker for checking updates in a background thread."""

    finished = Signal(object)  # UpdateInfo
    error = Signal(str)

    def __init__(self, client: Client) -> None:
        """Initialize the worker."""
        super().__init__()
        self._client = client

    def run(self) -> None:
        """Run the update check."""
        try:
            result = self._client.check_for_update()
            self.finished.emit(result)
        except Exception as e:
            logger.exception('Update check failed')
            self.error.emit(str(e))


class UpdateDownloadWorker(QThread):
    """Worker for downloading updates in a background thread."""

    finished = Signal(bool)  # success status
    progress = Signal(int)  # percentage (0-100)
    error = Signal(str)

    def __init__(self, client: Client) -> None:
        """Initialize the worker."""
        super().__init__()
        self._client = client

    def run(self) -> None:
        """Run the update download."""
        try:

            def progress_callback(percentage: int) -> None:
                self.progress.emit(percentage)

            success = self._client.download_update(progress_callback)
            self.finished.emit(success)
        except Exception as e:
            logger.exception('Update download failed')
            self.error.emit(str(e))


class ToolUpdateWorker(QThread):
    """Worker for re-syncing manifest-declared tools in a background thread."""

    finished = Signal(int)  # number of manifests processed
    error = Signal(str)

    def __init__(self, porringer: API, plugins: list[str] | None = None) -> None:
        """Initialize the worker.

        Args:
            porringer: The porringer API instance.
            plugins: Optional include-list of plugin names.  When set, only
                actions handled by these plugins are executed.  ``None``
                means all plugins.
        """
        super().__init__()
        self._porringer = porringer
        self._plugins = plugins

    def run(self) -> None:
        """Re-sync all cached project manifests."""
        try:
            directories = self._porringer.cache.list_directories()
            count = 0
            for directory in directories:
                manifest = Path(directory.path) / 'porringer.json'
                if not manifest.exists():
                    logger.debug('Skipping missing manifest: %s', manifest)
                    continue
                params = SetupParameters(
                    paths=[manifest],
                    project_directory=Path(directory.path),
                    strategy=SyncStrategy.LATEST,
                    plugins=self._plugins,
                )
                asyncio.run(self._sync(params))
                count += 1
            self.finished.emit(count)
        except Exception as e:
            logger.exception('Tool update failed')
            self.error.emit(str(e))

    async def _sync(self, params: SetupParameters) -> None:
        """Execute a sync stream for the given parameters."""
        async for _event in self._porringer.sync.execute_stream(params):
            pass  # consume events to completion


class UpdateSourceDialog(QDialog):
    """Dialog for editing the Velopack update source URL or local path."""

    def __init__(self, current_source: str | None, parent: QWidget | None = None) -> None:
        """Initialise the dialog.

        Args:
            current_source: The current update source value (may be ``None``).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle('Update Source')
        self.setMinimumWidth(UPDATE_SOURCE_DIALOG_MIN_WIDTH)

        layout = QVBoxLayout(self)

        label = QLabel(
            'Enter a URL or local path for Velopack releases.\nLeave blank to use the default GitHub source.',
        )
        layout.addWidget(label)

        self._source_edit = QLineEdit(current_source or '')
        self._source_edit.setPlaceholderText(GITHUB_REPO_URL)

        browse_button = QPushButton('Browse...')
        browse_button.clicked.connect(self._browse)

        row = QHBoxLayout()
        row.addWidget(self._source_edit)
        row.addWidget(browse_button)
        layout.addLayout(row)

        button_row = QHBoxLayout()
        ok_button = QPushButton('OK')
        cancel_button = QPushButton('Cancel')
        button_row.addStretch()
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, 'Select Releases Directory')
        if path:
            self._source_edit.setText(path)

    @property
    def source(self) -> str | None:
        """Return the trimmed source text, or ``None`` if blank."""
        return self._source_edit.text().strip() or None


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

        # Periodic auto-update checking
        self._auto_update_timer: QTimer | None = None
        self._start_auto_update_timer()

        # Periodic tool update checking
        self._tool_update_timer: QTimer | None = None
        self._start_tool_update_timer()

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

        # Settings submenu
        self.settings_menu = QMenu('Settings', self.menu)
        self.menu.addMenu(self.settings_menu)

        self.update_action = QAction('Check for Updates...', self.settings_menu)
        self.update_action.triggered.connect(self._on_check_updates)
        self.settings_menu.addAction(self.update_action)

        self.settings_menu.addSeparator()

        # Update Source action
        self.update_source_action = QAction('Update Source...', self.settings_menu)
        self.update_source_action.triggered.connect(self._on_update_source)
        self.settings_menu.addAction(self.update_source_action)

        # Update Channel submenu
        self.channel_menu = QMenu('Update Channel', self.settings_menu)
        self.settings_menu.addMenu(self.channel_menu)

        self._channel_stable_action = QAction('Stable', self.channel_menu)
        self._channel_stable_action.setCheckable(True)
        self._channel_stable_action.triggered.connect(lambda: self._on_channel_changed(UpdateChannel.STABLE))
        self.channel_menu.addAction(self._channel_stable_action)

        self._channel_dev_action = QAction('Development', self.channel_menu)
        self._channel_dev_action.setCheckable(True)
        self._channel_dev_action.triggered.connect(lambda: self._on_channel_changed(UpdateChannel.DEVELOPMENT))
        self.channel_menu.addAction(self._channel_dev_action)

        # Set initial channel check state from config
        self._sync_channel_checks()

        self.settings_menu.addSeparator()

        self.open_log_action = QAction('Open Log...', self.settings_menu)
        self.open_log_action.triggered.connect(open_log)
        self.settings_menu.addAction(self.open_log_action)

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

    def _start_auto_update_timer(self) -> None:
        """Start (or restart) the periodic auto-update timer from config."""
        if self._auto_update_timer is not None:
            self._auto_update_timer.stop()
            self._auto_update_timer = None

        config = resolve_update_config(self._resolve_config())
        interval_minutes = config.auto_update_interval_minutes
        if interval_minutes <= 0:
            logger.info('Automatic update checking is disabled')
            return

        interval_ms = interval_minutes * 60 * 1000
        self._auto_update_timer = QTimer()
        self._auto_update_timer.setInterval(interval_ms)
        self._auto_update_timer.timeout.connect(self._on_auto_check_updates)
        self._auto_update_timer.start()
        logger.info('Automatic update checking enabled (every %d minute(s))', interval_minutes)

    def _start_tool_update_timer(self) -> None:
        """Start (or restart) the periodic tool update timer from config."""
        if self._tool_update_timer is not None:
            self._tool_update_timer.stop()
            self._tool_update_timer = None

        config = resolve_update_config(self._resolve_config())
        interval_minutes = config.tool_update_interval_minutes
        if interval_minutes <= 0:
            logger.info('Automatic tool updating is disabled')
            return

        interval_ms = interval_minutes * 60 * 1000
        self._tool_update_timer = QTimer()
        self._tool_update_timer.setInterval(interval_ms)
        self._tool_update_timer.timeout.connect(self._on_tool_update)
        self._tool_update_timer.start()
        logger.info('Automatic tool updating enabled (every %d minute(s))', interval_minutes)

    def _sync_channel_checks(self) -> None:
        """Synchronize channel checkmarks with the current config."""
        config = self._resolve_config()
        is_dev = config.update_channel == 'dev'
        self._channel_stable_action.setChecked(not is_dev)
        self._channel_dev_action.setChecked(is_dev)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon activation (e.g. double-click)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()

    def _on_update_source(self) -> None:
        """Open a dialog to edit the update source URL or local path."""
        config = self._resolve_config()

        parent = self._window if self._window.isVisible() else None
        dialog = UpdateSourceDialog(config.update_source, parent)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            config.update_source = dialog.source
            logger.info('Update source changed to: %s', dialog.source or '(default)')
            self._reinitialize_updater(config)

    def _on_channel_changed(self, channel: UpdateChannel) -> None:
        """Handle channel selection change."""
        config = self._resolve_config()
        config.update_channel = 'dev' if channel == UpdateChannel.DEVELOPMENT else 'stable'
        logger.info('Update channel changed to: %s', config.update_channel)
        self._sync_channel_checks()
        self._reinitialize_updater(config)

    def _reinitialize_updater(self, config: GlobalConfiguration) -> None:
        """Re-derive update settings and restart the updater and timers."""
        update_cfg = update_and_resolve(config)
        self._client.initialize_updater(update_cfg)
        self._start_auto_update_timer()
        self._start_tool_update_timer()
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

        # Disable the action while checking
        self.update_action.setEnabled(False)
        self.update_action.setText('Checking for Updates...')

        worker = UpdateCheckWorker(self._client)
        worker.finished.connect(lambda result: self._on_update_check_finished(result, silent=silent))
        worker.error.connect(lambda error: self._on_update_check_error(error, silent=silent))

        self._runner = worker
        self._runner.start()

    def _on_update_check_finished(self, result: UpdateInfo | None, *, silent: bool = False) -> None:
        """Handle update check completion."""
        self._reset_update_action()

        if result is None:
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
            if not silent:
                self.tray.showMessage(
                    'Update Check Failed',
                    f'Failed to check for updates: {result.error}',
                    QSystemTrayIcon.MessageIcon.Warning,
                )
            else:
                logger.warning('Automatic update check failed: %s', result.error)
            return

        if not result.available:
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
        self.tray.showMessage(
            'Update Available',
            f'Version {result.latest_version} is available (current: {result.current_version}).\nClick to download.',
            QSystemTrayIcon.MessageIcon.Information,
        )

    def _on_update_check_error(self, error: str, *, silent: bool = False) -> None:
        """Handle update check error."""
        self._reset_update_action()

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

        config = self._resolve_config()
        all_names = [p.name for p in porringer.plugin.list() if p.installed]
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
