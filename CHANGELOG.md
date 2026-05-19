# Changelog

All notable changes to this project will be documented here.

## [0.1.0] — 2026-05-19

### Added
- Live CPU/GPU temperature monitoring with 60-second history graphs
- Per-core CPU usage and frequency bars (16 cores)
- Fan mode control (AUTO/MAX) via hp-wmi kernel interface
- Dual fan graph — fan 1 and fan 2 on the same chart
- RAM usage card showing used/total GB and percentage
- Power profile control (Performance/Balanced/Power Saver) via powerprofilesctl
- Configurable alert thresholds with hysteresis
- Auto fan action — daemon sets fan to MAX on critical CPU temp, restores on recovery
- System tray icon with live CPU temperature display
- Desktop notifications on alert level transitions
- PyQt6 dark theme dashboard
- Daemon architecture — root systemd service, GUI runs as user
- Unix domain socket IPC between daemon and GUI
- nvidia-smi GPU metrics (name, temp, utilization, VRAM, power draw)
- RAM usage from /proc/meminfo — no external dependencies
- GNOME power settings stay in sync via powerprofilesctl

### No third-party dependencies
- Fan control writes directly to /sys/devices/platform/hp-wmi/hwmon
- Power profiles via powerprofilesctl (pre-installed on Ubuntu 22.04+)
- No openomen required

### Installation
- Source install via install/install.sh
- .deb package via build_deb.sh
- PyInstaller self-contained binary via build_pyinstaller.sh

### Tested on
- HP OMEN 15 en0xxx — AMD Ryzen 7 4800H + NVIDIA RTX 2060
- Ubuntu with kernel 7.0.0