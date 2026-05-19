"""
daemon.py
---------
Main orchestrator — runs as root via systemd.
Wires together: reader, alerter, commander, ipc_server.

Loop (every DAEMON_READ_INTERVAL seconds):
    1. reader   reads /sys hardware files
    2. alerter  checks thresholds, fires callbacks if needed
    3. snapshot built from readings + alerts + current thresholds
    4. ipc_server broadcasts snapshot to all connected GUI clients

Commands from GUI arrive via ipc_server and are dispatched to commander.

Run:
    sudo python3 -m daemon.daemon
"""

import logging
import signal
import sys
import time

from config import (
    DAEMON_READ_INTERVAL,
    DEFAULT_FAN_MODE,
    DEFAULT_PROFILE,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    LOG_FILE,
)
from models import Alert, Snapshot, Command, CommandResult
from thresholds import Thresholds, load_thresholds, save_thresholds
from daemon.reader import read_all
from daemon.commander import fan_set, set_power_profile, check_system
from daemon.alerter import Alerter
from daemon.ipc_server import IPCServer


def setup_logging():
    """Configure root logger with console and optional file handlers.

    Reads log settings from config:
        LOG_LEVEL: severity threshold (e.g. logging.INFO)
        LOG_FORMAT: message format string
        LOG_DATE_FORMAT: timestamp format string
        LOG_FILE: path to log file, or None for stdout only

    If the log file cannot be opened (e.g. permission denied), a warning
    is printed to stdout and logging continues without the file handler.
    """
    handlers = [logging.StreamHandler(sys.stdout)]
    if LOG_FILE:
        try:
            handlers.append(logging.FileHandler(LOG_FILE))
        except OSError as e:
            print(f"warning: could not open log file {LOG_FILE}: {e}")

    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=handlers,
    )


log = logging.getLogger(__name__)


