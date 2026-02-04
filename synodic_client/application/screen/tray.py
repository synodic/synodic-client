"""Tray screen for the application."""

import logging
from typing import LiteralString

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QProgressDialog, QSystemTrayIcon

from synodic_client.application.screen.screen import MainWindow
from synodic_client.client import Client
from synodic_client.updater import UpdateInfo

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

        with client.resource(icon_name) as icon_path:
            self.tray_icon = QIcon(str(icon_path))

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)
        self.tray.messageClicked.connect(self._on_notification_clicked)

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

        self.menu.addSeparator()

        self.quit_action = QAction('Quit', self.menu)
        self.quit_action.triggered.connect(app.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)

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
            f'Version {result.latest_version} is available (current: {result.current_version}).\n'
            'Click to download.',
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

    def _on_download_progress(self, percentage: int) -> None:
        """Handle download progress update."""
        if self._progress_dialog:
            self._progress_dialog.setValue(percentage)
            self._progress_dialog.setLabelText(f'Downloading update... {percentage}%')

    def _on_download_finished(self, success: bool) -> None:
        """Handle download completion."""
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

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
                'The update will be applied when the application closes.\n'
                'The application will restart automatically.',
                QSystemTrayIcon.MessageIcon.Information,
            )
            self._app.quit()

        except Exception as e:
            self.tray.showMessage(
                'Update Failed',
                f'Failed to apply the update: {e}',
                QSystemTrayIcon.MessageIcon.Warning,
            )
