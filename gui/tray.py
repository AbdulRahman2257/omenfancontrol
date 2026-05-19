"""
gui/tray.py
-----------
System tray icon with live CPU temp display and quick controls.

Icon:
    Dynamic — shows current CPU temperature as text.
    Border colour changes with alert level:
        normal   → orange (#f97316)
        warn     → orange (#f97316)
        critical → red    (#ef4444)

Left click:  toggle main window visibility
Right click: context menu with live readings and quick controls
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

log = logging.getLogger(__name__)

_COLOR_NORMAL = "#f97316"
_COLOR_WARN = "#f97316"
_COLOR_CRITICAL = "#ef4444"
_COLOR_BG = "#1e1810"
_ICON_SIZE = 256


def _make_icon(temp: float | None, alert_level: str = "normal") -> QIcon:
    """Render a dynamic tray icon showing the current CPU temperature.

    Args:
        temp: CPU temperature in degrees Celsius, or None.
        alert_level: One of "normal", "warn", or "critical".

    Returns:
        QIcon with the rendered temperature display.
    """
    pixmap = QPixmap(_ICON_SIZE, _ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if alert_level == "critical":
        border_color = QColor(_COLOR_CRITICAL)
        bg_color = QColor("#2a0808")
    else:
        border_color = QColor(_COLOR_NORMAL)
        bg_color = QColor(_COLOR_BG)

    painter.setBrush(bg_color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(8, 8, _ICON_SIZE - 16, _ICON_SIZE - 16, 20, 20)

    pen = QPen(border_color)
    pen.setWidth(10)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(8, 8, _ICON_SIZE - 16, _ICON_SIZE - 16, 20, 20)

    painter.setPen(QColor(border_color))

    if temp is not None:
        painter.setFont(QFont("Courier New", 110, QFont.Weight.Bold))
        painter.drawText(
            0,
            0,
            _ICON_SIZE,
            180,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{temp:.0f}",
        )
        painter.setFont(QFont("Courier New", 52, QFont.Weight.Bold))
        painter.drawText(
            0,
            168,
            _ICON_SIZE,
            80,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "°C",
        )
    else:
        painter.setFont(QFont("Courier New", 90, QFont.Weight.Bold))
        painter.drawText(
            0,
            0,
            _ICON_SIZE,
            _ICON_SIZE,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "--",
        )

    painter.end()
    return QIcon(pixmap)


class SystemTray(QSystemTrayIcon):
    """System tray icon for the OMEN dashboard.

    Displays live CPU temperature and provides a quick-access menu
    for fan mode and power profile control.

    Signals:
        fan_changed: Emitted when user selects a fan mode from tray menu.
        power_changed: Emitted when user selects a power profile from menu.
        show_window_requested: Emitted when user clicks show window.
        quit_requested: Emitted when user clicks quit.

    Attributes:
        _cpu_temp: Last known CPU temperature.
        _gpu_temp: Last known GPU temperature.
        _fan_mode: Last known fan mode.
        _profile: Last known power profile.
        _fan1_rpm: Last known fan 1 RPM.
        _alert_level: Current alert level string.

    Example:
        tray = SystemTray(parent=window)
        tray.fan_changed.connect(client.send_fan)
        tray.power_changed.connect(client.send_power)
        tray.show_window_requested.connect(window.show)
        tray.quit_requested.connect(app.quit)
        tray.show()
    """

    fan_changed = pyqtSignal(str)
    power_changed = pyqtSignal(str)
    show_window_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        """Initialise the system tray icon.

        Args:
            parent: Optional Qt parent widget — usually the main window.
        """
        super().__init__(parent)

        self._cpu_temp: float | None = None
        self._gpu_temp: float | None = None
        self._fan_mode: str = "auto"
        self._profile: str = "--"
        self._fan1_rpm: int | None = None
        self._alert_level: str = "normal"

        self.setIcon(_make_icon(None, "normal"))
        self.setToolTip("OMEN Dashboard")
        self._build_menu()
        self.activated.connect(self._on_activated)

    def update(self, snapshot: dict) -> None:
        """Update tray icon and menu from a snapshot dict.

        Args:
            snapshot: Decoded snapshot dict from the daemon.
        """
        self._cpu_temp = snapshot.get("cpu_temp")
        self._gpu_temp = snapshot.get("gpu_temp")
        self._fan_mode = snapshot.get("fan_mode", "auto")
        self._profile = snapshot.get("power_profile") or "--"
        self._fan1_rpm = snapshot.get("fan1_rpm")

        alerts = snapshot.get("alerts", [])
        if any(a.get("level") == "critical" for a in alerts):
            self._alert_level = "critical"
        elif any(a.get("level") == "warn" for a in alerts):
            self._alert_level = "warn"
        else:
            self._alert_level = "normal"

        self.setIcon(_make_icon(self._cpu_temp, self._alert_level))

        cpu_str = f"{self._cpu_temp:.0f}°C" if self._cpu_temp else "--"
        gpu_str = f"{self._gpu_temp:.0f}°C" if self._gpu_temp else "--"
        self.setToolTip(
            f"OMEN Dashboard\n"
            f"CPU: {cpu_str}  GPU: {gpu_str}\n"
            f"Fan: {self._fan_mode.upper()}  Profile: {self._profile.upper()}"
        )
        self._refresh_menu_readings()

    def set_connected(self, connected: bool) -> None:
        """Update the tray icon for connection state.

        Args:
            connected: True if connected to daemon, False otherwise.
        """
        if not connected:
            self.setIcon(_make_icon(None, "normal"))
            self.setToolTip("OMEN Dashboard — disconnected")

    def _build_menu(self) -> None:
        """Build the right-click context menu."""
        self._menu = QMenu()
        self._menu.setObjectName("TrayMenu")

        header = self._menu.addAction("▶ OMEN DASHBOARD")
        header.setEnabled(False)
        self._menu.addSeparator()

        self._act_cpu = self._menu.addAction("cpu temp   --")
        self._act_gpu = self._menu.addAction("gpu temp   --")
        self._act_fan = self._menu.addAction("fan        --")
        self._act_profile = self._menu.addAction("profile    --")

        for act in (
            self._act_cpu,
            self._act_gpu,
            self._act_fan,
            self._act_profile,
        ):
            act.setEnabled(False)

        self._menu.addSeparator()

        self._act_show = self._menu.addAction("show window")
        self._act_show.triggered.connect(self.show_window_requested)

        self._menu.addSeparator()

        fan_label = self._menu.addAction("fan mode")
        fan_label.setEnabled(False)

        self._act_fan_auto = self._menu.addAction("  auto")
        self._act_fan_max = self._menu.addAction("  max")
        self._act_fan_auto.triggered.connect(lambda: self._on_fan("auto"))
        self._act_fan_max.triggered.connect(lambda: self._on_fan("max"))

        self._menu.addSeparator()

        prof_label = self._menu.addAction("power profile")
        prof_label.setEnabled(False)

        self._act_performance = self._menu.addAction("  performance")
        self._act_balanced = self._menu.addAction("  balanced")
        self._act_power_saver = self._menu.addAction("  power-saver")
        self._act_performance.triggered.connect(lambda: self._on_power("performance"))
        self._act_balanced.triggered.connect(lambda: self._on_power("balanced"))
        self._act_power_saver.triggered.connect(lambda: self._on_power("power-saver"))

        self._menu.addSeparator()

        act_quit = self._menu.addAction("quit")
        act_quit.triggered.connect(self.quit_requested)

        self.setContextMenu(self._menu)

    def _refresh_menu_readings(self) -> None:
        """Update live reading labels in the menu."""
        cpu_str = f"{self._cpu_temp:.0f}°C" if self._cpu_temp else "--"
        gpu_str = f"{self._gpu_temp:.0f}°C" if self._gpu_temp else "--"
        rpm_str = f"{self._fan1_rpm} RPM" if self._fan1_rpm else "--"

        self._act_cpu.setText(f"cpu temp   {cpu_str}")
        self._act_gpu.setText(f"gpu temp   {gpu_str}")
        self._act_fan.setText(f"fan        {self._fan_mode.upper()} · {rpm_str}")
        self._act_profile.setText(f"profile    {self._profile.upper()}")

        self._act_fan_auto.setText(
            "  auto  ✓" if self._fan_mode == "auto" else "  auto"
        )
        self._act_fan_max.setText("  max   ✓" if self._fan_mode == "max" else "  max")
        self._act_performance.setText(
            "  performance  ✓" if self._profile == "performance" else "  performance"
        )
        self._act_balanced.setText(
            "  balanced     ✓" if self._profile == "balanced" else "  balanced"
        )
        self._act_power_saver.setText(
            "  power-saver  ✓" if self._profile == "power-saver" else "  power-saver"
        )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle tray icon click — toggle main window visibility.

        Args:
            reason: Qt activation reason enum value.
        """
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window_requested.emit()

    def _on_fan(self, mode: str) -> None:
        """Emit fan_changed signal and update menu immediately.

        Args:
            mode: Fan mode — "auto" or "max".
        """
        self._fan_mode = mode
        self._refresh_menu_readings()
        self.fan_changed.emit(mode)
        log.info("tray: fan: %s", mode)

    def _on_power(self, profile: str) -> None:
        """Emit power_changed signal and update menu immediately.

        Args:
            profile: Power profile — "performance", "balanced",
                or "power-saver".
        """
        self._profile = profile
        self._refresh_menu_readings()
        self.power_changed.emit(profile)
        log.info("tray: power: %s", profile)
