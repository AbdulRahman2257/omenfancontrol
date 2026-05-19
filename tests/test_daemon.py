"""
test_daemon.py
--------------
Unit tests for the Daemon class.

All external dependencies are mocked:
    - commander  (no root needed)
    - reader     (no /sys access needed)
    - ipc_server (tested separately)
    - thresholds (no disk access needed)

Run:
    python -m pytest tests/test_daemon.py -v
"""

import os
import signal
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Alert, AlertLevel, CommandResult  # noqa: E402
from thresholds import Thresholds  # noqa: E402

FAKE_READER_DATA = {
    "cpu_temp": 72.0,
    "gpu_temp": 48.0,
    "fan1_rpm": 2500,
    "fan2_rpm": 0,
    "cpu_usage": 34.5,
    "power_profile": "balanced",
    "profiles_avail": ["performance", "balanced", "power-saver"],
    "cpu_model": "AMD Ryzen 7 4800H with Radeon Graphics",
    "cpu_cores": [
        {"core": i, "usage": 10.0 + i, "freq": 1400 + i * 50} for i in range(16)
    ],
    "gpu_name": "NVIDIA GeForce RTX 2060",
    "gpu_util": 0.0,
    "gpu_vram_used": 4,
    "gpu_vram_total": 6144,
    "gpu_power": 5.7,
    "ram_used": 8.2,
    "ram_total": 14.5,
    "ram_percent": 56.5,
}

FAKE_ALERT_DICT = {
    "level": "warn",
    "source": "cpu",
    "temp": 86.0,
    "message": "CPU temperature warning: 86.0°C",
    "timestamp": time.time(),
}


def make_daemon(
    system_ok: bool = True,
    reader_data: dict | None = None,
    alert_dicts: list | None = None,
) -> tuple:
    """Build a Daemon with all external dependencies mocked.

    Args:
        system_ok: Whether check_system should report success.
        reader_data: Sensor dict returned by read_all.
            Defaults to FAKE_READER_DATA.
        alert_dicts: List of alert dicts returned by alerter.check().
            Defaults to empty list.

    Returns:
        Tuple of (daemon instance, mocks dict).
    """
    from daemon.daemon import Daemon

    reader_data = reader_data or FAKE_READER_DATA
    alert_dicts = alert_dicts or []

    mock_check_system = MagicMock(
        return_value=CommandResult(
            ok=system_ok,
            message="" if system_ok else "system check failed",
        )
    )
    mock_read_all = MagicMock(return_value=reader_data)
    mock_fan_set = MagicMock(return_value=CommandResult(ok=True, message="fan set"))
    mock_set_profile = MagicMock(
        return_value=CommandResult(ok=True, message="profile set")
    )

    mock_alerter_instance = MagicMock()
    mock_alerter_instance.check.return_value = alert_dicts
    mock_alerter_instance.get_thresholds.return_value = Thresholds()
    mock_alerter_class = MagicMock(return_value=mock_alerter_instance)

    mock_server_instance = MagicMock()
    mock_server_class = MagicMock(return_value=mock_server_instance)

    patches = {
        "daemon.daemon.check_system": mock_check_system,
        "daemon.daemon.read_all": mock_read_all,
        "daemon.daemon.fan_set": mock_fan_set,
        "daemon.daemon.set_power_profile": mock_set_profile,
        "daemon.daemon.load_thresholds": MagicMock(return_value=Thresholds()),
        "daemon.daemon.save_thresholds": MagicMock(return_value=True),
        "daemon.daemon.Alerter": mock_alerter_class,
        "daemon.daemon.IPCServer": mock_server_class,
    }

    patchers = [patch(target, mock) for target, mock in patches.items()]
    for p in patchers:
        p.start()

    daemon = Daemon()

    mocks = {
        "check_system": mock_check_system,
        "read_all": mock_read_all,
        "fan_set": mock_fan_set,
        "set_power_profile": mock_set_profile,
        "alerter": mock_alerter_instance,
        "server": mock_server_instance,
        "patchers": patchers,
    }

    return daemon, mocks


