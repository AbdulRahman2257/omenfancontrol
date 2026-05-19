"""
reader.py
---------
Reads hardware data directly from /sys, /proc, and nvidia-smi.

Data sources:
    /proc/cpuinfo          — CPU model name
    k10temp hwmon          — CPU tctl temperature
    /proc/stat             — per-core CPU usage %
    cpufreq/scaling_cur_freq — per-core CPU frequency
    hp-wmi hwmon           — fan 1 and fan 2 RPM
    /sys/firmware/acpi     — power profile
    nvidia-smi             — GPU name, temp, utilization, VRAM, power draw
    amdgpu hwmon           — iGPU temp and power (secondary)

Test:
    pytest daemon/test_reader.py
"""

import os
import glob
import subprocess
import logging

from config import (
    HWMON_CPU_DRIVER,
    HWMON_FAN_PLATFORM,
    ACPI_PROFILE_PATH,
    ACPI_PROFILE_CHOICES_PATH,
    PROC_STAT_PATH,
)

log = logging.getLogger(__name__)


def find_hwmon_path(driver_name: str) -> str | None:
    """
    Find the hwmon directory for a specific driver.

    Args:
        driver_name: Driver name string to match against hwmon name file.

    Returns:
        Path string like '/sys/class/hwmon/hwmon3', or None if not found.
    """
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        name_file = os.path.join(hwmon, "name")
        try:
            name = open(name_file).read().strip()
            if name == driver_name:
                return hwmon
        except OSError:
            continue
    return None


def find_hp_wmi_hwmon() -> str | None:
    """
    Find the HP WMI hwmon path where fan RPM files live.

    Returns:
        Path string like '/sys/devices/platform/hp-wmi/hwmon/hwmon5',
        or None if not found.
    """
    matches = glob.glob(f"{HWMON_FAN_PLATFORM}/hwmon*")
    return matches[0] if matches else None


# ###############-----CPU-------####################


def read_cpu_model() -> str | None:
    """
    Read CPU model name from /proc/cpuinfo.

    Returns:
        Model name string e.g. 'AMD Ryzen 7 4800H with Radeon Graphics',
        or None if unreadable.
    """
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":")[1].strip()
    except OSError:
        return None
    return None


def read_cpu_temp() -> float | None:
    """
    Read CPU temperature via k10temp driver (AMD Ryzen).

    Returns:
        Temperature in degrees Celsius, or None if unavailable.
    """
    hwmon = find_hwmon_path(HWMON_CPU_DRIVER)
    if not hwmon:
        return None
    try:
        raw = open(os.path.join(hwmon, "temp1_input")).read().strip()
        return round(int(raw) / 1000.0, 1)
    except (OSError, ValueError):
        return None


# ###############-----CPU USAGE AND FREQUENCY-------####################


_prev_total_stat: tuple | None = None
_prev_core_stats: list | None = None


def read_cpu_usage() -> float | None:
    """
    Read overall CPU usage percentage from /proc/stat.

    Stateful — returns None on first call, then usage since last call.

    Returns:
        Float 0.0–100.0, or None on first call or read error.
    """
    global _prev_total_stat

    try:
        with open(PROC_STAT_PATH) as f:
            line = f.readline()
        values = list(map(int, line.split()[1:]))
        idle = values[3] + values[4]
        total = sum(values)

        if _prev_total_stat is None:
            _prev_total_stat = (idle, total)
            return None

        prev_idle, prev_total = _prev_total_stat
        _prev_total_stat = (idle, total)

        d_total = total - prev_total
        d_idle = idle - prev_idle

        if d_total == 0:
            return 0.0

        return round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1)

    except (OSError, ValueError, IndexError):
        return None


