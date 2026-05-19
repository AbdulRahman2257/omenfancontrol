"""
test_commander.py
-----------------
Tests for commander — fan control and power profile management
via Linux kernel interfaces.

Unit tests (no root needed):
    - CommandResult behaviour
    - Input validation for fan modes and profiles

Integration tests (root + real hardware):
    - fan read/write via hwmon pwm
    - power profile via powerprofilesctl

Run:
    python -m pytest tests/test_commander.py -v
    python -m pytest tests/test_commander.py -v -k "not integration"
    sudo python -m pytest tests/test_commander.py -v -m "integration"
"""

import logging
import os
import sys
import time
from unittest.mock import MagicMock, mock_open, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon.commander import (  # noqa: E402
    CommandResult,
    check_system,
    fan_auto,
    fan_max,
    fan_set,
    fan_status,
    set_power_profile,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")


def _system_available() -> bool:
    """Check whether system interfaces are accessible.

    Returns:
        True if fan pwm and powerprofilesctl are available.
    """
    return check_system().ok


def test_command_result_ok() -> None:
    """CommandResult ok=True stores message correctly."""
    r = CommandResult(ok=True, message="system interfaces ready")
    assert r.ok is True
    assert r.message == "system interfaces ready"
    assert r.to_dict()["status"] == "ok"
    assert r.to_dict()["msg"] == "system interfaces ready"


def test_command_result_fail() -> None:
    """CommandResult ok=False stores message correctly."""
    r = CommandResult(ok=False, message="permission denied")
    assert r.ok is False
    assert r.message == "permission denied"
    assert r.to_dict()["status"] == "error"
    assert r.to_dict()["msg"] == "permission denied"


def test_command_result_strips_whitespace() -> None:
    """CommandResult strips leading and trailing whitespace."""
    r = CommandResult(ok=True, message="  fan set  \n")
    assert r.message == "fan set"


def test_command_result_empty_message() -> None:
    """CommandResult handles empty message."""
    r = CommandResult(ok=True)
    assert r.message == ""
    assert r.to_dict()["status"] == "ok"


def test_fan_set_invalid_mode() -> None:
    """fan_set rejects invalid modes without touching hardware."""
    for mode in ("turbo", "", "MAX", "0", "auto ", " max"):
        r = fan_set(mode)
        assert r.ok is False
        assert "invalid" in r.message.lower()


def test_fan_set_valid_modes_pass_validation() -> None:
    """fan_set accepts 'max' and 'auto' — validation passes."""
    for mode in ("max", "auto"):
        with patch("builtins.open", mock_open()):
            r = fan_set(mode)
            assert "invalid" not in r.message.lower()


def test_set_power_profile_invalid() -> None:
    """set_power_profile rejects invalid profiles."""
    for profile in ("ultra", "", "BALANCED", "cool", "power_saver"):
        r = set_power_profile(profile)
        assert r.ok is False
        assert "invalid" in r.message.lower()


def test_set_power_profile_valid_pass_validation() -> None:
    """set_power_profile accepts valid profiles and calls powerprofilesctl."""
    for profile in ("performance", "balanced", "power-saver"):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            r = set_power_profile(profile)
            assert r.ok is True
            assert mock_run.called
            assert mock_run.call_args[0][0] == ["powerprofilesctl", "set", profile]


def test_fan_status_reads_auto() -> None:
    """fan_status returns auto when pwm1_enable reads 2."""
    with patch("builtins.open", mock_open(read_data="2\n")):
        r = fan_status()
        assert r.ok is True
        assert "auto" in r.message


def test_fan_status_reads_max() -> None:
    """fan_status returns max when pwm1_enable reads 0."""
    with patch("builtins.open", mock_open(read_data="0\n")):
        r = fan_status()
        assert r.ok is True
        assert "max" in r.message


def test_fan_status_handles_oserror() -> None:
    """fan_status returns ok=False when /sys path is unreadable."""
    with patch("builtins.open", side_effect=OSError("no such file")):
        r = fan_status()
        assert r.ok is False
        assert r.message != ""


def test_fan_max_writes_zero() -> None:
    """fan_max writes '0' to pwm1_enable."""
    m = mock_open()
    with patch("builtins.open", m):
        r = fan_max()
        assert r.ok is True
        assert "0" in m().write.call_args[0][0]


def test_fan_auto_writes_two() -> None:
    """fan_auto writes '2' to pwm1_enable."""
    m = mock_open()
    with patch("builtins.open", m):
        r = fan_auto()
        assert r.ok is True
        assert "2" in m().write.call_args[0][0]


def test_fan_write_permission_error() -> None:
    """fan_max returns ok=False with clear message on PermissionError."""
    with patch("builtins.open", side_effect=PermissionError("denied")):
        r = fan_max()
        assert r.ok is False
        assert "root" in r.message.lower()


def test_set_power_profile_not_found() -> None:
    """set_power_profile returns ok=False when powerprofilesctl is missing."""
    with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
        r = set_power_profile("balanced")
        assert r.ok is False
        assert "powerprofilesctl" in r.message.lower()


def test_set_power_profile_subprocess_fails() -> None:
    """set_power_profile returns ok=False when subprocess exits non-zero."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error applying profile",
        )
        r = set_power_profile("performance")
        assert r.ok is False
        assert r.message != ""


def test_check_system_ok() -> None:
    """check_system returns ok when both interfaces are accessible."""
    with patch("builtins.open", mock_open(read_data="2\n")):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="balanced\n", stderr=""
            )
            r = check_system()
            assert r.ok is True
            assert r.message != ""


def test_check_system_fan_path_missing() -> None:
    """check_system returns ok=False when fan pwm path is missing."""
    with patch("builtins.open", side_effect=OSError("no such file")):
        r = check_system()
        assert r.ok is False
        assert "fan" in r.message.lower()


def test_check_system_powerprofilesctl_missing() -> None:
    """check_system returns ok=False when powerprofilesctl is missing."""
    with patch("builtins.open", mock_open(read_data="2\n")):
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("not found"),
        ):
            r = check_system()
            assert r.ok is False
            assert "powerprofilesctl" in r.message.lower()


@pytest.mark.integration
def test_integration_check_system() -> None:
    """check_system passes on real hardware."""
    r = check_system()
    assert r.ok, r.message


@pytest.mark.integration
def test_integration_fan_status() -> None:
    """fan_status reads real fan mode."""
    r = fan_status()
    assert r.ok, r.message
    assert "auto" in r.message or "max" in r.message


@pytest.mark.integration
def test_integration_fan_max_then_auto() -> None:
    """Fan can be set to max then restored to auto."""
    r_max = fan_max()
    assert r_max.ok, r_max.message
    time.sleep(2)

    r_auto = fan_auto()
    assert r_auto.ok, r_auto.message


@pytest.mark.integration
def test_integration_power_profiles() -> None:
    """All three power profiles can be set."""
    for profile in ("performance", "balanced", "power-saver"):
        r = set_power_profile(profile)
        assert r.ok, r.message
        time.sleep(0.5)

    set_power_profile("balanced")
