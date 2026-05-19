"""
alerter.py
----------
Watches hardware readings against configurable thresholds.
Fires alerts when temps cross warning or critical levels.
Auto-switches fan to max on critical CPU temp, restores when safe.

Thresholds can be updated at runtime via update_thresholds().
Changes take effect on the next check() call.

No side effects on import — call Alerter.check(data) every second
from the daemon main loop.
"""

import logging
import threading
from typing import Callable

from models import Alert, AlertLevel
from thresholds import Thresholds

log = logging.getLogger(__name__)


class Alerter:
    """Stateful temperature threshold watcher with runtime-configurable limits.

    Tracks previous alert levels to avoid spamming the same alert every
    second — only fires callbacks when the level changes (ok to warn,
    warn to critical). Thresholds can be replaced at any time via
    update_thresholds(); the change takes effect on the next check() call.

    Attributes:
        on_alert: Optional callback fired when an alert level changes.
        on_fan_action: Optional callback fired when fan speed should change.
        _thresholds: Current Thresholds instance used for comparisons.
        _lock: Protects _thresholds against concurrent read/write between
            the daemon loop thread and the IPC command thread.
        _cpu_level: Last known CPU alert level, used to detect changes.
        _gpu_level: Last known GPU alert level, used to detect changes.
        _fan_auto_maxed: True if this alerter auto-maxed the fan, so it
            knows to restore it on recovery.

    Example:
        alerter = Alerter(
            thresholds=Thresholds(),
            on_alert=lambda alert: print(alert.message),
            on_fan_action=lambda action: fan_set(action),
        )
        alerts = alerter.check({"cpu_temp": 91.0, "gpu_temp": 55.0})
        alerter.update_thresholds(Thresholds(cpu_critical=88.0))
    """

    def __init__(
        self,
        thresholds: Thresholds,
        on_alert: Callable[[Alert], None] | None = None,
        on_fan_action: Callable[[str], None] | None = None,
    ):
        """Initialise the alerter with thresholds and optional callbacks.

        Args:
            thresholds: Initial Thresholds instance defining warn, critical,
                and recover temperatures for CPU and GPU.
            on_alert: Optional callback invoked when an alert level changes.
                Receives the Alert object describing the event.
            on_fan_action: Optional callback invoked when the alerter wants
                to change fan speed. Receives "max" or "auto".
        """
        self.on_alert = on_alert
        self.on_fan_action = on_fan_action
        self._thresholds = thresholds
        self._lock = threading.Lock()
        self._cpu_level: AlertLevel = AlertLevel.OK
        self._gpu_level: AlertLevel = AlertLevel.OK
        self._fan_auto_maxed: bool = False

    def check(self, data: dict) -> list[dict]:
        """Check latest readings against current thresholds.

        Compares cpu_temp and gpu_temp from data against the current
        Thresholds instance. Only fires callbacks when alert level changes.
        Thread-safe — acquires lock to read thresholds.

        Args:
            data: Dict with keys cpu_temp and gpu_temp (floats or None).
                Typically the dict returned by reader.read_all().

        Returns:
            List of alert dicts to include in the broadcast snapshot.
            Empty if no level changes occurred this tick.
        """
        alerts = []

        with self._lock:
            t = self._thresholds

        cpu_temp = data.get("cpu_temp")
        gpu_temp = data.get("gpu_temp")

        if cpu_temp is not None:
            alert = self._check_cpu(cpu_temp, t)
            if alert:
                alerts.append(alert.to_dict())

        if gpu_temp is not None:
            alert = self._check_gpu(gpu_temp, t)
            if alert:
                alerts.append(alert.to_dict())

        return alerts

    def update_thresholds(self, thresholds: Thresholds):
        """Replace the active thresholds — takes effect on the next check().

        Thread-safe — acquires lock so the daemon loop thread cannot read
        a partially updated thresholds object. Does not reset alert state,
        so existing warn/critical levels are preserved across the update.

        Args:
            thresholds: New Thresholds instance to use from the next
                check() call onwards.
        """
        with self._lock:
            self._thresholds = thresholds
        log.info(
            "thresholds updated — cpu warn=%.1f critical=%.1f recover=%.1f"
            " | gpu warn=%.1f critical=%.1f",
            thresholds.cpu_warn,
            thresholds.cpu_critical,
            thresholds.cpu_recover,
            thresholds.gpu_warn,
            thresholds.gpu_critical,
        )

    def get_thresholds(self) -> Thresholds:
        """Return a snapshot of the current thresholds.

        Thread-safe — acquires lock before reading. Used by the daemon
        to include current thresholds in the broadcast snapshot so the
        GUI can display what values are active.

        Returns:
            The current Thresholds instance.
        """
        with self._lock:
            return self._thresholds

    def reset(self):
        """Reset all alert states.

        Resets CPU and GPU alert levels to OK and clears the fan auto-max
        flag. Does not modify thresholds.
        """
        self._cpu_level = AlertLevel.OK
        self._gpu_level = AlertLevel.OK
        self._fan_auto_maxed = False
        log.info("alerter reset")

    def _check_cpu(self, temp: float, t: Thresholds) -> Alert | None:
        """Check CPU temp against thresholds, return Alert if level changed.

        Also triggers fan callbacks: sets fan to max on critical, restores
        to auto when temperature recovers below cpu_recover.

        Args:
            temp: Current CPU temperature in degrees Celsius.
            t: Thresholds snapshot to compare against.

        Returns:
            Alert if the level changed since last check, None otherwise.
        """
        new_level = self._cpu_threshold(temp, t)

        if new_level == self._cpu_level:
            return None

        old_level = self._cpu_level
        self._cpu_level = new_level

        alert = self._make_alert("cpu", temp, new_level)
        log.info(
            "CPU alert: %s -> %s (%.1f°C)",
            old_level.value,
            new_level.value,
            temp,
        )

        if new_level == AlertLevel.CRITICAL and not self._fan_auto_maxed:
            log.warning("CPU critical — auto-switching fan to MAX")
            self._fan_auto_maxed = True
            if self.on_fan_action:
                self.on_fan_action("max")

        elif new_level == AlertLevel.OK and self._fan_auto_maxed:
            log.info("CPU recovered — restoring fan to AUTO")
            self._fan_auto_maxed = False
            if self.on_fan_action:
                self.on_fan_action("auto")

        if self.on_alert:
            self.on_alert(alert)

        return alert

    def _check_gpu(self, temp: float, t: Thresholds) -> Alert | None:
        """Check GPU temp against thresholds, return Alert if level changed.

        Args:
            temp: Current GPU temperature in degrees Celsius.
            t: Thresholds snapshot to compare against.

        Returns:
            Alert if the level changed since last check, None otherwise.
        """
        new_level = self._gpu_threshold(temp, t)

        if new_level == self._gpu_level:
            return None

        old_level = self._gpu_level
        self._gpu_level = new_level

        alert = self._make_alert("gpu", temp, new_level)
        log.info(
            "GPU alert: %s -> %s (%.1f°C)",
            old_level.value,
            new_level.value,
            temp,
        )

        if self.on_alert:
            self.on_alert(alert)

        return alert

    def _cpu_threshold(self, temp: float, t: Thresholds) -> AlertLevel:
        """Map CPU temperature to an alert level using current thresholds.

        Uses a recover threshold to avoid flapping around the warn boundary.
        Once in warn or critical, stays there until temp drops below
        cpu_recover.

        Args:
            temp: Current CPU temperature in degrees Celsius.
            t: Thresholds to use for comparison.

        Returns:
            The AlertLevel that applies at this temperature.
        """
        if temp >= t.cpu_critical:
            return AlertLevel.CRITICAL
        if temp >= t.cpu_warn:
            return AlertLevel.WARN
        if self._cpu_level != AlertLevel.OK and temp >= t.cpu_recover:
            return self._cpu_level
        return AlertLevel.OK

    def _gpu_threshold(self, temp: float, t: Thresholds) -> AlertLevel:
        """Map GPU temperature to an alert level using current thresholds.

        Args:
            temp: Current GPU temperature in degrees Celsius.
            t: Thresholds to use for comparison.

        Returns:
            The AlertLevel that applies at this temperature.
        """
        if temp >= t.gpu_critical:
            return AlertLevel.CRITICAL
        if temp >= t.gpu_warn:
            return AlertLevel.WARN
        return AlertLevel.OK

    def _make_alert(self, source: str, temp: float, level: AlertLevel) -> Alert:
        """Build an Alert object with a human-readable message.

        Args:
            source: Hardware source — "cpu" or "gpu".
            temp: Temperature that triggered the alert in degrees Celsius.
            level: The new AlertLevel being reported.

        Returns:
            Alert instance ready to be included in the broadcast snapshot.
        """
        messages = {
            ("cpu", AlertLevel.WARN): (f"CPU temperature warning: {temp:.1f}°C"),
            ("cpu", AlertLevel.CRITICAL): (
                f"CPU temperature critical: {temp:.1f}°C — fans set to MAX"
            ),
            ("cpu", AlertLevel.OK): (f"CPU temperature recovered: {temp:.1f}°C"),
            ("gpu", AlertLevel.WARN): (f"GPU temperature warning: {temp:.1f}°C"),
            ("gpu", AlertLevel.CRITICAL): (f"GPU temperature critical: {temp:.1f}°C"),
            ("gpu", AlertLevel.OK): (f"GPU temperature recovered: {temp:.1f}°C"),
        }
        msg = messages.get(
            (source, level),
            f"{source.upper()} {level.value}: {temp:.1f}°C",
        )
        return Alert(level=level, source=source, temp=temp, message=msg)
