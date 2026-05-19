"""
config.py
---------
Central configuration for the OMEN dashboard.
All constants, paths, thresholds, and settings live here.
Every other module imports from this file — nothing is hardcoded elsewhere.

Edit this file to change behaviour across the entire application.
"""

import logging
from pathlib import Path

FAN_PWM_PATH = "/sys/devices/platform/hp-wmi/hwmon/hwmon5/pwm1_enable"
PLATFORM_PROFILE_PATH = "/sys/firmware/acpi/platform_profile"
VALID_FAN_MODES = {"max": "0", "auto": "2"}
VALID_PROFILES = {"performance", "balanced", "power-saver"}
COMMAND_TIMEOUT = 5


#  fan control


# Default fan mode on daemon startup
DEFAULT_FAN_MODE: str = "auto"


#  power profiles


# Default profile on daemon startup
DEFAULT_PROFILE: str = "balanced"

#  thresholds

# Where the daemon persists user-configured thresholds.
# Written by daemon (root), read by daemon on startup.
THRESHOLDS_PATH: str = "/var/lib/omen-dashboard/thresholds.json"


#  alert thresholds

# CPU temperature thresholds (degrees Celsius)
ALERT_CPU_WARN: float = 85.0  # yellow warning notification
ALERT_CPU_CRITICAL: float = 90.0  # red critical notification + auto fan max

# GPU temperature thresholds (degrees Celsius)
ALERT_GPU_WARN: float = 80.0  # yellow warning notification
ALERT_GPU_CRITICAL: float = 90.0  # red critical notification

# When CPU drops back below this, auto-restore fan to auto (if daemon maxed it)
ALERT_CPU_RECOVER: float = 75.0


#  daemon settings

# How often to read /sys hardware files (seconds)
# 1.0 = every second, smooth graphs
# 2.0 = every 2 seconds, lighter on resources
DAEMON_READ_INTERVAL: float = 1.0

# Unix socket path — GUI connects here to receive data
# /run is the standard location for runtime sockets on Linux
DAEMON_SOCKET_PATH: str = "/run/omen-daemon.sock"

# How many data points to keep in history buffer
# At 1s interval: 60 = 1 minute of history
HISTORY_LENGTH: int = 60


# Max clients that can connect to the daemon socket simultaneously
SOCKET_MAX_CLIENTS: int = 5


#  logging

# Log level: logging.DEBUG, logging.INFO, logging.WARNING
LOG_LEVEL: int = logging.INFO

# Log file location — None means log to stdout only
# Example: Path("/var/log/omen-daemon.log")
LOG_FILE: Path | None = Path("/var/log/omen-daemon.log")

# Log format
LOG_FORMAT: str = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


#  hardware /sys paths
# These are auto-discovered at runtime by reader.py using glob.
# Listed here for documentation purposes only — do not hardcode these
# as hwmon numbers can change between reboots.

# CPU temp driver name (AMD Ryzen)
HWMON_CPU_DRIVER: str = "k10temp"

# GPU temp driver name (AMD GPU)
HWMON_GPU_DRIVER: str = "amdgpu"

# Fan RPM platform path prefix
HWMON_FAN_PLATFORM: str = "/sys/devices/platform/hp-wmi/hwmon"

# Power profile path
ACPI_PROFILE_PATH: str = "/sys/firmware/acpi/platform_profile"
ACPI_PROFILE_CHOICES_PATH: str = "/sys/firmware/acpi/platform_profile_choices"

# CPU usage path
PROC_STAT_PATH: str = "/proc/stat"


#  GUI settings

# Window title
APP_NAME: str = "OMEN Dashboard"
APP_VERSION: str = "0.1.0"

# How often the GUI polls the daemon for new data (milliseconds)
# Should match DAEMON_READ_INTERVAL * 1000
GUI_POLL_INTERVAL_MS: int = 1000

# Graph history display length (should match HISTORY_LENGTH)
GUI_GRAPH_HISTORY: int = HISTORY_LENGTH

# Tray icon tooltip
TRAY_TOOLTIP: str = "OMEN Dashboard"
