"""
test_ipc_client.py
------------------
Tests for IPCClient — uses a real Unix socket at /tmp.
Each test spins up a minimal fake server, runs the client,
then tears everything down cleanly.

Run:
    python -m pytest tests/test_ipc_client.py -v
"""

import json
import os
import socket
import sys
import threading
import time

import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

config.DAEMON_SOCKET_PATH = "/tmp/omen-client-test.sock"

import gui.ipc_client as ipc_client_module  # noqa: E402

ipc_client_module.RECONNECT_INTERVAL = 0.2

from config import DAEMON_SOCKET_PATH  # noqa: E402
from gui.ipc_client import IPCClient  # noqa: E402

FAKE_SNAPSHOT = {
    "timestamp": time.time(),
    "cpu_temp": 72.0,
    "gpu_temp": 48.0,
    "fan1_rpm": 2500,
    "fan2_rpm": 0,
    "cpu_usage": 34.5,
    "power_profile": "balanced",
    "fan_mode": "auto",
    "alerts": [],
    "thresholds": {
        "cpu_warn": 85.0,
        "cpu_critical": 90.0,
        "cpu_recover": 75.0,
        "gpu_warn": 80.0,
        "gpu_critical": 90.0,
    },
}


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    """Create QApplication once for the entire test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def clean_socket():
    """Remove socket file before and after each test."""
    if os.path.exists(DAEMON_SOCKET_PATH):
        os.unlink(DAEMON_SOCKET_PATH)
    yield
    if os.path.exists(DAEMON_SOCKET_PATH):
        os.unlink(DAEMON_SOCKET_PATH)
    time.sleep(0.1)


class FakeServer:
    """Minimal Unix socket server for testing the IPC client.

    Attributes:
        received_commands: List of dicts received from the client.
        _server_sock: The bound listening socket.
        _client_sock: The accepted client connection.
        _thread: Background accept thread.
        _ready: Event set when a client has connected.
    """

    def __init__(self) -> None:
        self.received_commands: list[dict] = []
        self._server_sock: socket.socket | None = None
        self._client_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> "FakeServer":
        """Bind socket and start accept loop in background thread.

        Returns:
            Self for chaining.
        """
        if os.path.exists(DAEMON_SOCKET_PATH):
            os.unlink(DAEMON_SOCKET_PATH)

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(DAEMON_SOCKET_PATH)
        self._server_sock.listen(1)

        self._thread = threading.Thread(
            target=self._accept, daemon=True, name="fake-server"
        )
        self._thread.start()
        return self

    def _accept(self) -> None:
        try:
            self._server_sock.settimeout(3.0)
            self._client_sock, _ = self._server_sock.accept()
            self._client_sock.settimeout(1.0)
            self._ready.set()

            buffer = ""
            while True:
                if self._client_sock is None:
                    break
                try:
                    chunk = self._client_sock.recv(4096).decode()
                    if not chunk:
                        break
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            try:
                                self.received_commands.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                except socket.timeout:
                    continue
        except OSError:
            pass

    def wait_for_client(self, timeout: float = 2.0) -> bool:
        """Wait until a client has connected.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            True if client connected, False if timeout expired.
        """
        return self._ready.wait(timeout)

    def send_snapshot(self, data: dict) -> None:
        """Send a snapshot dict to the connected client.

        Args:
            data: Snapshot dict to serialise and send.
        """
        if self._client_sock:
            self._client_sock.sendall((json.dumps(data) + "\n").encode())

    def send_raw(self, raw: str) -> None:
        """Send a raw string to the connected client.

        Args:
            raw: Raw string to send — can be invalid JSON.
        """
        if self._client_sock:
            self._client_sock.sendall(raw.encode())

    def close_client(self) -> None:
        """Close the client connection to simulate daemon disconnect."""
        if self._client_sock:
            try:
                self._client_sock.close()
            except OSError:
                pass
            self._client_sock = None

    def stop(self) -> None:
        """Close all sockets and clean up the socket file."""
        self.close_client()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if os.path.exists(DAEMON_SOCKET_PATH):
            os.unlink(DAEMON_SOCKET_PATH)


class SignalCollector:
    """Collects Qt signals emitted by IPCClient for test assertions.

    Attributes:
        snapshots: List of snapshot dicts received.
        connected_count: Number of times connected signal fired.
        disconnected_count: Number of times disconnected signal fired.
        errors: List of error strings received.
    """

    def __init__(self, client: IPCClient) -> None:
        """Wire up signal collectors to the client.

        Args:
            client: IPCClient instance whose signals to collect.
        """
        self.snapshots: list[dict] = []
        self.connected_count: int = 0
        self.disconnected_count: int = 0
        self.errors: list[str] = []

        client.snapshot_received.connect(self._on_snapshot)
        client.connected.connect(self._on_connected)
        client.disconnected.connect(self._on_disconnected)
        client.error.connect(self._on_error)

    def _on_snapshot(self, data: dict) -> None:
        self.snapshots.append(data)

    def _on_connected(self) -> None:
        self.connected_count += 1

    def _on_disconnected(self) -> None:
        self.disconnected_count += 1

    def _on_error(self, msg: str) -> None:
        self.errors.append(msg)

    def wait_for_snapshots(self, count: int, timeout: float = 2.0) -> bool:
        """Wait until at least count snapshots have been received.

        Args:
            count: Minimum number of snapshots to wait for.
            timeout: Maximum seconds to wait.

        Returns:
            True if count reached, False if timeout expired.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if len(self.snapshots) >= count:
                return True
            time.sleep(0.05)
        return False

    def wait_for_connected(self, timeout: float = 2.0) -> bool:
        """Wait until the connected signal has fired at least once.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            True if connected, False if timeout expired.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if self.connected_count > 0:
                return True
            time.sleep(0.05)
        return False

    def wait_for_disconnected(self, timeout: float = 2.0) -> bool:
        """Wait until the disconnected signal has fired at least once.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            True if disconnected, False if timeout expired.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if self.disconnected_count > 0:
                return True
            time.sleep(0.05)
        return False

    def wait_for_commands(
        self, server: FakeServer, count: int, timeout: float = 2.0
    ) -> bool:
        """Wait until the server has received at least count commands.

        Args:
            server: FakeServer instance to poll.
            count: Minimum number of commands to wait for.
            timeout: Maximum seconds to wait.

        Returns:
            True if count reached, False if timeout expired.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if len(server.received_commands) >= count:
                return True
            time.sleep(0.05)
        return False


def make_client() -> tuple[IPCClient, SignalCollector]:
    """Create a fresh IPCClient with a SignalCollector attached.

    Returns:
        Tuple of (client, collector).
    """
    client = IPCClient()
    collector = SignalCollector(client)
    return client, collector


def cleanup(client: IPCClient, server: FakeServer) -> None:
    """Stop client and server cleanly.

    Args:
        client: IPCClient to stop.
        server: FakeServer to stop.
    """
    client.stop()
    server.stop()
    time.sleep(0.1)


def test_connected_signal() -> None:
    """connected signal fires when client connects to server."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    assert collector.wait_for_connected(), "connected signal not emitted"
    assert client.is_connected

    cleanup(client, server)


