"""
test_alerter.py
---------------
Tests alerter threshold logic in isolation — no hardware needed.
Simulates temp readings crossing warn/critical/recover thresholds.

Run:
    python -m pytest tests/test_alerter.py -v
"""

import logging
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon.alerter import Alerter  # noqa: E402
from models import AlertLevel  # noqa: E402
from thresholds import Thresholds  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")


def make_alerter(
    thresholds: Thresholds | None = None,
) -> tuple[Alerter, list, list]:
    """Create a fresh Alerter with signal collectors.

    Args:
        thresholds: Optional Thresholds instance. Defaults to
            standard thresholds if not provided.

    Returns:
        Tuple of (alerter, fired_alerts list, fan_actions list).
    """
    fired_alerts: list = []
    fan_actions: list = []
    alerter = Alerter(
        thresholds=thresholds or Thresholds(),
        on_alert=lambda alert: fired_alerts.append(alert),
        on_fan_action=lambda action: fan_actions.append(action),
    )
    return alerter, fired_alerts, fan_actions


def tick(alerter: Alerter, cpu: float, gpu: float) -> list[dict]:
    """Run one alerter check with given temperatures.

    Args:
        alerter: The Alerter instance to check.
        cpu: CPU temperature in degrees Celsius.
        gpu: GPU temperature in degrees Celsius.

    Returns:
        List of alert dicts returned by alerter.check().
    """
    return alerter.check({"cpu_temp": cpu, "gpu_temp": gpu})


def test_no_alerts_at_normal_temps() -> None:
    """No alerts fire when temps are well below thresholds."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 65.0, 45.0)
    tick(alerter, 70.0, 50.0)
    tick(alerter, 72.0, 55.0)
    assert len(fired) == 0
    assert len(fans) == 0


def test_cpu_warn_fires_once() -> None:
    """CPU warn alert fires exactly once on threshold crossing."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 84.0, 50.0)
    tick(alerter, 86.0, 50.0)
    tick(alerter, 87.0, 50.0)
    tick(alerter, 88.0, 50.0)

    cpu_warns = [a for a in fired if a.level == AlertLevel.WARN and a.source == "cpu"]
    assert len(cpu_warns) == 1
    assert len(fans) == 0


def test_cpu_critical_fires_and_sets_fan_max() -> None:
    """CPU critical fires and triggers fan to max."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 86.0, 50.0)
    tick(alerter, 91.0, 50.0)
    tick(alerter, 92.0, 50.0)

    cpu_crits = [
        a for a in fired if a.level == AlertLevel.CRITICAL and a.source == "cpu"
    ]
    assert len(cpu_crits) == 1
    assert len(fans) == 1
    assert fans[0] == "max"


def test_cpu_recovery_restores_fan() -> None:
    """CPU recovery fires and restores fan to auto."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 91.0, 50.0)
    tick(alerter, 80.0, 50.0)
    tick(alerter, 72.0, 50.0)

    cpu_recoveries = [
        a for a in fired if a.level == AlertLevel.OK and a.source == "cpu"
    ]
    assert len(cpu_recoveries) >= 1
    assert "auto" in fans
    assert fans == ["max", "auto"]


def test_cpu_hysteresis_no_flapping() -> None:
    """CPU stays in warn state until temp drops below recover threshold."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 86.0, 50.0)
    tick(alerter, 84.0, 50.0)
    tick(alerter, 80.0, 50.0)
    tick(alerter, 76.0, 50.0)
    tick(alerter, 72.0, 50.0)

    warn_count = sum(
        1 for a in fired if a.level == AlertLevel.WARN and a.source == "cpu"
    )
    ok_count = sum(1 for a in fired if a.level == AlertLevel.OK and a.source == "cpu")
    assert warn_count == 1
    assert ok_count == 1


def test_gpu_warn_and_critical() -> None:
    """GPU warn and critical fire correctly."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 50.0, 81.0)
    tick(alerter, 50.0, 85.0)
    tick(alerter, 50.0, 91.0)

    gpu_warns = [a for a in fired if a.level == AlertLevel.WARN and a.source == "gpu"]
    gpu_crits = [
        a for a in fired if a.level == AlertLevel.CRITICAL and a.source == "gpu"
    ]
    assert len(gpu_warns) == 1
    assert len(gpu_crits) == 1
    assert len(fans) == 0


