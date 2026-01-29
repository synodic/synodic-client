"""Screen class for the Synodic Client application."""

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Main window for the application."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle('Synodic Client')

    def show(self) -> None:
        """Show the window, initializing UI lazily on first show."""
        # Future: Initialize heavy UI components here on first show
        super().show()


class Screen:
    """Screen class for the Synodic Client application."""

    _window: MainWindow | None = None

    @property
    def window(self) -> MainWindow:
        """Lazily create the main window on first access.

        Returns:
            The MainWindow instance.
        """
        if self._window is None:
            self._window = MainWindow()
        return self._window
