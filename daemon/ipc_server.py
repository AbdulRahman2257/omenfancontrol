"""
ipc_server.py
-------------
Unix domain socket server — broadcasts snapshots to GUI clients,
receives commands and dispatches via on_command callback.

Socket path defined in config: DAEMON_SOCKET_PATH
Protocol: newline-delimited JSON

Message flow:
    daemon → broadcast(snapshot) → all connected clients
    GUI client → sends command JSON → on_command(raw) → reply sent back
"""

import json
import logging
import os
import socket
import threading
from typing import Callable

from config import DAEMON_SOCKET_PATH, SOCKET_MAX_CLIENTS

log = logging.getLogger(__name__)


class IPCServer:
    """Unix domain socket server for daemon-GUI communication.

    Runs an accept loop in a background thread. Each connected client
    gets its own handler thread. Snapshots are broadcast to all connected
    clients every tick, and commands received from clients are dispatched
    via the on_command callback.

    Attributes:
        _on_command: Callback invoked when a GUI client sends a command.
        _clients: List of currently connected client sockets.
        _lock: Threading lock protecting the _clients list.
        _server_sock: The bound Unix domain socket accepting connections.
        _running: Controls the accept loop and client handler loops.

    Example:
        def handle_command(raw: dict) -> dict:
            return {"status": "ok", "msg": "done"}

        server = IPCServer(on_command=handle_command)
        server.start()
        server.broadcast({"cpu_temp": 72.0})
        server.stop()
    """

    def __init__(self, on_command: Callable[[dict], dict] | None = None):
        """Initialise the IPC server.

        Args:
            on_command: Optional callback invoked when a GUI client sends a
                command. Receives the raw decoded dict and must return a
                result dict. If None, commands are silently ignored.
        """
        self._on_command = on_command
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._server_sock: socket.socket | None = None
        self._running = False

    def start(self):
        """Bind the Unix socket and start the accept loop in a background thread.

        Removes any stale socket file left from a previous crash before
        binding. Sets socket permissions to 0o666 so the GUI can connect
        without root.

        Raises:
            OSError: If the socket cannot be bound.
        """
        if os.path.exists(DAEMON_SOCKET_PATH):
            os.unlink(DAEMON_SOCKET_PATH)

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(DAEMON_SOCKET_PATH)
        self._server_sock.listen(SOCKET_MAX_CLIENTS)
        os.chmod(DAEMON_SOCKET_PATH, 0o666)

        self._running = True
        threading.Thread(
            target=self._accept_loop,
            daemon=True,
            name="ipc-accept",
        ).start()
        log.info("IPC server listening on %s", DAEMON_SOCKET_PATH)

    def stop(self):
        """Gracefully shut down the server.

        Closes all connected client sockets, closes the server socket,
        and removes the socket file from the filesystem.
        """
        self._running = False

        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()

        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass

        if os.path.exists(DAEMON_SOCKET_PATH):
            os.unlink(DAEMON_SOCKET_PATH)

        log.info("IPC server stopped")

    def broadcast(self, data: dict):
        """Serialize data to JSON and send to all connected clients.

        Uses newline-delimited JSON framing. Clients that have disconnected
        are detected by a failed send and silently removed from the client list.

        Args:
            data: A JSON-serialisable dict — typically a Snapshot.to_dict().
        """
        message = (json.dumps(data) + "\n").encode()
        dead = []

        with self._lock:
            for client in self._clients:
                try:
                    client.sendall(message)
                except OSError:
                    dead.append(client)

            for client in dead:
                self._clients.remove(client)
                log.info("client disconnected (dead on broadcast)")

    def _accept_loop(self):
        """Background thread that waits for incoming GUI connections.

        For each accepted connection, appends the socket to _clients and
        spawns a dedicated handler thread. Exits cleanly when the server
        socket is closed during stop().
        """
        while self._running:
            try:
                client_sock, _ = self._server_sock.accept()
                log.info("new GUI client connected")

                with self._lock:
                    self._clients.append(client_sock)

                threading.Thread(
                    target=self._handle_client,
                    args=(client_sock,),
                    daemon=True,
                    name="ipc-client",
                ).start()

            except OSError:
                break

    def _handle_client(self, client: socket.socket):
        """Per-client thread that reads and dispatches incoming commands.

        Reads newline-delimited JSON from the client socket, passes each
        complete message to on_command, and sends the result dict back.
        Cleans up and removes the client from _clients on disconnect.

        Args:
            client: The connected client socket to read commands from.
        """
        buffer = ""
        try:
            while self._running:
                chunk = client.recv(4096).decode()
                if not chunk:
                    break

                buffer += chunk

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        raw = json.loads(line)
                        log.debug("command received: %s", raw)

                        if self._on_command:
                            result = self._on_command(raw)
                            reply = (json.dumps(result) + "\n").encode()
                            client.sendall(reply)

                    except json.JSONDecodeError as e:
                        log.warning("bad JSON from client: %s", e)

        except OSError:
            pass
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)
            try:
                client.close()
            except OSError:
                pass
            log.info("client handler exiting")
