"""Single-instance application management using Qt local sockets.

Ensures only one instance of Synodic Client runs at a time.  When a second
instance is launched (e.g. by clicking a ``synodic://`` URI), it sends the
URI to the already-running instance and exits.

Debug commands (prefixed with ``debug:``) receive a JSON response on the
same connection before it is closed.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QByteArray, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from synodic_client.application.theme import SOCKET_TIMEOUT_MS
from synodic_client.config import is_dev_mode

logger = logging.getLogger(__name__)

_SERVER_NAME = 'synodic-client'
_SERVER_NAME_DEV = 'synodic-client-dev'

_DEBUG_PREFIX = 'debug:'


def _decode(raw: bytes | bytearray | memoryview) -> str:
    """Decode raw socket data to a UTF-8 string."""
    return bytes(raw).decode('utf-8')


def _server_name() -> str:
    """Return the server name, namespaced for dev mode."""
    return _SERVER_NAME_DEV if is_dev_mode() else _SERVER_NAME


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
        self._debug_handler: Callable[[str], str] | None = None

    def set_debug_handler(self, handler: Callable[[str], str]) -> None:
        """Register a handler for ``debug:`` IPC commands.

        Args:
            handler: Callable that accepts a command string (without the
                ``debug:`` prefix) and returns a JSON response string.
        """
        self._debug_handler = handler

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
        socket.connectToServer(_server_name())

        if socket.waitForConnected(SOCKET_TIMEOUT_MS):
            socket.write(QByteArray(message.encode('utf-8')))
            socket.waitForBytesWritten(SOCKET_TIMEOUT_MS)
            socket.disconnectFromServer()
            logger.info('Sent message to existing instance: %s', message)
            return True

        return False

    @staticmethod
    def send_debug_command(command: str) -> str:
        """Send a debug command to the running instance and return its response.

        Args:
            command: The debug command (without the ``debug:`` prefix).

        Returns:
            The JSON response string from the running instance, or an
            error JSON string if the connection failed.
        """
        socket = QLocalSocket()
        socket.connectToServer(_server_name())

        if not socket.waitForConnected(SOCKET_TIMEOUT_MS):
            return '{"error": "No running instance found"}'

        socket.write(QByteArray(f'{_DEBUG_PREFIX}{command}'.encode()))
        socket.waitForBytesWritten(SOCKET_TIMEOUT_MS)

        if not socket.waitForReadyRead(SOCKET_TIMEOUT_MS):
            socket.disconnectFromServer()
            return '{"error": "Timed out waiting for response"}'

        raw = socket.readAll().data()
        socket.disconnectFromServer()
        return _decode(raw)

    def start_server(self) -> bool:
        """Start the local socket server to listen for incoming messages.

        If a stale server exists (e.g. from a crash), it will be cleaned up
        and a new server started.

        Returns:
            True if the server started successfully.
        """
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

        if not self._server.listen(_server_name()):
            # Clean up stale socket from a previous crash
            QLocalServer.removeServer(_server_name())
            if not self._server.listen(_server_name()):
                logger.error('Failed to start single-instance server: %s', self._server.errorString())
                return False

        logger.debug('Single-instance server listening as "%s"', _server_name())
        return True

    def _on_new_connection(self) -> None:
        """Handle an incoming connection from another instance."""
        if self._server is None:
            return

        socket = self._server.nextPendingConnection()
        if socket is None:
            return

        if socket.waitForReadyRead(SOCKET_TIMEOUT_MS):
            raw = socket.readAll().data()
            data = _decode(raw)

            if data.startswith(_DEBUG_PREFIX):
                command = data[len(_DEBUG_PREFIX) :]
                if self._debug_handler is not None:
                    response = self._debug_handler(command)
                else:
                    response = '{"error": "debug handler not registered"}'
                socket.write(QByteArray(response.encode('utf-8')))
                socket.waitForBytesWritten(SOCKET_TIMEOUT_MS)
            elif data:
                logger.info('Received message from another instance: %s', data)
                self.uri_received.emit(data)
            else:
                logger.info('Another instance connected (no URI)')

        socket.disconnectFromServer()
