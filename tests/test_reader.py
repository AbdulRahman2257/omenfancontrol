"""
test_reader.py
--------------
Hardware reader tests — verifies all /sys paths and live readings.
Requires real hardware — all tests marked as integration.

Run:
    python -m pytest tests/test_reader.py -v -m "integration"
"""

import os
import sys
import time

import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemon.reader import (  # noqa: E402
    find_hp_wmi_hwmon,
    find_hwmon_path,
    read_all,
    read_cpu_cores,
    read_cpu_model,
    read_gpu_data,
)


@pytest.mark.integration
def test_hwmon_paths() -> None:
    """k10temp and hp-wmi hwmon paths are discoverable."""
    cpu_hwmon = find_hwmon_path("k10temp")
    assert cpu_hwmon is not None, "k10temp hwmon not found"

    fan_hwmon = find_hp_wmi_hwmon()
    assert fan_hwmon is not None, "hp-wmi hwmon not found"


@pytest.mark.integration
def test_cpu_model() -> None:
    """CPU model name is readable and non-empty."""
    model = read_cpu_model()
    assert model is not None, "cpu model is None"
    assert len(model) > 0, "cpu model is empty"


@pytest.mark.integration
def test_gpu_data() -> None:
    """nvidia-smi returns all expected GPU fields with sane values."""
    gpu = read_gpu_data()

    assert gpu.get("gpu_name") is not None, "gpu_name missing"
    assert gpu.get("gpu_temp") is not None, "gpu_temp missing"
    assert gpu.get("gpu_util") is not None, "gpu_util missing"
    assert gpu.get("gpu_vram_used") is not None, "gpu_vram_used missing"
    assert gpu.get("gpu_vram_total") is not None, "gpu_vram_total missing"
    assert gpu.get("gpu_power") is not None, "gpu_power missing"

    assert isinstance(gpu["gpu_temp"], float), "gpu_temp is not float"
    assert 0 < gpu["gpu_temp"] < 120, f"gpu_temp out of range: {gpu['gpu_temp']}"
    assert gpu["gpu_vram_total"] > 0, "gpu_vram_total is 0"


@pytest.mark.integration
def test_cpu_cores() -> None:
    """Per-core CPU stats are readable with correct structure."""
    cores = read_cpu_cores()

    assert len(cores) > 0, "cores list is empty"
    assert len(cores) == 16, f"expected 16 cores, got {len(cores)}"

    core0 = cores[0]
    assert "core" in core0, "core key missing"
    assert "usage" in core0, "usage key missing"
    assert "freq" in core0, "freq key missing"
    assert core0.get("freq", 0) > 0, f"freq is 0: {core0.get('freq')}"


@pytest.mark.integration
def test_read_all_fields() -> None:
    """read_all() returns all expected keys with correct types."""
    read_all()
    time.sleep(1)
    data = read_all()

    expected_keys = [
        "cpu_model",
        "cpu_temp",
        "cpu_usage",
        "cpu_cores",
        "fan1_rpm",
        "fan2_rpm",
        "power_profile",
        "profiles_avail",
        "gpu_name",
        "gpu_temp",
        "gpu_util",
        "gpu_vram_used",
        "gpu_vram_total",
        "gpu_power",
        "ram_used",
        "ram_total",
        "ram_percent",
    ]

    for key in expected_keys:
        assert key in data, f"key '{key}' missing from read_all()"

    assert isinstance(data["cpu_temp"], float), "cpu_temp is not float"
    assert 0 < data["cpu_temp"] < 120, f"cpu_temp out of range: {data['cpu_temp']}"

    assert isinstance(data["cpu_usage"], float), "cpu_usage is not float"
    assert (
        0.0 <= data["cpu_usage"] <= 100.0
    ), f"cpu_usage out of range: {data['cpu_usage']}"

    assert isinstance(data["fan1_rpm"], int), "fan1_rpm is not int"
    assert isinstance(data["cpu_cores"], list), "cpu_cores is not list"
    assert isinstance(data["profiles_avail"], list), "profiles_avail is not list"

    assert isinstance(data["ram_used"], float), "ram_used is not float"
    assert isinstance(data["ram_total"], float), "ram_total is not float"
    assert isinstance(data["ram_percent"], float), "ram_percent is not float"
    assert (
        0.0 <= data["ram_percent"] <= 100.0
    ), f"ram_percent out of range: {data['ram_percent']}"


@pytest.mark.integration
def test_live_readings_update() -> None:
    """Three consecutive read_all() calls return consistent data."""
    for _ in range(3):
        data = read_all()
        assert data.get("cpu_temp") is not None, "cpu_temp missing in live reading"
        assert data.get("fan1_rpm") is not None, "fan1_rpm missing in live reading"
        time.sleep(1)