def test_disconnected_signal() -> None:
    """disconnected signal fires when server closes the connection."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    server.close_client()

    assert collector.wait_for_disconnected(), "disconnected signal not emitted"

    cleanup(client, server)


def test_snapshot_received() -> None:
    """snapshot_received emitted with correct data."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    server.wait_for_client()
    server.send_snapshot(FAKE_SNAPSHOT)

    assert collector.wait_for_snapshots(1), "snapshot not received"

    snap = collector.snapshots[0]
    assert snap.get("cpu_temp") == 72.0
    assert snap.get("gpu_temp") == 48.0
    assert snap.get("fan1_rpm") == 2500
    assert snap.get("fan_mode") == "auto"
    assert snap.get("power_profile") == "balanced"
    assert isinstance(snap.get("thresholds"), dict)
    assert isinstance(snap.get("alerts"), list)

    cleanup(client, server)


def test_multiple_snapshots() -> None:
    """Multiple snapshots received in order."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    server.wait_for_client()

    for i in range(3):
        server.send_snapshot({**FAKE_SNAPSHOT, "cpu_temp": 70.0 + i})
        time.sleep(0.05)

    assert collector.wait_for_snapshots(
        3
    ), f"expected 3 snapshots, got {len(collector.snapshots)}"

    temps = [s["cpu_temp"] for s in collector.snapshots[:3]]
    assert temps == [70.0, 71.0, 72.0], f"wrong order: {temps}"

    cleanup(client, server)


def test_bad_json_emits_error() -> None:
    """Bad JSON emits error signal and client keeps running."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    server.wait_for_client()
    server.send_raw("{bad json here}\n")

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if len(collector.errors) > 0:
            break
        time.sleep(0.05)

    assert len(collector.errors) > 0, "error signal not emitted"
    assert client.is_connected

    server.send_snapshot(FAKE_SNAPSHOT)
    assert collector.wait_for_snapshots(1), "snapshot not received after bad JSON"

    cleanup(client, server)


