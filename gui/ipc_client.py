"""
gui/ipc_client.py
-----------------
Qt-based IPC client that connects to the daemon socket and receives
snapshots in a background thread.

Signals:
    snapshot_received(dict) — new snapshot arrived from daemon
    connected()             — socket connection established
    disconnected()          — socket connection lost
    error(str)              — unrecoverable error occurred

Reconnects automatically every RECONNECT_INTERVAL seconds if the
daemon is not running or the connection drops.
"""

import json
import logging
import socket
import threading

from PyQt6.QtCore import QThread, pyqtSignal

from config import DAEMON_SOCKET_PATH

log = logging.getLogger(__name__)

RECONNECT_INTERVAL: float = 2.0
RECV_BUFFER: int = 4096


class IPCClient(QThread):
    """Background thread that maintains a connection to the daemon socket.

    Reads newline-delimited JSON snapshots from the daemon and emits
    snapshot_received for each one. Automatically reconnects if the
    connection drops. Commands are sent synchronously from whatever
    thread calls send_command().

    Signals:
        snapshot_received: Emitted with the decoded snapshot dict.
        connected: Emitted when the socket connection is established.
        disconnected: Emitted when the socket connection is lost.
        error: Emitted with an error message on decode failure.

    Attributes:
        _running: Controls the reconnect loop.
        _sock: The active socket connection, or None if disconnected.

    Example:
        client = IPCClient()
        client.snapshot_received.connect(window.update_display)
        client.start()
    """

    snapshot_received = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        """Initialise the IPC client thread.

        Args:
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._running: bool = False
        self._sock: socket.socket | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background connection thread."""
        self._running = True
        self._stop_event.clear()
        super().start()

    def stop(self) -> None:
        """Stop the background thread and close the socket.

        Waits up to 3 seconds for the thread to finish.
        """
        self._running = False
        self._stop_event.set()
        self._close_socket()
        self.quit()
        self.wait(3000)

    def run(self) -> None:
        """QThread entry point — reconnect loop.

        Repeatedly attempts to connect to the daemon socket. On each
        successful connection, enters the read loop until the connection
        drops or stop() is called.
        """
        while self._running:
            if self._connect():
                self._read_loop()

            if self._running:
                log.debug("reconnecting in %.1fs...", RECONNECT_INTERVAL)
                self._stop_event.wait(RECONNECT_INTERVAL)

    def _connect(self) -> bool:
        """Attempt to connect to the daemon Unix socket.

        Returns:
            True if the connection was established, False otherwise.
        """
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(DAEMON_SOCKET_PATH)
            sock.settimeout(5.0)
            self._sock = sock
            log.info("connected to daemon at %s", DAEMON_SOCKET_PATH)
            self.connected.emit()
            return True
        except (OSError, ConnectionRefusedError) as e:
            log.debug("connection failed: %s", e)
            return False

    def _close_socket(self) -> None:
        """Close the active socket if open. Safe to call from any thread."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _read_loop(self) -> None:
        """Read snapshots from the daemon until the connection drops.

        Processes complete newline-delimited JSON messages as they arrive.
        Emits snapshot_received for each valid message.
        """
        buffer = ""
        try:
            while self._running:
                try:
                    chunk = self._sock.recv(RECV_BUFFER).decode()
                except socket.timeout:
                    continue

                if not chunk:
                    log.info("daemon disconnected")
                    break

                buffer += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    self._process_message(line)

        except OSError as e:
            if self._running:
                log.warning("socket error: %s", e)
        finally:
            self._close_socket()
            if self._running:
                self.disconnected.emit()

    def _process_message(self, line: str) -> None:
        """Parse and emit a single JSON message from the daemon.

        Args:
            line: A single stripped JSON string without the newline terminator.
        """
        try:
            data = json.loads(line)
            self.snapshot_received.emit(data)
        except json.JSONDecodeError as e:
            log.warning("bad JSON from daemon: %s", e)
            self.error.emit(f"bad JSON: {e}")

    def send_command(self, cmd: str, value) -> bool:
        """Send a command to the daemon over the socket.

        Args:
            cmd: Command name — "fan", "power", or "thresholds".
            value: Command value. String for fan/power, dict for thresholds.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._sock:
            log.warning("send_command called but not connected")
            return False

        try:
            payload = json.dumps({"cmd": cmd, "value": value}) + "\n"
            self._sock.sendall(payload.encode())
            log.debug("sent command: %s %s", cmd, value)
            return True
        except OSError as e:
            log.warning("send_command failed: %s", e)
            return False

    def send_fan(self, mode: str) -> bool:
        """Send a fan mode command to the daemon.

        Args:
            mode: Fan mode — "max" or "auto".

        Returns:
            True if sent successfully, False otherwise.
        """
        return self.send_command("fan", mode)

    def send_power(self, profile: str) -> bool:
        """Send a power profile command to the daemon.

        Args:
            profile: Power profile — "performance", "balanced", or "power-saver".

        Returns:
            True if sent successfully, False otherwise.
        """
        return self.send_command("power", profile)

    def send_thresholds(self, thresholds: dict) -> bool:
        """Send updated thresholds to the daemon.

        Args:
            thresholds: Dict with any subset of threshold keys.
                Values in degrees Celsius.

        Returns:
            True if sent successfully, False otherwise.
        """
        return self.send_command("thresholds", thresholds)

    @property
    def is_connected(self) -> bool:
        """True if the socket is currently connected to the daemon."""
        return self._sock is not None
