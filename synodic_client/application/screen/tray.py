"""Tray screen for the application."""

import logging
from typing import LiteralString

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction, QIcon
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
)

from synodic_client.application.screen.screen import MainWindow
from synodic_client.client import Client
from synodic_client.logging import open_log
from synodic_client.resolution import resolve_config, update_and_resolve
from synodic_client.updater import GITHUB_REPO_URL, UpdateChannel, UpdateInfo

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QObject):
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


class UpdateDownloadWorker(QObject):
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


class TrayScreen:
    """Tray screen for the application."""

    def __init__(self, app: QApplication, client: Client, icon_name: LiteralString, window: MainWindow) -> None:
        """Initialize the tray icon."""
        self._app = app
        self._client = client
        self._window = window
        self._update_thread: QThread | None = None
        self._update_worker: UpdateCheckWorker | UpdateDownloadWorker | None = None
        self._progress_dialog: QProgressDialog | None = None
        self._pending_update_info: UpdateInfo | None = None
        self._download_cancelled = False

        with client.resource(icon_name) as icon_path:
            self.tray_icon = QIcon(str(icon_path))

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)
        self.tray.messageClicked.connect(self._on_notification_clicked)
        self.tray.activated.connect(self._on_tray_activated)

        self.tray.setVisible(True)

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

    def _sync_channel_checks(self) -> None:
        """Synchronize channel checkmarks with the current config."""
        config = resolve_config()
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
        config = resolve_config()

        dialog = QDialog(self._window if self._window.isVisible() else None)
        dialog.setWindowTitle('Update Source')
        dialog.setMinimumWidth(450)

        layout = QVBoxLayout(dialog)

        label = QLabel(
            'Enter a URL or local path for Velopack releases.\nLeave blank to use the default GitHub source.',
        )
        layout.addWidget(label)

        source_edit = QLineEdit(config.update_source or '')
        source_edit.setPlaceholderText(GITHUB_REPO_URL)

        browse_button = QPushButton('Browse...')

        row = QHBoxLayout()
        row.addWidget(source_edit)
        row.addWidget(browse_button)
        layout.addLayout(row)

        button_row = QHBoxLayout()
        ok_button = QPushButton('OK')
        cancel_button = QPushButton('Cancel')
        button_row.addStretch()
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        def _browse() -> None:
            path = QFileDialog.getExistingDirectory(dialog, 'Select Releases Directory')
            if path:
                source_edit.setText(path)

        browse_button.clicked.connect(_browse)
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_source = source_edit.text().strip() or None
            config.update_source = new_source
            logger.info('Update source changed to: %s', new_source or '(default)')

            update_cfg = update_and_resolve(config)
            self._client.initialize_updater(update_cfg)
            logger.info(
                'Updater re-initialized (channel: %s, source: %s)', update_cfg.channel.name, update_cfg.repo_url
            )

    def _on_channel_changed(self, channel: UpdateChannel) -> None:
        """Handle channel selection change."""
        config = resolve_config()
        config.update_channel = 'dev' if channel == UpdateChannel.DEVELOPMENT else 'stable'
        logger.info('Update channel changed to: %s', config.update_channel)

        update_cfg = update_and_resolve(config)
        self._sync_channel_checks()
        self._client.initialize_updater(update_cfg)
        logger.info('Updater re-initialized (channel: %s, source: %s)', update_cfg.channel.name, update_cfg.repo_url)

    def _on_check_updates(self) -> None:
        """Handle check for updates action."""
        if self._client.updater is None:
            self.tray.showMessage(
                'Update Error',
                'Updater is not initialized.',
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        # Disable the action while checking
        self.update_action.setEnabled(False)
        self.update_action.setText('Checking for Updates...')

        # Create worker and thread
        self._update_thread = QThread()
        self._update_worker = UpdateCheckWorker(self._client)
        self._update_worker.moveToThread(self._update_thread)

        # Connect signals
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.finished.connect(self._on_update_check_finished)
        self._update_worker.error.connect(self._on_update_check_error)

        # Clean up thread and worker when thread finishes
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.finished.connect(self._update_worker.deleteLater)

        # Start the thread
        self._update_thread.start()

    def _on_update_check_finished(self, result: UpdateInfo | None) -> None:
        """Handle update check completion."""
        if self._update_thread is not None:
            self._update_thread.quit()
            self._update_thread.wait()

        self.update_action.setEnabled(True)
        self.update_action.setText('Check for Updates...')

        if result is None:
            self.tray.showMessage(
                'Update Check Failed',
                'Failed to check for updates. Please try again later.',
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        if result.error:
            self.tray.showMessage(
                'Update Check Failed',
                f'Failed to check for updates: {result.error}',
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return

        if not result.available:
            self.tray.showMessage(
                'No Updates Available',
                f'You are running the latest version ({result.current_version}).',
                QSystemTrayIcon.MessageIcon.Information,
            )
            return

        # Update available - show notification, clicking it starts download
        self._pending_update_info = result
        self.tray.showMessage(
            'Update Available',
            f'Version {result.latest_version} is available (current: {result.current_version}).\nClick to download.',
            QSystemTrayIcon.MessageIcon.Information,
        )

    def _on_update_check_error(self, error: str) -> None:
        """Handle update check error."""
        if self._update_thread is not None:
            self._update_thread.quit()
            self._update_thread.wait()

        self.update_action.setEnabled(True)
        self.update_action.setText('Check for Updates...')

        self.tray.showMessage(
            'Update Check Error',
            f'An error occurred: {error}',
            QSystemTrayIcon.MessageIcon.Critical,
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

        # Create worker and thread
        self._update_thread = QThread()
        self._update_worker = UpdateDownloadWorker(self._client)
        self._update_worker.moveToThread(self._update_thread)

        # Connect signals
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.finished.connect(self._on_download_finished)
        self._update_worker.progress.connect(self._on_download_progress)
        self._update_worker.error.connect(self._on_download_error)
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_worker.error.connect(self._update_thread.quit)

        # Start the thread
        self._update_thread.start()

    def _on_download_cancelled(self) -> None:
        """Handle cancel button on the download progress dialog."""
        self._download_cancelled = True
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None
        logger.info('Update download cancelled by user')

    def _on_download_progress(self, percentage: int) -> None:
        """Handle download progress update."""
        if self._progress_dialog and not self._download_cancelled:
            self._progress_dialog.setValue(percentage)
            self._progress_dialog.setLabelText(f'Downloading update... {percentage}%')

    def _on_download_finished(self, success: bool) -> None:
        """Handle download completion."""
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

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
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

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
