"""
thresholds.py
-------------
Load and save user-configured alert thresholds.

Thresholds are stored as JSON at THRESHOLDS_PATH.
On first run the file does not exist — defaults from config.py are used.
The daemon writes this file when the GUI sends updated thresholds.
The daemon reads this file on startup to restore the last saved thresholds.

Format:
    {
        "cpu_warn":     85.0,
        "cpu_critical": 90.0,
        "cpu_recover":  75.0,
        "gpu_warn":     80.0,
        "gpu_critical": 90.0
    }
"""

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

from config import (
    ALERT_CPU_WARN,
    ALERT_CPU_CRITICAL,
    ALERT_CPU_RECOVER,
    ALERT_GPU_WARN,
    ALERT_GPU_CRITICAL,
    THRESHOLDS_PATH,
)

log = logging.getLogger(__name__)


@dataclass
class Thresholds:
    """
    User-configurable temperature thresholds for alert and fan control.

    All values are in degrees Celsius. The cpu_critical threshold is the
    point at which the daemon automatically sets the fan to maximum speed.
    The cpu_recover threshold is the point at which the fan is restored to
    automatic control after a critical event.

    Attributes:
        cpu_warn: CPU temperature at which a warning alert fires.
        cpu_critical: CPU temperature at which a critical alert fires and
            fan is set to maximum.
        cpu_recover: CPU temperature below which the fan is restored to
            auto after a critical event. Must be lower than cpu_warn to
            avoid flapping.
        gpu_warn: GPU temperature at which a warning alert fires.
        gpu_critical: GPU temperature at which a critical alert fires.

    Example:
        t = Thresholds(cpu_warn=83.0, cpu_critical=88.0, cpu_recover=70.0,
                       gpu_warn=78.0, gpu_critical=88.0)
    """

    cpu_warn: float = ALERT_CPU_WARN
    cpu_critical: float = ALERT_CPU_CRITICAL
    cpu_recover: float = ALERT_CPU_RECOVER
    gpu_warn: float = ALERT_GPU_WARN
    gpu_critical: float = ALERT_GPU_CRITICAL

    def to_dict(self) -> dict:
        """
        Serialise thresholds to a JSON-safe dict.

        Returns:
            Dict with float values for all five threshold fields.
        """
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Thresholds":
        """
        Deserialise thresholds from a dict, falling back to defaults.

        Unknown keys are ignored. Missing keys fall back to the config.py
        defaults so partial files are safe to load.

        Args:
            d: Dict containing threshold values, typically decoded from JSON.

        Returns:
            Thresholds instance with values from d, defaults for missing keys.
        """
        return Thresholds(
            cpu_warn=float(d.get("cpu_warn", ALERT_CPU_WARN)),
            cpu_critical=float(d.get("cpu_critical", ALERT_CPU_CRITICAL)),
            cpu_recover=float(d.get("cpu_recover", ALERT_CPU_RECOVER)),
            gpu_warn=float(d.get("gpu_warn", ALERT_GPU_WARN)),
            gpu_critical=float(d.get("gpu_critical", ALERT_GPU_CRITICAL)),
        )

    def validate(self) -> list[str]:
        """
        Check that threshold values are logically consistent.

        Rules:
            - cpu_recover must be below cpu_warn (avoid flapping)
            - cpu_warn must be below cpu_critical
            - gpu_warn must be below gpu_critical
            - all values must be between 0 and 120°C

        Returns:
            List of error strings. Empty list means thresholds are valid.
        """
        errors = []

        if not (0 < self.cpu_warn < 120):
            errors.append(f"cpu_warn out of range: {self.cpu_warn}")
        if not (0 < self.cpu_critical < 120):
            errors.append(f"cpu_critical out of range: {self.cpu_critical}")
        if not (0 < self.cpu_recover < 120):
            errors.append(f"cpu_recover out of range: {self.cpu_recover}")
        if not (0 < self.gpu_warn < 120):
            errors.append(f"gpu_warn out of range: {self.gpu_warn}")
        if not (0 < self.gpu_critical < 120):
            errors.append(f"gpu_critical out of range: {self.gpu_critical}")

        if self.cpu_recover >= self.cpu_warn:
            errors.append(
                f"cpu_recover ({self.cpu_recover}) must be below "
                f"cpu_warn ({self.cpu_warn})"
            )
        if self.cpu_warn >= self.cpu_critical:
            errors.append(
                f"cpu_warn ({self.cpu_warn}) must be below "
                f"cpu_critical ({self.cpu_critical})"
            )
        if self.gpu_warn >= self.gpu_critical:
            errors.append(
                f"gpu_warn ({self.gpu_warn}) must be below "
                f"gpu_critical ({self.gpu_critical})"
            )

        return errors


#  load / save


def load_thresholds() -> Thresholds:
    """
    Load thresholds from the JSON file, falling back to defaults.

    If the file does not exist, returns a Thresholds instance with
    config.py defaults — this is the normal state on first run.
    If the file is corrupt or unreadable, logs a warning and returns
    defaults rather than crashing the daemon.

    Returns:
        Thresholds loaded from file, or defaults if file is missing
        or unreadable.
    """
    path = Path(THRESHOLDS_PATH)

    if not path.exists():
        log.info("no thresholds file found at %s — using defaults", path)
        return Thresholds()

    try:
        raw = path.read_text()
        data = json.loads(raw)
        t = Thresholds.from_dict(data)
        log.info("thresholds loaded from %s", path)
        return t

    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.warning("could not load thresholds from %s: %s — using defaults", path, e)
        return Thresholds()


def save_thresholds(t: Thresholds) -> bool:
    """
    Save thresholds to the JSON file.

    Creates the parent directory if it does not exist. Writes atomically
    by validating before writing so a corrupt partial write is avoided.

    Args:
        t: Thresholds instance to persist.

    Returns:
        True if saved successfully, False if an OS error occurred.
    """
    path = Path(THRESHOLDS_PATH)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(t.to_dict(), indent=2))
        log.info("thresholds saved to %s", path)
        return True

    except OSError as e:
        log.error("could not save thresholds to %s: %s", path, e)
        return False