def test_gpu_recovery() -> None:
    """GPU recovery fires ok alert."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 50.0, 91.0)
    tick(alerter, 50.0, 60.0)

    gpu_recoveries = [
        a for a in fired if a.level == AlertLevel.OK and a.source == "gpu"
    ]
    assert len(gpu_recoveries) == 1


def test_simultaneous_cpu_and_gpu_alerts() -> None:
    """CPU and GPU can alert independently at the same time."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 91.0, 91.0)

    cpu_crits = [
        a for a in fired if a.level == AlertLevel.CRITICAL and a.source == "cpu"
    ]
    gpu_crits = [
        a for a in fired if a.level == AlertLevel.CRITICAL and a.source == "gpu"
    ]
    assert len(cpu_crits) == 1
    assert len(gpu_crits) == 1
    assert fans == ["max"]


def test_update_thresholds_takes_effect() -> None:
    """update_thresholds() changes active thresholds immediately."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 80.0, 50.0)
    assert len(fired) == 0

    alerter.update_thresholds(
        Thresholds(
            cpu_warn=75.0,
            cpu_critical=90.0,
            cpu_recover=65.0,
            gpu_warn=80.0,
            gpu_critical=90.0,
        )
    )
    tick(alerter, 80.0, 50.0)

    cpu_warns = [a for a in fired if a.level == AlertLevel.WARN and a.source == "cpu"]
    assert len(cpu_warns) == 1


def test_get_thresholds_returns_current() -> None:
    """get_thresholds() returns the currently active thresholds."""
    custom = Thresholds(
        cpu_warn=80.0,
        cpu_critical=88.0,
        cpu_recover=70.0,
        gpu_warn=75.0,
        gpu_critical=85.0,
    )
    alerter, _, _ = make_alerter(thresholds=custom)
    t = alerter.get_thresholds()

    assert t.cpu_warn == 80.0
    assert t.cpu_critical == 88.0
    assert t.cpu_recover == 70.0
    assert t.gpu_warn == 75.0
    assert t.gpu_critical == 85.0


def test_reset_clears_state() -> None:
    """reset() clears alert levels so they fire again on next check."""
    alerter, fired, fans = make_alerter()
    tick(alerter, 91.0, 50.0)
    initial_count = len(fired)

    alerter.reset()
    tick(alerter, 91.0, 50.0)
    assert len(fired) > initial_count


def test_full_sequence() -> None:
    """Full ok, warn, critical, recover sequence fires correct alerts."""
    alerter, fired, fans = make_alerter()

    tick(alerter, 65.0, 45.0)
    tick(alerter, 86.0, 50.0)
    tick(alerter, 91.0, 50.0)
    tick(alerter, 91.0, 81.0)
    tick(alerter, 91.0, 91.0)
    tick(alerter, 80.0, 70.0)
    tick(alerter, 72.0, 60.0)
    tick(alerter, 70.0, 70.0)
    tick(alerter, 65.0, 45.0)

    assert any(a.level == AlertLevel.WARN and a.source == "cpu" for a in fired)
    assert any(a.level == AlertLevel.CRITICAL and a.source == "cpu" for a in fired)
    assert any(a.level == AlertLevel.WARN and a.source == "gpu" for a in fired)
    assert any(a.level == AlertLevel.CRITICAL and a.source == "gpu" for a in fired)
    assert any(a.level == AlertLevel.OK and a.source == "cpu" for a in fired)
    assert any(a.level == AlertLevel.OK and a.source == "gpu" for a in fired)
    assert fans == ["max", "auto"]
