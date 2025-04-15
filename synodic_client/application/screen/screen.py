"""Screen class for the Synodic Client application."""

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Main window for the application."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()


class Screen:
    """Screen class for the Synodic Client application."""

    def __init__(self):
        """Initialize the screen."""
        self.window = MainWindow()

        self.window.setWindowTitle('Synodic Client')