def read_cpu_cores() -> list[dict]:
    """
    Read per-core CPU usage and frequency.

    Stateful — usage is calculated as delta since last call.
    On first call, usage values will be 0.0.

    Returns:
        List of dicts, one per core, each containing:
            core  (int):  core index
            usage (float): usage percentage 0.0–100.0
            freq  (int):   current frequency in MHz
        Empty list on read error.
    """
    global _prev_core_stats

    cores = []

    # read /proc/stat lines for all cores
    try:
        with open(PROC_STAT_PATH) as f:
            lines = f.readlines()
        core_lines = [
            line
            for line in lines
            if line.startswith("cpu") and len(line) > 4 and line[3] != " "
        ]
    except OSError:
        return []

    # parse current stats
    current_stats = []
    for line in core_lines:
        parts = line.split()
        values = list(map(int, parts[1:]))
        idle = values[3] + values[4]
        total = sum(values)
        current_stats.append((idle, total))

    # calculate usage deltas
    usages = []
    if _prev_core_stats and len(_prev_core_stats) == len(current_stats):
        for (prev_idle, prev_total), (curr_idle, curr_total) in zip(
            _prev_core_stats, current_stats
        ):
            d_total = curr_total - prev_total
            d_idle = curr_idle - prev_idle
            if d_total == 0:
                usages.append(0.0)
            else:
                usages.append(
                    round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1)
                )
    else:
        usages = [0.0] * len(current_stats)

    _prev_core_stats = current_stats

    # read per-core frequencies
    freq_paths = sorted(
        glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")
    )
    if not freq_paths:
        freq_paths = sorted(
            glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_cur_freq")
        )

    freqs = []
    for path in freq_paths:
        try:
            raw = open(path).read().strip()
            freqs.append(int(raw) // 1000)  # kHz → MHz
        except (OSError, ValueError):
            freqs.append(0)

    for i, usage in enumerate(usages):
        cores.append(
            {
                "core": i,
                "usage": usage,
                "freq": freqs[i] if i < len(freqs) else 0,
            }
        )

    return cores


def read_ram() -> dict:
    """Read RAM usage from /proc/meminfo.

    Returns:
        Dict with ram_used, ram_total (GB) and ram_percent (%).
    """
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            parts = line.split()
            mem[parts[0].rstrip(":")] = int(parts[1])  # kB
        total = mem["MemTotal"]
        available = mem["MemAvailable"]
        used = total - available

        return {
            "ram_used": round(used / (1024**2), 1),  # GB
            "ram_total": round(total / (1024**2), 1),  # GB
            "ram_percent": round(used / total * 100, 1),
        }
    except OSError:
        return {
            "ram_used": None,
            "ram_total": None,
            "ram_percent": None,
        }


def read_fan_rpms() -> dict:
    """
    Read fan RPM values from HP WMI hwmon.

    Returns:
        Dict with keys 'fan1' and 'fan2', each int or None.
    """
    result = {"fan1": None, "fan2": None}
    hwmon = find_hp_wmi_hwmon()
    if not hwmon:
        return result

    for i, key in enumerate(["fan1", "fan2"], start=1):
        try:
            raw = open(os.path.join(hwmon, f"fan{i}_input")).read().strip()
            result[key] = int(raw)
        except (OSError, ValueError):
            result[key] = None

    return result


def read_power_profile() -> str | None:
    """
    Read current ACPI power profile.

    Returns:
        Profile string e.g. 'balanced', or None if unreadable.
    """
    try:
        return open(ACPI_PROFILE_PATH).read().strip()
    except OSError:
        return None


def read_available_profiles() -> list[str]:
    """Read available ACPI power profiles.

    Returns:
        List of profile strings e.g. ['power saver', 'balanced', 'performance'].
    """
    try:
        return open(ACPI_PROFILE_CHOICES_PATH).read().strip().split()
    except OSError:
        return []


# gpu — nvidia-smi is the only way to get all metrics in one call, but we want to check
# availability once at startup and skip if not present to avoid subprocess
#  overhead every second

_nvidia_available: bool | None = None


def _check_nvidia() -> bool:
    """
    Check once whether nvidia-smi is available.

    Returns:
        True if nvidia-smi is installed and responds, False otherwise.
    """
    global _nvidia_available
    if _nvidia_available is not None:
        return _nvidia_available
    try:
        result = subprocess.run(
            ["nvidia-smi", "--version"],
            capture_output=True,
            timeout=2,
        )
        _nvidia_available = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _nvidia_available = False
    log.info("nvidia-smi available: %s", _nvidia_available)
    return _nvidia_available


def read_gpu_data() -> dict:
    """
    Read all NVIDIA GPU metrics in a single nvidia-smi call.

    Queries name, temperature, utilization, VRAM usage, VRAM total,
    and power draw in one subprocess call to minimise latency.

    Returns:
        Dict with keys:
            gpu_name       (str|None)
            gpu_temp       (float|None) — degrees Celsius
            gpu_util       (float|None) — utilization percent
            gpu_vram_used  (int|None)   — MiB
            gpu_vram_total (int|None)   — MiB
            gpu_power      (float|None) — Watts
        All values None if nvidia-smi is unavailable or call fails.
    """
    empty = {
        "gpu_name": None,
        "gpu_temp": None,
        "gpu_util": None,
        "gpu_vram_used": None,
        "gpu_vram_total": None,
        "gpu_power": None,
    }

    if not _check_nvidia():
        return empty

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,temperature.gpu,utilization.gpu,"
                "memory.used,memory.total,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )

        if result.returncode != 0:
            log.warning("nvidia-smi failed: %s", result.stderr.strip())
            return empty

        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 6:
            log.warning("nvidia-smi unexpected output: %s", result.stdout)
            return empty

        return {
            "gpu_name": parts[0],
            "gpu_temp": float(parts[1]),
            "gpu_util": float(parts[2]),
            "gpu_vram_used": int(parts[3]),
            "gpu_vram_total": int(parts[4]),
            "gpu_power": float(parts[5]),
        }

    except (subprocess.TimeoutExpired, ValueError, IndexError) as e:
        log.warning("gpu read error: %s", e)
        return empty


# combined snapshot

# read CPU model once at import — it never changes
_CPU_MODEL: str | None = read_cpu_model()


def read_all() -> dict:
    """
    Read all hardware values in one call.

    Returns a dict with all current readings. Called every second
    by the daemon main loop.

    Returns:
        Dict containing all hardware readings with keys:
            cpu_temp, cpu_usage, cpu_cores, cpu_model,
            fan1_rpm, fan2_rpm,
            power_profile, profiles_avail,
            gpu_name, gpu_temp, gpu_util,
            gpu_vram_used, gpu_vram_total, gpu_power,
            ram_used, ram_total, ram_percent.
    """
    fans = read_fan_rpms()
    gpu = read_gpu_data()
    cores = read_cpu_cores()
    ram = read_ram()

    return {
        # cpu
        "cpu_model": _CPU_MODEL,
        "cpu_temp": read_cpu_temp(),
        "cpu_usage": read_cpu_usage(),
        "cpu_cores": cores,
        "ram_used": ram["ram_used"],
        "ram_total": ram["ram_total"],
        "ram_percent": ram["ram_percent"],
        # fans
        "fan1_rpm": fans["fan1"],
        "fan2_rpm": fans["fan2"],
        # power
        "power_profile": read_power_profile(),
        "profiles_avail": read_available_profiles(),
        # gpu — all from one nvidia-smi call
        "gpu_name": gpu["gpu_name"],
        "gpu_temp": gpu["gpu_temp"],
        "gpu_util": gpu["gpu_util"],
        "gpu_vram_used": gpu["gpu_vram_used"],
        "gpu_vram_total": gpu["gpu_vram_total"],
        "gpu_power": gpu["gpu_power"],
    }
