"""Single-instance application management using Qt local sockets.

Ensures only one instance of Synodic Client runs at a time.  When a second
instance is launched (e.g. by clicking a ``synodic://`` URI), it sends the
URI to the already-running instance and exits.
"""

import logging

from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_SERVER_NAME = 'synodic-client'


class SingleInstance(QObject):
    """Manages single-instance enforcement via a local socket server.

    Signals:
        uri_received: Emitted when another instance sends a URI string.
    """

    uri_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the single instance manager.

        Args:
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._server: QLocalServer | None = None

    @staticmethod
    def try_send_to_existing(message: str) -> bool:
        """Attempt to send a message to an already-running instance.

        Args:
            message: The message (typically a ``synodic://`` URI) to send.

        Returns:
            True if the message was sent successfully (another instance is running).
            False if no other instance was found.
        """
        socket = QLocalSocket()
        socket.connectToServer(_SERVER_NAME)

        if socket.waitForConnected(1000):
            socket.write(QByteArray(message.encode('utf-8')))
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            logger.info('Sent message to existing instance: %s', message)
            return True

        return False

    def start_server(self) -> bool:
        """Start the local socket server to listen for incoming messages.

        If a stale server exists (e.g. from a crash), it will be cleaned up
        and a new server started.

        Returns:
            True if the server started successfully.
        """
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

        if not self._server.listen(_SERVER_NAME):
            # Clean up stale socket from a previous crash
            QLocalServer.removeServer(_SERVER_NAME)
            if not self._server.listen(_SERVER_NAME):
                logger.error('Failed to start single-instance server: %s', self._server.errorString())
                return False

        logger.debug('Single-instance server listening as "%s"', _SERVER_NAME)
        return True

    def _on_new_connection(self) -> None:
        """Handle an incoming connection from another instance."""
        if self._server is None:
            return

        socket = self._server.nextPendingConnection()
        if socket is None:
            return

        if socket.waitForReadyRead(1000):
            raw = socket.readAll().data()
            data = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else str(raw)
            if data:
                logger.info('Received message from another instance: %s', data)
                self.uri_received.emit(data)
            else:
                logger.info('Another instance connected (no URI)')

        socket.disconnectFromServer()
