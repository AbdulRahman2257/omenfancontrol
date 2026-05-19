"""
models.py
---------
Pure data structures shared across the entire application.
No logic, no side effects, no hardware access.

Imported by:
    daemon/alerter.py    — Alert, AlertLevel
    daemon/daemon.py     — Snapshot
    daemon/ipc_server.py — Snapshot
    gui/                 — all models for deserialising received data

"""

import time
from dataclasses import dataclass, field
from enum import Enum


class AlertLevel(Enum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"

    @staticmethod
    def from_str(value: str) -> "AlertLevel":
        """Parse from string — safe, returns OK on unknown value."""
        try:
            return AlertLevel(value)
        except ValueError:
            return AlertLevel.OK


@dataclass
class Alert:
    """
    A single alert event produced by the alerter.
    Included in Snapshot.alerts and passed to on_alert callbacks.
    """

    level: AlertLevel
    source: str  # "cpu" or "gpu"
    temp: float  # temperature that triggered the alert
    message: str  # human readable description
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "source": self.source,
            "temp": self.temp,
            "message": self.message,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "Alert":
        """Reconstruct an Alert from a dict — used by GUI after JSON decode."""
        return Alert(
            level=AlertLevel.from_str(d.get("level", "ok")),
            source=d.get("source", ""),
            temp=d.get("temp", 0.0),
            message=d.get("message", ""),
            timestamp=d.get("timestamp", time.time()),
        )


# snapshot model


@dataclass
class Snapshot:
    # add ram_used, ram_total, ram_percent
    timestamp: float
    cpu_temp: float | None = None
    gpu_temp: float | None = None
    fan1_rpm: int | None = None
    fan2_rpm: int | None = None
    cpu_usage: float | None = None
    power_profile: str | None = None
    fan_mode: str = "auto"
    alerts: list[Alert] = field(default_factory=list)
    thresholds: dict = field(default_factory=dict)
    cpu_model: str | None = None
    cpu_cores: list = field(default_factory=list)
    gpu_name: str | None = None
    gpu_util: float | None = None
    gpu_vram_used: int | None = None
    gpu_vram_total: int | None = None
    gpu_power: float | None = None
    ram_used: float | None = None
    ram_total: float | None = None
    ram_percent: float | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cpu_temp": self.cpu_temp,
            "gpu_temp": self.gpu_temp,
            "fan1_rpm": self.fan1_rpm,
            "fan2_rpm": self.fan2_rpm,
            "cpu_usage": self.cpu_usage,
            "power_profile": self.power_profile,
            "fan_mode": self.fan_mode,
            "alerts": [a.to_dict() for a in self.alerts],
            "thresholds": self.thresholds,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "gpu_name": self.gpu_name,
            "gpu_util": self.gpu_util,
            "gpu_vram_used": self.gpu_vram_used,
            "gpu_vram_total": self.gpu_vram_total,
            "gpu_power": self.gpu_power,
            "ram_used": self.ram_used,
            "ram_total": self.ram_total,
            "ram_percent": self.ram_percent,
        }

    @staticmethod
    def from_dict(d: dict) -> "Snapshot":
        return Snapshot(
            timestamp=d.get("timestamp", time.time()),
            cpu_temp=d.get("cpu_temp"),
            gpu_temp=d.get("gpu_temp"),
            fan1_rpm=d.get("fan1_rpm"),
            fan2_rpm=d.get("fan2_rpm"),
            cpu_usage=d.get("cpu_usage"),
            power_profile=d.get("power_profile"),
            fan_mode=d.get("fan_mode", "auto"),
            alerts=[Alert.from_dict(a) for a in d.get("alerts", [])],
            thresholds=d.get("thresholds", {}),
            cpu_model=d.get("cpu_model"),
            cpu_cores=d.get("cpu_cores", []),
            gpu_name=d.get("gpu_name"),
            gpu_util=d.get("gpu_util"),
            gpu_vram_used=d.get("gpu_vram_used"),
            gpu_vram_total=d.get("gpu_vram_total"),
            gpu_power=d.get("gpu_power"),
            ram_used=d.get("ram_used"),
            ram_total=d.get("ram_total"),
            ram_percent=d.get("ram_percent"),
        )


# command models


@dataclass
class Command:
    """
    A command sent from GUI to daemon over the socket.
    Example: Command(cmd="fan", value="max")
    """

    cmd: str  # "fan" or "power"
    value: str  # "max"/"auto" for fan, "power-saver"/"balanced"/"performance" for power

    def to_dict(self) -> dict:
        return {"cmd": self.cmd, "value": self.value}

    @staticmethod
    def from_dict(d: dict) -> "Command":
        return Command(cmd=d.get("cmd", ""), value=d.get("value", ""))


@dataclass
class CommandResult:
    """
    Result of a command sent back from daemon to GUI.
    """

    ok: bool
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": "ok" if self.ok else "error",
            "msg": self.message,
        }

    @staticmethod
    def from_dict(d: dict) -> "CommandResult":
        return CommandResult(
            ok=d.get("status") == "ok",
            message=d.get("msg", ""),
        )
