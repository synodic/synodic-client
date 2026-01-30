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

        with client.resource(icon_name) as icon_path:
            self.tray_icon = QIcon(str(icon_path))

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.tray_icon)

        self.tray.setVisible(True)

        self.menu = QMenu()

        self.open_action = QAction('Open', self.menu)
        self.menu.addAction(self.open_action)
        self.open_action.triggered.connect(window.show)

        self.settings_action = QAction('Settings', self.menu)
        self.menu.addAction(self.settings_action)

        self.menu.addSeparator()

        self.update_action = QAction('Check for Updates...', self.menu)
        self.update_action.triggered.connect(self._on_check_updates)
        self.menu.addAction(self.update_action)

        self.menu.addSeparator()

        self.quit_action = QAction('Quit', self.menu)
        self.quit_action.triggered.connect(app.quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)

    def _on_check_updates(self) -> None:
        """Handle check for updates action."""
        if self._client.updater is None:
            QMessageBox.warning(
                self._window,
                'Update Error',
                'Updater is not initialized.',
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
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_worker.error.connect(self._update_thread.quit)

        # Start the thread
        self._update_thread.start()

    def _on_update_check_finished(self, result: UpdateInfo | None) -> None:
        """Handle update check completion."""
        self.update_action.setEnabled(True)
        self.update_action.setText('Check for Updates...')

        if result is None:
            QMessageBox.warning(
                self._window,
                'Update Check Failed',
                'Failed to check for updates. Please try again later.',
            )
            return

        if result.error:
            QMessageBox.warning(
                self._window,
                'Update Check Failed',
                f'Failed to check for updates:\n{result.error}',
            )
            return

        if not result.available:
            QMessageBox.information(
                self._window,
                'No Updates Available',
                f'You are running the latest version ({result.current_version}).',
            )
            return

        # Update available - prompt user
        reply = QMessageBox.question(
            self._window,
            'Update Available',
            f'A new version is available!\n\n'
            f'Current version: {result.current_version}\n'
            f'New version: {result.latest_version}\n\n'
            f'Would you like to download and install it?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._start_download()

    def _on_update_check_error(self, error: str) -> None:
        """Handle update check error."""
        self.update_action.setEnabled(True)
        self.update_action.setText('Check for Updates...')

        QMessageBox.critical(
            self._window,
            'Update Check Error',
            f'An error occurred while checking for updates:\n{error}',
        )

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
            QMessageBox.warning(
                self._window,
                'Download Failed',
                'Failed to download the update. Please try again later.',
            )
            return

        # Prompt to apply update
        reply = QMessageBox.question(
            self._window,
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

        QMessageBox.critical(
            self._window,
            'Download Error',
            f'An error occurred while downloading the update:\n{error}',
        )

    def _apply_update(self) -> None:
        """Apply the downloaded update."""
        if self._client.updater is None:
            return

        try:
            # Schedule update to apply on exit, then quit the app
            self._client.apply_update_on_exit(restart=True)

            QMessageBox.information(
                self._window,
                'Update Ready',
                'The update will be applied when the application closes.\n'
                'The application will restart automatically with the new version.',
            )
            self._app.quit()

        except Exception as e:
            QMessageBox.warning(
                self._window,
                'Update Failed',
                f'Failed to apply the update: {e}',
            )