class Daemon:
    """Main orchestrator that wires together all hardware monitoring components.

    Reads hardware sensor data every DAEMON_READ_INTERVAL seconds, checks
    temperature thresholds via the alerter, builds a Snapshot, and broadcasts
    it to all connected GUI clients via the IPC server. Commands received from
    the GUI are dispatched to the commander for execution.

    Thresholds are loaded from disk on startup and can be updated at runtime
    via the "thresholds" IPC command. Updates take effect on the next tick
    and are persisted to disk immediately.

    Attributes:
        _running: Controls the main loop — set to False to stop the daemon.
        _fan_mode: Tracks the current fan mode ("auto" or "max").
        _profile: Tracks the current power profile.
        _alerter: Stateful threshold watcher that fires callbacks on level
            changes and triggers automatic fan control on critical temps.
        _server: Unix socket server that broadcasts snapshots to GUI clients
            and receives commands from them.

    Example:
        setup_logging()
        daemon = Daemon()
        daemon.start()
    """

    def __init__(self):
        """Initialise the daemon, loading thresholds and wiring components.

        Loads persisted thresholds from disk (falls back to config.py
        defaults if no file exists). Creates the alerter with the loaded
        thresholds and wired callbacks. Creates the IPC server with the
        command dispatcher as its command callback.
        """
        self._running = False
        self._fan_mode = DEFAULT_FAN_MODE
        self._profile = DEFAULT_PROFILE

        thresholds = load_thresholds()
        log.info(
            "thresholds loaded — cpu warn=%.1f critical=%.1f recover=%.1f"
            " | gpu warn=%.1f critical=%.1f",
            thresholds.cpu_warn,
            thresholds.cpu_critical,
            thresholds.cpu_recover,
            thresholds.gpu_warn,
            thresholds.gpu_critical,
        )

        self._alerter = Alerter(
            thresholds=thresholds,
            on_alert=self._on_alert,
            on_fan_action=self._on_fan_action,
        )

        self._server = IPCServer(on_command=self._dispatch_command)

    def start(self, register_signals: bool = True):
        """Start the daemon and block until stop() is called.

        Performs a preflight check to verify system interfaces are accessible.
        Starts the IPC server, registers OS signal handlers, then enters
        the main read, check, broadcast loop.

        Args:
            register_signals: If True, registers SIGTERM and SIGINT handlers
                for graceful shutdown. Set to False in tests to avoid the
                restriction that signal handlers can only be registered from
                the main thread.

        Note:
            Exits the process with code 1 if the system check fails.
        """
        log.info("OMEN daemon starting")

        result = check_system()
        if not result.ok:
            log.error("system check failed: %s", result.message)
            sys.exit(1)
            return
        log.info("system interfaces ready")

        self._server.start()

        if register_signals:
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

        self._running = True
        log.info("daemon running — interval=%.1fs", DAEMON_READ_INTERVAL)
        self._loop()

    def stop(self):
        """Gracefully shut down the daemon.

        Sets _running to False so the main loop exits after the current
        tick completes, then stops the IPC server and closes all client
        connections.
        """
        log.info("daemon stopping")
        self._running = False
        self._server.stop()
        log.info("daemon stopped")

    def _loop(self):
        """Run the main read, check, broadcast loop until stop() is called.

        Uses monotonic time to calculate remaining sleep after each tick,
        keeping the interval consistent even when _tick() takes variable
        time. Tick exceptions are caught and logged without crashing the
        daemon.
        """
        while self._running:
            tick_start = time.monotonic()

            try:
                self._tick()
            except Exception as e:
                log.error("tick error: %s", e, exc_info=True)

            elapsed = time.monotonic() - tick_start
            sleep_for = max(0.0, DAEMON_READ_INTERVAL - elapsed)
            time.sleep(sleep_for)

    def _tick(self):
        """Execute one iteration of the monitoring loop.

        Reads all hardware sensors, passes readings to the alerter for
        threshold checking, builds a Snapshot from the combined data
        including current thresholds, and broadcasts it to all connected
        GUI clients.
        """
        data = read_all()
        alert_dicts = self._alerter.check(data)
        alerts = [Alert.from_dict(a) for a in alert_dicts]
        thresholds = self._alerter.get_thresholds()

        snapshot = Snapshot(
            timestamp=time.time(),
            cpu_temp=data.get("cpu_temp"),
            gpu_temp=data.get("gpu_temp"),
            fan1_rpm=data.get("fan1_rpm"),
            fan2_rpm=data.get("fan2_rpm"),
            cpu_usage=data.get("cpu_usage"),
            power_profile=data.get("power_profile"),
            fan_mode=self._fan_mode,
            alerts=alerts,
            thresholds=thresholds.to_dict(),
            cpu_model=data.get("cpu_model"),
            cpu_cores=data.get("cpu_cores", []),
            gpu_name=data.get("gpu_name"),
            gpu_util=data.get("gpu_util"),
            gpu_vram_used=data.get("gpu_vram_used"),
            gpu_vram_total=data.get("gpu_vram_total"),
            gpu_power=data.get("gpu_power"),
            ram_used=data.get("ram_used"),
            ram_total=data.get("ram_total"),
            ram_percent=data.get("ram_percent"),
        )

        self._server.broadcast(snapshot.to_dict())

    def _dispatch_command(self, raw: dict) -> dict:
        """Parse and execute a command received from a GUI client.

        Deserialises the raw dict into a Command, dispatches it to the
        appropriate handler, updates internal state on success, and returns
        a serialised CommandResult for the client.

        Supported commands:
            fan:        Set fan mode. value must be "max" or "auto".
            power:      Set power profile. value must be "performance",
                        "balanced", or "power-saver".
            thresholds: Update alert thresholds. value must be a dict
                        with any subset of threshold keys.

        Args:
            raw: Decoded JSON dict from the GUI client, expected to contain
                "cmd" and "value" keys matching the Command model.

        Returns:
            A serialised CommandResult dict with "status" and "msg" keys,
            ready to be sent back to the client as JSON.
        """
        try:
            cmd = Command.from_dict(raw)
            log.info("command received: %s", cmd.cmd)

            if cmd.cmd == "fan":
                return self._handle_fan(cmd.value)

            if cmd.cmd == "power":
                return self._handle_power(cmd.value)

            if cmd.cmd == "thresholds":
                return self._handle_thresholds(cmd.value)

            return CommandResult(
                ok=False,
                message=f"unknown command: {cmd.cmd}",
            ).to_dict()

        except Exception as e:
            log.error("command dispatch error: %s", e)
            return CommandResult(ok=False, message=str(e)).to_dict()

    def _handle_fan(self, value: str) -> dict:
        """Execute a fan mode command.

        Args:
            value: Fan mode to apply — "max" or "auto".

        Returns:
            Serialised CommandResult dict.
        """
        result = fan_set(value)
        if result.ok:
            self._fan_mode = value
        return CommandResult(
            ok=result.ok,
            message=result.message,
        ).to_dict()

    def _handle_power(self, value: str) -> dict:
        """Execute a power profile command.

        Args:
            value: Power profile to apply — "performance", "balanced",
                or "power-saver".

        Returns:
            Serialised CommandResult dict.
        """
        result = set_power_profile(value)
        if result.ok:
            self._profile = value
        return CommandResult(
            ok=result.ok,
            message=result.message,
        ).to_dict()

    def _handle_thresholds(self, value) -> dict:
        """Validate, apply, and persist updated thresholds from the GUI.

        Deserialises the value dict into a Thresholds instance, validates
        logical consistency, applies to the alerter immediately, and saves
        to disk so changes survive a daemon restart.

        Args:
            value: Dict containing threshold values sent by the GUI.
                Unknown keys are ignored. Missing keys fall back to the
                current active thresholds rather than config.py defaults,
                so the GUI can send partial updates.

        Returns:
            Serialised CommandResult dict — ok if applied and saved,
            error if validation failed with details of what was wrong.
        """
        if not isinstance(value, dict):
            return CommandResult(
                ok=False,
                message="thresholds value must be a dict",
            ).to_dict()

        current = self._alerter.get_thresholds()
        merged = {**current.to_dict(), **value}
        new_t = Thresholds.from_dict(merged)

        errors = new_t.validate()
        if errors:
            msg = "invalid thresholds: " + "; ".join(errors)
            log.warning(msg)
            return CommandResult(ok=False, message=msg).to_dict()

        self._alerter.update_thresholds(new_t)

        saved = save_thresholds(new_t)
        if not saved:
            log.warning("thresholds applied but could not be saved to disk")
            return CommandResult(
                ok=True,
                message="thresholds applied but not saved to disk",
            ).to_dict()

        return CommandResult(
            ok=True,
            message="thresholds updated and saved",
        ).to_dict()

    def _on_alert(self, alert: Alert):
        """Handle an alert level change fired by the alerter.

        Args:
            alert: The Alert object describing the source, temperature,
                level, and human-readable message.
        """
        log.warning(
            "ALERT [%s] %s: %.1f°C",
            alert.level.value.upper(),
            alert.source.upper(),
            alert.temp,
        )

    def _on_fan_action(self, action: str):
        """Execute an automatic fan speed change requested by the alerter.

        Args:
            action: Fan mode to apply — "max" or "auto".
        """
        log.info("alerter requesting fan: %s", action)
        result = fan_set(action)
        if result.ok:
            self._fan_mode = action
            log.info("fan auto-set to %s by alerter", action)
        else:
            log.error("alerter fan action failed: %s", result.message)

    def _handle_signal(self, signum, frame):
        """Handle OS signals for graceful shutdown.

        Registered for SIGTERM and SIGINT. Delegates to stop().

        Args:
            signum: The signal number received.
            frame: The current stack frame.
        """
        log.info("received signal %s — shutting down", signum)
        self.stop()


if __name__ == "__main__":
    setup_logging()
    daemon = Daemon()
    daemon.start()
