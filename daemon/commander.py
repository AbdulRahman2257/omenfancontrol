"""
commander.py
------------
Fan and power profile control via Linux kernel interfaces.

Fan control:
    Writes directly to hp-wmi hwmon pwm1_enable.
        0 = force max speed
        2 = auto (BIOS control)

Power profile control:
    Uses powerprofilesctl to stay in sync with GNOME.
    Profiles: performance, balanced, power-saver
"""

import logging
import subprocess

from config import (
    FAN_PWM_PATH,
    VALID_FAN_MODES,
    VALID_PROFILES,
    COMMAND_TIMEOUT,
)

log = logging.getLogger(__name__)


class CommandResult:
    """Returned by every command function.

    Attributes:
        ok: True if the command succeeded.
        message: Human-readable result string.
    """

    def __init__(self, ok: bool, message: str = ""):
        self.ok = ok
        self.message = message.strip()

    def to_dict(self) -> dict:
        """Serialise to dict for IPC response.

        Returns:
            Dict with status and msg keys.
        """
        return {
            "status": "ok" if self.ok else "error",
            "msg": self.message,
        }

    def __repr__(self) -> str:
        return f"CommandResult(ok={self.ok}, message={self.message!r})"


def fan_max() -> CommandResult:
    """Force fans to maximum speed.

    Writes 0 to pwm1_enable — disables BIOS fan control.

    Returns:
        CommandResult indicating success or failure.
    """
    return _write_pwm("max")


def fan_auto() -> CommandResult:
    """Return fans to automatic BIOS control.

    Writes 2 to pwm1_enable — restores BIOS fan control.

    Returns:
        CommandResult indicating success or failure.
    """
    return _write_pwm("auto")


def fan_set(mode: str) -> CommandResult:
    """Set fan mode by name.

    Args:
        mode: Fan mode — "max" or "auto".

    Returns:
        CommandResult indicating success or failure.
    """
    if mode not in VALID_FAN_MODES:
        return CommandResult(
            ok=False,
            message=f"invalid fan mode '{mode}', use: {sorted(VALID_FAN_MODES)}",
        )
    return fan_max() if mode == "max" else fan_auto()


def fan_status() -> CommandResult:
    """Read current fan mode from pwm1_enable.

    Returns:
        CommandResult with current mode in message.
    """
    try:
        with open(FAN_PWM_PATH) as f:
            value = f.read().strip()
        mode = "max" if value == "0" else "auto"
        return CommandResult(ok=True, message=f"fan mode: {mode} (pwm={value})")
    except OSError as e:
        log.error("fan_status failed: %s", e)
        return CommandResult(ok=False, message=str(e))


def _write_pwm(mode: str) -> CommandResult:
    """Write pwm value to fan control file.

    Args:
        mode: Fan mode key from VALID_FAN_MODES.

    Returns:
        CommandResult indicating success or failure.
    """
    value = VALID_FAN_MODES[mode]
    log.info("setting fan: %s (pwm=%s)", mode, value)
    try:
        with open(FAN_PWM_PATH, "w") as f:
            f.write(value + "\n")
        return CommandResult(ok=True, message=f"fan set to {mode}")
    except PermissionError:
        return CommandResult(
            ok=False,
            message=(
                f"permission denied writing to {FAN_PWM_PATH} — "
                "daemon must run as root"
            ),
        )
    except OSError as e:
        log.error("fan write failed: %s", e)
        return CommandResult(ok=False, message=str(e))


def set_power_profile(profile: str) -> CommandResult:
    """Set power profile via powerprofilesctl.

    Keeps GNOME power settings UI in sync.

    Args:
        profile: Profile name — "performance", "balanced", or "power-saver".

    Returns:
        CommandResult indicating success or failure.
    """
    if profile not in VALID_PROFILES:
        return CommandResult(
            ok=False,
            message=(f"invalid profile '{profile}', " f"use: {sorted(VALID_PROFILES)}"),
        )
    log.info("setting power profile: %s", profile)
    try:
        result = subprocess.run(
            ["powerprofilesctl", "set", profile],
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
        if result.returncode == 0:
            return CommandResult(
                ok=True,
                message=f"power profile set to {profile}",
            )
        err = result.stderr or result.stdout or f"exit {result.returncode}"
        log.warning("powerprofilesctl failed: %s", err)
        return CommandResult(ok=False, message=err)

    except FileNotFoundError:
        return CommandResult(
            ok=False,
            message="powerprofilesctl not found — install power-profiles-daemon",
        )
    except subprocess.TimeoutExpired:
        return CommandResult(ok=False, message="powerprofilesctl timed out")
    except Exception as e:
        log.error("set_power_profile error: %s", e)
        return CommandResult(ok=False, message=str(e))


def check_system() -> CommandResult:
    """Verify fan and power profile interfaces are accessible.

    Called at daemon startup to fail fast if something is wrong.

    Returns:
        CommandResult — ok if both interfaces are accessible.
    """
    try:
        with open(FAN_PWM_PATH) as f:
            f.read()
    except PermissionError:
        return CommandResult(
            ok=False,
            message=(
                f"permission denied reading {FAN_PWM_PATH} — " "daemon must run as root"
            ),
        )
    except OSError as e:
        return CommandResult(
            ok=False,
            message=f"fan control unavailable: {e}",
        )

    try:
        result = subprocess.run(
            ["powerprofilesctl", "get"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return CommandResult(
                ok=False,
                message="powerprofilesctl not working",
            )
    except FileNotFoundError:
        return CommandResult(
            ok=False,
            message="powerprofilesctl not found",
        )

    return CommandResult(ok=True, message="system interfaces ready")
