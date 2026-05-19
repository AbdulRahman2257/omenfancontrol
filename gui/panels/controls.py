"""
gui/panels/controls.py
----------------------
Controls panel — fan mode, power profile, and threshold editor.

Three cards side by side:
    1. POWER PROFILE  — performance / balanced / power-saver buttons
    2. FAN CONTROL    — auto / max toggle + threshold spinboxes
    3. SYSTEM INFO    — profile, uptime, kernel, socket status

Signals:
    fan_changed(str)         — "auto" or "max"
    power_changed(str)       — "performance", "balanced", or "power-saver"
    thresholds_changed(dict) — threshold dict ready to send to daemon
"""

import logging
import platform

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)


def _set_prop(widget, prop: str, value: str) -> None:
    """Set a Qt dynamic property and force stylesheet re-evaluation.

    Args:
        widget: The QWidget to update.
        prop: Property name string.
        value: Property value string.
    """
    widget.setProperty(prop, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _uptime() -> str:
    """Return system uptime as a human-readable string.

    Returns:
        String like "4h 22m" or "2d 3h".
    """
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        if days > 0:
            return f"{days}d {hours}h"
        return f"{hours}h {minutes}m"
    except OSError:
        return "n/a"


class PowerProfileCard(QFrame):
    """Three-button power profile selector card.

    Emits power_changed when the user clicks a profile button.
    The active button is highlighted with the accent colour.

    Attributes:
        power_changed: Signal emitted with the selected profile string.
        _buttons: Dict mapping profile name to QPushButton.
        _current: Currently active profile string.

    Example:
        card = PowerProfileCard()
        card.power_changed.connect(client.send_power)
        card.set_profile("balanced")
    """

    power_changed = pyqtSignal(str)

    _PROFILES = ("performance", "balanced", "power-saver")

    def __init__(self, parent: QWidget | None = None):
        """Initialise the power profile card.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("ControlCard")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumHeight(300)

        self._current: str = "balanced"
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        label = QLabel("POWER PROFILE")
        label.setObjectName("SectionLabel")
        layout.addWidget(label)
        layout.addSpacing(4)

        for profile in self._PROFILES:
            btn = QPushButton(profile.upper())
            btn.setObjectName("ProfileButton")
            btn.clicked.connect(lambda checked, p=profile: self._on_clicked(p))
            self._buttons[profile] = btn
            layout.addWidget(btn)

        layout.addStretch()

        self._current_label = QLabel("current: balanced")
        self._current_label.setObjectName("CardSubLabel")
        layout.addWidget(self._current_label)

    def set_profile(self, profile: str) -> None:
        """Update the active profile button without emitting a signal.

        Args:
            profile: Profile name — "performance", "balanced", or "power-saver".
        """
        if profile not in self._PROFILES:
            return
        self._current = profile
        self._refresh_buttons()
        self._current_label.setText(f"current: {profile}")

    def _on_clicked(self, profile: str) -> None:
        self._current = profile
        self._refresh_buttons()
        self._current_label.setText(f"current: {profile}")
        self.power_changed.emit(profile)

    def _refresh_buttons(self) -> None:
        for profile, btn in self._buttons.items():
            _set_prop(btn, "active", "true" if profile == self._current else "false")


class FanControlCard(QFrame):
    """Fan mode toggle and threshold editor card.

    Top half: AUTO / MAX toggle buttons.
    Bottom half: Spinboxes for cpu_warn, cpu_critical, cpu_recover,
                 gpu_warn, gpu_critical with a SAVE button.

    Attributes:
        fan_changed: Signal emitted with "auto" or "max".
        thresholds_changed: Signal emitted with threshold dict.
        _btn_auto: Auto mode button.
        _btn_max: Max mode button.
        _spinboxes: Dict mapping threshold key to QDoubleSpinBox.

    Example:
        card = FanControlCard()
        card.fan_changed.connect(client.send_fan)
        card.thresholds_changed.connect(client.send_thresholds)
        card.set_fan_mode("auto")
        card.set_thresholds({"cpu_warn": 85.0, "cpu_critical": 90.0})
    """

    fan_changed = pyqtSignal(str)
    thresholds_changed = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None):
        """Initialise the fan control card.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("ControlCard")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumHeight(300)

        self._current_mode: str = "auto"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        fan_label = QLabel("FAN CONTROL")
        fan_label.setObjectName("SectionLabel")
        layout.addWidget(fan_label)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(6)

        self._btn_max = QPushButton("MAX")
        self._btn_auto = QPushButton("AUTO")

        for btn in (self._btn_max, self._btn_auto):
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

        self._btn_max.clicked.connect(lambda: self._on_fan_clicked("max"))
        self._btn_auto.clicked.connect(lambda: self._on_fan_clicked("auto"))

        toggle_row.addWidget(self._btn_max)
        toggle_row.addWidget(self._btn_auto)
        layout.addLayout(toggle_row)

        self._mode_label = QLabel("mode: auto")
        self._mode_label.setObjectName("CardSubLabel")
        layout.addWidget(self._mode_label)

        layout.addSpacing(8)

        thresh_label = QLabel("THRESHOLDS")
        thresh_label.setObjectName("SectionLabel")
        layout.addWidget(thresh_label)

        self._spinboxes: dict[str, QDoubleSpinBox] = {}

        thresh_grid = QGridLayout()
        thresh_grid.setSpacing(6)
        thresh_grid.setContentsMargins(0, 4, 0, 0)

        rows = [
            ("cpu_warn", "CPU WARN", 50.0, 110.0, 85.0),
            ("cpu_critical", "CPU CRITICAL", 50.0, 110.0, 90.0),
            ("cpu_recover", "CPU RECOVER", 40.0, 100.0, 75.0),
            ("gpu_warn", "GPU WARN", 50.0, 110.0, 80.0),
            ("gpu_critical", "GPU CRITICAL", 50.0, 110.0, 90.0),
        ]

        for row_idx, (key, label_text, min_v, max_v, default) in enumerate(rows):
            key_label = QLabel(label_text)
            key_label.setObjectName("ThreshKey")

            spinbox = QDoubleSpinBox()
            spinbox.setRange(min_v, max_v)
            spinbox.setValue(default)
            spinbox.setSuffix(" °C")
            spinbox.setDecimals(1)
            spinbox.setSingleStep(1.0)
            spinbox.setFixedWidth(90)

            self._spinboxes[key] = spinbox

            thresh_grid.addWidget(key_label, row_idx, 0)
            thresh_grid.addWidget(spinbox, row_idx, 1, Qt.AlignmentFlag.AlignRight)

        layout.addLayout(thresh_grid)

        self._save_btn = QPushButton("SAVE THRESHOLDS")
        self._save_btn.setObjectName("SaveButton")
        self._save_btn.clicked.connect(self._on_save)
        layout.addWidget(self._save_btn)

        layout.addStretch()
        self._refresh_fan_buttons()

    def set_fan_mode(self, mode: str) -> None:
        """Update the active fan mode button without emitting a signal.

        Args:
            mode: Fan mode — "auto" or "max".
        """
        if mode not in ("auto", "max"):
            return
        self._current_mode = mode
        self._refresh_fan_buttons()
        self._mode_label.setText(f"mode: {mode}")

    def set_thresholds(self, thresholds: dict) -> None:
        """Populate spinboxes from a thresholds dict.

        Skips update if any spinbox currently has focus to avoid
        overwriting values the user is actively editing.

        Args:
            thresholds: Dict with threshold keys and float values.
        """
        if any(s.hasFocus() for s in self._spinboxes.values()):
            return
        for key, spinbox in self._spinboxes.items():
            if key in thresholds:
                spinbox.setValue(float(thresholds[key]))

    def _on_fan_clicked(self, mode: str) -> None:
        self._current_mode = mode
        self._refresh_fan_buttons()
        self._mode_label.setText(f"mode: {mode}")
        self.fan_changed.emit(mode)

    def _refresh_fan_buttons(self) -> None:
        _set_prop(
            self._btn_auto,
            "active",
            "true" if self._current_mode == "auto" else "false",
        )
        _set_prop(
            self._btn_max,
            "active",
            "true" if self._current_mode == "max" else "false",
        )

    def _on_save(self) -> None:
        thresholds = {key: spinbox.value() for key, spinbox in self._spinboxes.items()}
        log.info("thresholds save requested: %s", thresholds)
        self.thresholds_changed.emit(thresholds)


class SystemInfoCard(QFrame):
    """System information display card.

    Shows static system info (kernel, hostname) and live values
    from snapshots (power profile, uptime, connection status).

    Attributes:
        _values: Dict mapping info key to QLabel value widget.
        _uptime_timer: Timer that updates the uptime label every minute.

    Example:
        card = SystemInfoCard()
        card.set_connected(True)
        card.update(snapshot)
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialise the system info card.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("ControlCard")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumHeight(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        label = QLabel("SYSTEM")
        label.setObjectName("SectionLabel")
        layout.addWidget(label)
        layout.addSpacing(4)

        self._values: dict[str, QLabel] = {}

        rows = [
            ("profile", "profile", "--"),
            ("uptime", "uptime", _uptime()),
            ("kernel", "kernel", platform.release()),
            ("hostname", "hostname", platform.node()),
            ("socket", "socket", "disconnected"),
        ]

        for key, key_text, default in rows:
            row = QHBoxLayout()
            row.setSpacing(8)

            key_label = QLabel(key_text)
            key_label.setObjectName("SysKey")
            key_label.setFixedWidth(70)

            val_label = QLabel(default)
            val_label.setWordWrap(True)

            if key == "socket":
                val_label.setObjectName("StatusDisconnected")
            else:
                val_label.setObjectName("SysValue")

            self._values[key] = val_label

            row.addWidget(key_label)
            row.addWidget(val_label)
            row.addStretch()
            layout.addLayout(row)

        layout.addStretch()

        self._uptime_timer = QTimer()
        self._uptime_timer.timeout.connect(self._refresh_uptime)
        self._uptime_timer.start(60_000)

    def update(self, snapshot: dict) -> None:
        """Update live values from a snapshot dict.

        Args:
            snapshot: Decoded snapshot dict containing power_profile key.
        """
        profile = snapshot.get("power_profile") or "--"
        self._values["profile"].setText(profile.upper())

    def set_connected(self, connected: bool) -> None:
        """Update the socket connection status label.

        Args:
            connected: True if the daemon socket is connected.
        """
        label = self._values["socket"]
        if connected:
            label.setObjectName("StatusConnected")
            label.setText("connected")
        else:
            label.setObjectName("StatusDisconnected")
            label.setText("disconnected")
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _refresh_uptime(self) -> None:
        self._values["uptime"].setText(_uptime())


class ControlsPanel(QWidget):
    """Three-card controls row — power profile, fan control, system info.

    Aggregates signals from child cards and re-emits them so the
    main window only needs to connect to this panel.

    Signals:
        fan_changed: Emitted when user changes fan mode.
        power_changed: Emitted when user changes power profile.
        thresholds_changed: Emitted when user saves new thresholds.

    Attributes:
        _power_card: Power profile selector card.
        _fan_card: Fan mode toggle and threshold editor card.
        _sys_card: System information card.

    Example:
        panel = ControlsPanel()
        panel.fan_changed.connect(client.send_fan)
        panel.power_changed.connect(client.send_power)
        panel.thresholds_changed.connect(client.send_thresholds)
        client.snapshot_received.connect(panel.update)
    """

    fan_changed = pyqtSignal(str)
    power_changed = pyqtSignal(str)
    thresholds_changed = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None):
        """Initialise the controls panel with three cards.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._power_card = PowerProfileCard()
        self._fan_card = FanControlCard()
        self._sys_card = SystemInfoCard()

        self._power_card.power_changed.connect(self.power_changed)
        self._fan_card.fan_changed.connect(self.fan_changed)
        self._fan_card.thresholds_changed.connect(self.thresholds_changed)

        layout.addWidget(self._power_card)
        layout.addWidget(self._fan_card)
        layout.addWidget(self._sys_card)

    def update(self, snapshot: dict) -> None:
        """Update all cards from a snapshot dict.

        Args:
            snapshot: Decoded snapshot dict from the daemon.
        """
        profile = snapshot.get("power_profile")
        if profile:
            self._power_card.set_profile(profile)

        fan_mode = snapshot.get("fan_mode")
        if fan_mode:
            self._fan_card.set_fan_mode(fan_mode)

        thresholds = snapshot.get("thresholds")
        if thresholds:
            self._fan_card.set_thresholds(thresholds)

        self._sys_card.update(snapshot)

    def set_connected(self, connected: bool) -> None:
        """Update connection status in system info card.

        Args:
            connected: True if daemon socket is connected.
        """
        self._sys_card.set_connected(connected)
