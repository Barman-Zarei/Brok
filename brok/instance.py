"""Single-instance activation (local socket) and the macOS dock-reopen hook."""

from __future__ import annotations

import logging

from PySide2 import QtCore, QtNetwork

logger = logging.getLogger(__name__)


def activate_running_instance(name: str) -> bool:
    """Ask an already-running brok (via its local socket) to show its window.

    Returns True if a running instance answered. This is the safety net for
    hiding the avatar to a system tray that some Linux panels don't render: a second
    launch just raises the existing cat instead of doing nothing.
    """
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def start_activation_server(name: str, window):
    """Listen for a second launch and raise ``window`` when one arrives."""
    QtNetwork.QLocalServer.removeServer(name)  # clear a socket left by a crash
    server = QtNetwork.QLocalServer(window)
    if not server.listen(name):
        logger.warning("Single-instance socket unavailable: %s", server.errorString())
        return None

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
        window.show()
        window.raise_()
        window.activateWindow()
        logger.info("Second launch — raising the existing cat")

    server.newConnection.connect(on_connection)
    return server


def install_macos_reopen(app, window):
    """Bring a tray-hidden cat back when the app is reactivated on macOS.

    macOS re-launches don't start a second process — LaunchServices just
    activates the already-running app — so the single-instance socket never
    fires there and clicking the Dock icon otherwise does nothing. Show the
    window again whenever the app becomes active while hidden.
    """
    def on_state(state) -> None:
        if state == QtCore.Qt.ApplicationState.ApplicationActive and not window.isVisible():
            window.show()
            window.raise_()

    app.applicationStateChanged.connect(on_state)