def stop_patches(mocks: dict) -> None:
    """Stop all active patches created by make_daemon.

    Args:
        mocks: The mocks dict returned by make_daemon.
    """
    for p in mocks["patchers"]:
        p.stop()


def test_start_fails_if_system_check_fails() -> None:
    """Daemon exits with code 1 if system check fails."""
    daemon, mocks = make_daemon(system_ok=False)
    try:
        with patch("sys.exit") as mock_exit:
            daemon.start(register_signals=False)
            assert mock_exit.call_args[0][0] == 1
            assert not mocks["server"].start.called
    finally:
        stop_patches(mocks)


def test_start_succeeds_and_enters_loop() -> None:
    """Daemon calls server.start() and enters loop when system check passes."""
    daemon, mocks = make_daemon(system_ok=True)

    def run() -> None:
        with patch("sys.exit"):
            daemon.start(register_signals=False)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.2)

    assert mocks["server"].start.called
    assert daemon._running
    assert mocks["read_all"].called
    assert mocks["server"].broadcast.called

    daemon.stop()
    t.join(timeout=2)
    stop_patches(mocks)


def test_tick_builds_valid_snapshot() -> None:
    """_tick() broadcasts a Snapshot with correct sensor values."""
    daemon, mocks = make_daemon()
    daemon._tick()

    assert mocks["server"].broadcast.call_count == 1

    arg = mocks["server"].broadcast.call_args[0][0]
    assert isinstance(arg, dict)
    assert arg.get("cpu_temp") == 72.0
    assert arg.get("gpu_temp") == 48.0
    assert arg.get("fan1_rpm") == 2500
    assert arg.get("fan_mode") == "auto"
    assert arg.get("power_profile") == "balanced"
    assert isinstance(arg.get("alerts"), list)
    assert arg.get("timestamp") is not None
    assert arg.get("cpu_model") is not None
    assert arg.get("gpu_name") is not None
    assert arg.get("ram_used") == 8.2
    assert arg.get("ram_total") == 14.5
    assert arg.get("ram_percent") == 56.5

    stop_patches(mocks)


def test_tick_includes_alerts() -> None:
    """_tick() includes alerts returned by alerter.check() in snapshot."""
    daemon, mocks = make_daemon(alert_dicts=[FAKE_ALERT_DICT])
    daemon._tick()

    arg = mocks["server"].broadcast.call_args[0][0]
    alerts = arg.get("alerts", [])

    assert len(alerts) == 1
    assert alerts[0].get("source") == "cpu"
    assert alerts[0].get("level") == "warn"
    assert alerts[0].get("temp") == 86.0

    stop_patches(mocks)


def test_dispatch_fan_valid() -> None:
    """Fan command with valid mode calls fan_set and updates _fan_mode."""
    daemon, mocks = make_daemon()
    result = daemon._dispatch_command({"cmd": "fan", "value": "max"})

    assert mocks["fan_set"].called
    assert mocks["fan_set"].call_args[0][0] == "max"
    assert daemon._fan_mode == "max"
    assert result.get("status") == "ok"

    stop_patches(mocks)


def test_dispatch_fan_invalid() -> None:
    """Fan command with invalid mode returns error."""
    daemon, mocks = make_daemon()
    mocks["fan_set"].return_value = CommandResult(ok=False, message="invalid fan mode")

    result = daemon._dispatch_command({"cmd": "fan", "value": "turbo"})

    assert result.get("status") == "error"
    assert daemon._fan_mode == "auto"

    stop_patches(mocks)


def test_dispatch_power_valid() -> None:
    """Power command with valid profile updates _profile."""
    daemon, mocks = make_daemon()
    result = daemon._dispatch_command({"cmd": "power", "value": "performance"})

    assert mocks["set_power_profile"].called
    assert mocks["set_power_profile"].call_args[0][0] == "performance"
    assert daemon._profile == "performance"
    assert result.get("status") == "ok"

    stop_patches(mocks)


