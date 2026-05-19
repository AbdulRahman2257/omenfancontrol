"""
test_ipc_server.py
------------------
Tests for IPCServer — uses a real Unix socket at /tmp.
Each test spins up a fresh server and tears down cleanly.

Run:
    python -m pytest tests/test_ipc_server.py -v
"""

import json
import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

config.DAEMON_SOCKET_PATH = "/tmp/omen-server-test.sock"

from config import DAEMON_SOCKET_PATH  # noqa: E402
from daemon.ipc_server import IPCServer  # noqa: E402

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


def connect_client() -> socket.socket:
    """Open a fresh client connection to the IPC socket.

    Returns:
        Connected client socket with 2 second timeout.
    """
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(DAEMON_SOCKET_PATH)
    s.settimeout(2.0)
    return s


def wait_for_socket(timeout: float = 2.0) -> bool:
    """Poll until the socket file appears or timeout expires.

    Args:
        timeout: Maximum seconds to wait.

    Returns:
        True if socket file appeared, False if timeout expired.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(DAEMON_SOCKET_PATH):
            return True
        time.sleep(0.05)
    return False


def wait_for_clients(server: IPCServer, count: int, timeout: float = 2.0) -> bool:
    """Poll until server._clients reaches expected count.

    Args:
        server: The IPCServer instance to inspect.
        count: Expected number of connected clients.
        timeout: Maximum seconds to wait.

    Returns:
        True if client count reached, False if timeout expired.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with server._lock:
            if len(server._clients) == count:
                return True
        time.sleep(0.05)
    return False


def read_json(client: socket.socket) -> dict | None:
    """Read one newline-delimited JSON message from a socket.

    Args:
        client: Connected client socket.

    Returns:
        Decoded dict, or None on timeout or decode error.
    """
    try:
        raw = client.recv(4096).decode()
        return json.loads(raw.strip())
    except (socket.timeout, json.JSONDecodeError):
        return None


def send_command(client: socket.socket, cmd: str, value: str) -> dict | None:
    """Send a command dict and read back the JSON reply.

    Args:
        client: Connected client socket.
        cmd: Command name e.g. "fan".
        value: Command value e.g. "max".

    Returns:
        Decoded reply dict, or None if no reply received.
    """
    payload = json.dumps({"cmd": cmd, "value": value}) + "\n"
    client.sendall(payload.encode())
    try:
        raw = client.recv(4096).decode()
        return json.loads(raw.strip())
    except (socket.timeout, json.JSONDecodeError):
        return None


def cleanup_socket() -> None:
    """Remove the test socket file if it exists."""
    if os.path.exists(DAEMON_SOCKET_PATH):
        os.unlink(DAEMON_SOCKET_PATH)


@pytest.fixture(autouse=True)
def clean_socket():
    """Remove socket file before and after each test."""
    cleanup_socket()
    yield
    cleanup_socket()
    time.sleep(0.1)


def test_start_stop() -> None:
    """Server creates socket file on start and removes it on stop."""
    server = IPCServer()
    server.start()

    assert wait_for_socket(), "socket file not created"
    assert os.path.exists(DAEMON_SOCKET_PATH)

    server.stop()
    time.sleep(0.1)

    assert not os.path.exists(DAEMON_SOCKET_PATH)
    assert not server._running
    assert len(server._clients) == 0


def test_client_connect() -> None:
    """A connecting client appears in server._clients."""
    server = IPCServer()
    server.start()
    wait_for_socket()

    client = connect_client()
    assert wait_for_clients(server, 1), "client not registered"

    with server._lock:
        count = len(server._clients)
    assert count == 1

    client.close()
    server.stop()


def test_broadcast_received() -> None:
    """Client receives the exact snapshot dict that was broadcast."""
    server = IPCServer()
    server.start()
    wait_for_socket()

    client = connect_client()
    wait_for_clients(server, 1)

    server.broadcast(FAKE_SNAPSHOT)
    received = read_json(client)

    assert received is not None
    assert received.get("cpu_temp") == FAKE_SNAPSHOT["cpu_temp"]
    assert received.get("gpu_temp") == FAKE_SNAPSHOT["gpu_temp"]
    assert received.get("fan1_rpm") == FAKE_SNAPSHOT["fan1_rpm"]
    assert received.get("fan_mode") == FAKE_SNAPSHOT["fan_mode"]
    assert isinstance(received.get("alerts"), list)
    assert isinstance(received.get("thresholds"), dict)

    client.close()
    server.stop()


def test_command_dispatch() -> None:
    """Commands from client reach on_command and reply is sent back."""
    calls: list[dict] = []

    def handler(raw: dict) -> dict:
        calls.append(raw)
        cmd = raw.get("cmd")
        value = raw.get("value")
        if cmd == "fan" and value in ("max", "auto"):
            return {"status": "ok", "msg": f"fan set to {value}"}
        return {"status": "error", "msg": "unknown"}

    server = IPCServer(on_command=handler)
    server.start()
    wait_for_socket()

    client = connect_client()
    wait_for_clients(server, 1)
    time.sleep(0.1)

    reply = send_command(client, "fan", "max")
    time.sleep(0.1)

    assert len(calls) >= 1
    assert reply is not None
    assert reply.get("status") == "ok"
    assert reply.get("msg") == "fan set to max"

    client.close()
    server.stop()


def test_multiple_clients_broadcast() -> None:
    """Broadcast reaches all connected clients simultaneously."""
    server = IPCServer()
    server.start()
    wait_for_socket()

    clients = [connect_client() for _ in range(3)]
    wait_for_clients(server, 3)

    server.broadcast(FAKE_SNAPSHOT)
    received = [read_json(c) for c in clients]

    assert all(r is not None for r in received)
    assert all(r.get("cpu_temp") == 72.0 for r in received if r)

    for c in clients:
        c.close()
    server.stop()


def test_dead_client_cleanup() -> None:
    """A disconnected client is removed from _clients on next broadcast."""
    server = IPCServer()
    server.start()
    wait_for_socket()

    client = connect_client()
    wait_for_clients(server, 1)

    client.close()
    time.sleep(0.1)

    server.broadcast(FAKE_SNAPSHOT)
    time.sleep(0.1)

    with server._lock:
        remaining = len(server._clients)
    assert remaining == 0, f"expected 0 clients, got {remaining}"

    server.stop()


def test_bad_json_resilience() -> None:
    """Server survives and continues after receiving malformed JSON."""
    calls: list[dict] = []

    def handler(raw: dict) -> dict:
        calls.append(raw)
        return {"status": "ok", "msg": "ok"}

    server = IPCServer(on_command=handler)
    server.start()
    wait_for_socket()

    client = connect_client()
    wait_for_clients(server, 1)
    time.sleep(0.1)

    client.sendall(b"{bad json}\n")
    time.sleep(0.1)

    assert server._running

    reply = send_command(client, "fan", "auto")
    time.sleep(0.1)
    assert reply is not None
    assert reply.get("status") == "ok"

    client.close()
    server.stop()


def test_stop_disconnects_all_clients() -> None:
    """All clients are disconnected when server stops."""
    server = IPCServer()
    server.start()
    wait_for_socket()

    clients = [connect_client() for _ in range(2)]
    wait_for_clients(server, 2)

    server.stop()
    time.sleep(0.2)

    for c in clients:
        try:
            c.settimeout(1.0)
            data = c.recv(1024)
            assert data == b""
        except OSError:
            pass

    assert not os.path.exists(DAEMON_SOCKET_PATH)