def test_reconnects_after_disconnect() -> None:
    """Client reconnects automatically after server disconnect."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    initial_count = collector.connected_count

    server.close_client()
    collector.wait_for_disconnected()

    server.stop()
    time.sleep(0.1)
    server = FakeServer().start()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if collector.connected_count > initial_count:
            break
        time.sleep(0.1)

    assert (
        collector.connected_count > initial_count
    ), f"did not reconnect, connected_count={collector.connected_count}"

    cleanup(client, server)


def test_send_command() -> None:
    """send_command sends correct JSON to the server."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    server.wait_for_client()
    time.sleep(0.1)

    result = client.send_command("fan", "max")
    assert result is True

    assert collector.wait_for_commands(server, 1), "command not received"

    cmd = server.received_commands[0]
    assert cmd.get("cmd") == "fan"
    assert cmd.get("value") == "max"

    cleanup(client, server)


def test_send_fan() -> None:
    """send_fan sends correct fan command."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    server.wait_for_client()
    time.sleep(0.1)

    client.send_fan("auto")
    assert collector.wait_for_commands(server, 1), "fan command not received"

    cmd = server.received_commands[0]
    assert cmd.get("cmd") == "fan"
    assert cmd.get("value") == "auto"

    cleanup(client, server)


def test_send_power() -> None:
    """send_power sends correct power command."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    server.wait_for_client()
    time.sleep(0.1)

    client.send_power("performance")
    assert collector.wait_for_commands(server, 1), "power command not received"

    cmd = server.received_commands[0]
    assert cmd.get("cmd") == "power"
    assert cmd.get("value") == "performance"

    cleanup(client, server)


def test_send_thresholds() -> None:
    """send_thresholds sends correct thresholds dict."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    server.wait_for_client()
    time.sleep(0.1)

    new_thresholds = {
        "cpu_warn": 83.0,
        "cpu_critical": 88.0,
        "cpu_recover": 70.0,
        "gpu_warn": 78.0,
        "gpu_critical": 88.0,
    }
    client.send_thresholds(new_thresholds)
    assert collector.wait_for_commands(server, 1), "thresholds command not received"

    cmd = server.received_commands[0]
    assert cmd.get("cmd") == "thresholds"
    value = cmd.get("value", {})
    assert value.get("cpu_warn") == 83.0
    assert value.get("cpu_critical") == 88.0
    assert value.get("cpu_recover") == 70.0

    cleanup(client, server)


def test_send_when_not_connected() -> None:
    """send_command returns False when not connected."""
    client, _ = make_client()
    assert client.send_command("fan", "max") is False
    assert not client.is_connected


def test_is_connected_property() -> None:
    """is_connected reflects actual connection state."""
    server = FakeServer().start()
    client, collector = make_client()

    assert not client.is_connected

    client.start()
    collector.wait_for_connected()
    assert client.is_connected

    server.close_client()
    collector.wait_for_disconnected()
    time.sleep(0.1)
    assert not client.is_connected

    cleanup(client, server)


def test_stop_cleans_up() -> None:
    """stop() closes socket and thread exits cleanly."""
    server = FakeServer().start()
    client, collector = make_client()
    client.start()

    collector.wait_for_connected()
    assert client.isRunning()

    client.stop()

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not client.isRunning():
            break
        time.sleep(0.05)

    assert not client.isRunning()
    assert not client.is_connected

    server.stop()