def test_dispatch_power_invalid() -> None:
    """Power command with invalid profile returns error."""
    daemon, mocks = make_daemon()
    mocks["set_power_profile"].return_value = CommandResult(
        ok=False, message="invalid profile"
    )

    result = daemon._dispatch_command({"cmd": "power", "value": "ludicrous"})

    assert result.get("status") == "error"
    assert daemon._profile == "balanced"

    stop_patches(mocks)


def test_dispatch_thresholds_valid() -> None:
    """Thresholds command applies and saves valid thresholds."""
    daemon, mocks = make_daemon()

    result = daemon._dispatch_command(
        {
            "cmd": "thresholds",
            "value": {
                "cpu_warn": 83.0,
                "cpu_critical": 88.0,
                "cpu_recover": 70.0,
                "gpu_warn": 78.0,
                "gpu_critical": 88.0,
            },
        }
    )

    assert mocks["alerter"].update_thresholds.called
    assert result.get("status") == "ok"

    stop_patches(mocks)


def test_dispatch_thresholds_invalid() -> None:
    """Thresholds command rejects logically invalid values."""
    daemon, mocks = make_daemon()

    result = daemon._dispatch_command(
        {
            "cmd": "thresholds",
            "value": {
                "cpu_warn": 95.0,
                "cpu_critical": 85.0,
                "cpu_recover": 75.0,
                "gpu_warn": 80.0,
                "gpu_critical": 90.0,
            },
        }
    )

    assert result.get("status") == "error"
    assert not mocks["alerter"].update_thresholds.called

    stop_patches(mocks)


def test_dispatch_unknown_command() -> None:
    """Unknown command returns error without crashing."""
    daemon, mocks = make_daemon()
    result = daemon._dispatch_command({"cmd": "reboot", "value": "now"})

    assert result.get("status") == "error"
    assert "reboot" in result.get("msg", "")

    stop_patches(mocks)


def test_on_alert_logs_without_crash() -> None:
    """_on_alert() handles all alert levels without raising."""
    daemon, mocks = make_daemon()

    for level in [AlertLevel.WARN, AlertLevel.CRITICAL, AlertLevel.OK]:
        alert = Alert(
            level=level,
            source="cpu",
            temp=88.0,
            message=f"CPU {level.value}: 88.0°C",
        )
        daemon._on_alert(alert)

    stop_patches(mocks)


def test_on_fan_action_success() -> None:
    """_on_fan_action updates _fan_mode when fan_set succeeds."""
    daemon, mocks = make_daemon()
    daemon._on_fan_action("max")

    assert mocks["fan_set"].called
    assert mocks["fan_set"].call_args[0][0] == "max"
    assert daemon._fan_mode == "max"

    stop_patches(mocks)


def test_on_fan_action_failure() -> None:
    """_on_fan_action leaves _fan_mode unchanged when fan_set fails."""
    daemon, mocks = make_daemon()
    mocks["fan_set"].return_value = CommandResult(ok=False, message="hardware error")

    daemon._on_fan_action("max")

    assert mocks["fan_set"].called
    assert daemon._fan_mode == "auto"

    stop_patches(mocks)


def test_handle_signal_calls_stop() -> None:
    """_handle_signal() delegates to stop() for SIGTERM and SIGINT."""
    daemon, mocks = make_daemon()

    with patch.object(daemon, "stop") as mock_stop:
        daemon._handle_signal(signal.SIGTERM, None)
        assert mock_stop.call_count == 1

        daemon._handle_signal(signal.SIGINT, None)
        assert mock_stop.call_count == 2

    stop_patches(mocks)


def test_stop_sets_running_false() -> None:
    """stop() sets _running to False and calls server.stop()."""
    daemon, mocks = make_daemon()
    daemon._running = True

    daemon.stop()

    assert not daemon._running
    assert mocks["server"].stop.called

    stop_patches(mocks)
