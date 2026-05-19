"""
gui/panels/metrics.py
---------------------
Metrics panel — displays live hardware readings across two rows.

Row 1: CPU TEMP · GPU TEMP · FAN 1 RPM · FAN 2 RPM · CPU LOAD · RAM
Row 2: GPU UTIL · GPU VRAM · GPU POWER · CPU MODEL · GPU MODEL

Update by calling update(snapshot) with a decoded snapshot dict.
No IPC logic here — the main window wires snapshot_received to update().
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
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


def _status_from_temp(temp: float, warn: float, critical: float) -> str:
    """Map a temperature to a status string.

    Args:
        temp: Current temperature in degrees Celsius.
        warn: Warning threshold in degrees Celsius.
        critical: Critical threshold in degrees Celsius.

    Returns:
        One of "safe", "warn", or "critical".
    """
    if temp >= critical:
        return "critical"
    if temp >= warn:
        return "warn"
    return "safe"


def _status_from_rpm(rpm: int) -> str:
    """Map a fan RPM to a status string.

    Args:
        rpm: Current fan speed in RPM.

    Returns:
        One of "idle", "normal", or "warn".
    """
    if rpm == 0:
        return "idle"
    if rpm > 4000:
        return "warn"
    return "normal"


def _status_from_load(load: float) -> str:
    """Map a CPU load percentage to a status string.

    Args:
        load: CPU usage percentage 0.0-100.0.

    Returns:
        One of "low", "normal", or "warn".
    """
    if load >= 80:
        return "warn"
    if load >= 40:
        return "normal"
    return "low"


def _status_from_util(util: float) -> str:
    """Map GPU utilization percentage to a status string.

    Args:
        util: GPU utilization percentage 0.0-100.0.

    Returns:
        One of "idle", "normal", or "warn".
    """
    if util >= 80:
        return "warn"
    if util >= 10:
        return "normal"
    return "idle"


def _status_from_power(power: float) -> str:
    """Map GPU power draw to a status string.

    Args:
        power: GPU power draw in Watts.

    Returns:
        One of "low", "normal", or "warn".
    """
    if power >= 80:
        return "warn"
    if power >= 30:
        return "normal"
    return "low"


def _temp_bar_value(temp: float, critical: float) -> int:
    """Convert temperature to a 0-100 progress bar value.

    Args:
        temp: Current temperature in degrees Celsius.
        critical: Critical threshold used as the 100% mark.

    Returns:
        Integer 0-100 representing fill level.
    """
    return min(100, int((temp / critical) * 100))


class MetricCard(QFrame):
    """A single hardware metric display card.

    Shows a large coloured value, unit, sub-label, status bar, and
    status text. The left border colour is set via inline stylesheet
    to match the metric source colour.

    Attributes:
        _value_label: The large number display.
        _sublabel: Small descriptive text below the value.
        _status_bar: Progress bar showing relative level.
        _status_label: Text label showing status string.

    Example:
        card = MetricCard(
            label="CPU     TEMP",
            sublabel="CPU TEMPERATURE",
            unit="°C",
            source="cpu",
            border="#f97316",
        )
        card.set_value("69", status="safe", bar_value=58)
    """

    def __init__(
        self,
        label: str,
        sublabel: str,
        unit: str,
        source: str,
        border: str,
        parent: QWidget | None = None,
    ):
        """Initialise the metric card.

        Args:
            label: Card header text.
            sublabel: Small text below the value.
            unit: Unit string shown after the value e.g. "°C".
            source: Source key for QSS property.
            border: CSS hex colour for the left accent border.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setStyleSheet(f"QFrame#MetricCard {{ border-left: 3px solid {border}; }}")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setMinimumWidth(110)
        self.setMaximumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self._label = QLabel(label)
        self._label.setObjectName("CardLabel")
        layout.addWidget(self._label)

        value_row = QHBoxLayout()
        value_row.setSpacing(2)
        value_row.setContentsMargins(0, 0, 0, 0)

        self._value_label = QLabel("--")
        self._value_label.setObjectName("MetricValue")
        _set_prop(self._value_label, "source", source)
        value_row.addWidget(self._value_label)

        self._unit_label = QLabel(unit)
        self._unit_label.setObjectName("UnitLabel")
        self._unit_label.setStyleSheet(f"color: {border};")
        self._unit_label.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft
        )
        self._unit_label.setContentsMargins(0, 0, 0, 8)
        value_row.addWidget(self._unit_label)
        value_row.addStretch()
        layout.addLayout(value_row)

        self._sublabel = QLabel(sublabel)
        self._sublabel.setObjectName("CardSubLabel")
        layout.addWidget(self._sublabel)

        layout.addSpacing(6)

        self._status_bar = QProgressBar()
        self._status_bar.setRange(0, 100)
        self._status_bar.setValue(0)
        self._status_bar.setTextVisible(False)
        self._status_bar.setFixedHeight(3)
        _set_prop(self._status_bar, "status", "safe")
        layout.addWidget(self._status_bar)

        self._status_label = QLabel("--")
        self._status_label.setObjectName("StatusLabel")
        _set_prop(self._status_label, "status", "safe")
        layout.addWidget(self._status_label)

    def set_value(
        self,
        display: str,
        status: str,
        bar_value: int,
        sublabel: str | None = None,
    ) -> None:
        """Update the card display.

        Args:
            display: Formatted string to show as the main value.
            status: Status string for QSS property.
            bar_value: Integer 0-100 for the progress bar fill.
            sublabel: Optional new sublabel text.
        """
        self._value_label.setText(display)
        self._status_bar.setValue(bar_value)
        self._status_label.setText(status)

        if sublabel is not None:
            self._sublabel.setText(sublabel)

        _set_prop(self._status_bar, "status", status)
        _set_prop(self._status_label, "status", status)
        _set_prop(
            self._value_label,
            "status",
            (
                status
                if status in ("warn", "critical")
                else self._value_label.property("source")
            ),
        )

    def set_text_only(self, line1: str, line2: str = "") -> None:
        """Show plain text lines instead of a large metric value.

        Used for model name cards where no numeric value exists.

        Args:
            line1: Primary text line.
            line2: Secondary text line shown as sublabel.
        """
        self._value_label.hide()
        self._unit_label.hide()
        self._status_bar.hide()
        self._status_label.hide()

        self._label_line1 = QLabel(line1)
        self._label_line1.setObjectName("SysValue")
        self._label_line1.setWordWrap(True)
        self.layout().addWidget(self._label_line1)

        if line2:
            self._label_line2 = QLabel(line2)
            self._label_line2.setObjectName("CardSubLabel")
            self._label_line2.setWordWrap(True)
            self.layout().addWidget(self._label_line2)

        self.layout().addStretch()

    def set_unavailable(self) -> None:
        """Show dashes when no data is available."""
        self._value_label.setText("--")
        self._status_bar.setValue(0)
        self._status_label.setText("--")
        _set_prop(self._status_bar, "status", "idle")
        _set_prop(self._status_label, "status", "idle")


class CoreBarRow(QWidget):
    """A single horizontal bar row showing one CPU core's usage and frequency.

    Attributes:
        _bar: Progress bar showing usage percentage.
        _pct_label: Usage percentage label.
        _freq_label: Frequency label in MHz.

    Example:
        row = CoreBarRow(core_index=0)
        row.update(usage=23.5, freq=1901)
    """

    def __init__(self, core_index: int, parent: QWidget | None = None):
        """Initialise the core bar row.

        Args:
            core_index: Zero-based core index shown as label.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        core_label = QLabel(f"core {core_index:2d}")
        core_label.setObjectName("CardSubLabel")
        core_label.setFixedWidth(80)
        core_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(core_label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(30)
        _set_prop(self._bar, "status", "normal")
        layout.addWidget(self._bar, stretch=1)

        self._pct_label = QLabel("0%")
        self._pct_label.setObjectName("ThreshValue")
        self._pct_label.setFixedWidth(45)
        self._pct_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._pct_label)

        self._freq_label = QLabel("-- MHz")
        self._freq_label.setObjectName("CardSubLabel")
        self._freq_label.setFixedWidth(80)
        self._freq_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._freq_label)

    def update(self, usage: float, freq: int) -> None:
        """Update the bar with new usage and frequency values.

        Args:
            usage: Core usage percentage 0.0-100.0.
            freq: Core frequency in MHz.
        """
        self._bar.setValue(int(usage))
        self._pct_label.setText(f"{usage:.0f}%")
        self._freq_label.setText(f"{freq} MHz")
        _set_prop(self._bar, "status", "warn" if usage >= 80 else "normal")


class CoresPanel(QFrame):
    """Two-column grid of horizontal core bars for all CPU cores.

    Attributes:
        _bars: List of CoreBarRow widgets, one per core.

    Example:
        panel = CoresPanel(core_count=16)
        panel.update(cores=[{"core": 0, "usage": 23.5, "freq": 1901}, ...])
    """

    def __init__(self, core_count: int = 16, parent: QWidget | None = None):
        """Initialise the cores panel.

        Args:
            core_count: Number of CPU cores to display.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("GraphCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        label = QLabel(f"CPU CORES — {core_count} CORES")
        label.setObjectName("SectionLabel")
        outer.addWidget(label)

        grid = QHBoxLayout()
        grid.setSpacing(16)
        outer.addLayout(grid)

        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        left_col.setSpacing(4)
        right_col.setSpacing(4)

        self._bars: list[CoreBarRow] = []
        half = core_count // 2

        for i in range(core_count):
            bar = CoreBarRow(core_index=i + 1)
            self._bars.append(bar)
            if i < half:
                left_col.addWidget(bar)
            else:
                right_col.addWidget(bar)

        grid.addLayout(left_col)
        grid.addLayout(right_col)

    def update(self, cores: list[dict]) -> None:
        """Update all core bars from a cores list.

        Args:
            cores: List of dicts each with core, usage, and freq keys.
        """
        for core_data in cores:
            idx = core_data.get("core", 0)
            if idx < len(self._bars):
                self._bars[idx].update(
                    usage=core_data.get("usage", 0.0),
                    freq=core_data.get("freq", 0),
                )

    def clear(self) -> None:
        """Reset all bars to zero."""
        for bar in self._bars:
            bar.update(usage=0.0, freq=0)


class MetricsPanel(QWidget):
    """Two-row metrics display panel.

    Row 1: CPU temp, GPU temp, fan 1 RPM, fan 2 RPM, CPU load, RAM.
    Row 2: GPU utilization, GPU VRAM, GPU power, CPU model, GPU model.

    Attributes:
        _cpu_card: CPU temperature card.
        _gpu_card: GPU temperature card.
        _fan1_card: Fan 1 RPM card.
        _fan2_card: Fan 2 RPM card.
        _load_card: CPU load percentage card.
        _ram_card: RAM usage card.
        _gpu_util_card: GPU utilization card.
        _gpu_vram_card: GPU VRAM percentage card.
        _gpu_power_card: GPU power draw card.
        _cpu_model_card: CPU model name card.
        _gpu_model_card: GPU model name card.

    Example:
        panel = MetricsPanel()
        client.snapshot_received.connect(panel.update)
        layout.addWidget(panel)
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialise the metrics panel with all rows.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self._cpu_card = MetricCard(
            label="CPU          TEMP",
            sublabel="CPU TEMPERATURE",
            unit="°C",
            source="cpu",
            border="#f97316",
        )
        self._gpu_card = MetricCard(
            label="GPU          TEMP",
            sublabel="GPU TEMPERATURE",
            unit="°C",
            source="gpu",
            border="#eab308",
        )
        self._fan1_card = MetricCard(
            label="FAN 1        RPM",
            sublabel="ROTATIONS/MIN",
            unit="",
            source="fan",
            border="#fb923c",
        )
        self._fan2_card = MetricCard(
            label="FAN 2        RPM",
            sublabel="ROTATIONS/MIN",
            unit="",
            source="fan",
            border="#fb923c",
        )
        self._load_card = MetricCard(
            label="LOAD         CPU",
            sublabel="CPU USAGE",
            unit="%",
            source="load",
            border="#22c55e",
        )
        self._ram_card = MetricCard(
            label="RAM          USED",
            sublabel="-- / -- GB",
            unit="%",
            source="load",
            border="#06b6d4",
        )

        for card in (
            self._cpu_card,
            self._gpu_card,
            self._fan1_card,
            self._fan2_card,
            self._load_card,
            self._ram_card,
        ):
            row1.addWidget(card)

        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self._gpu_util_card = MetricCard(
            label="GPU          UTIL",
            sublabel="GPU UTILIZATION",
            unit="%",
            source="gpu",
            border="#a855f7",
        )
        self._gpu_vram_card = MetricCard(
            label="GPU          VRAM",
            sublabel="-- / -- MiB",
            unit="%",
            source="gpu",
            border="#a855f7",
        )
        self._gpu_power_card = MetricCard(
            label="GPU         POWER",
            sublabel="POWER DRAW",
            unit="W",
            source="gpu",
            border="#a855f7",
        )
        self._cpu_model_card = MetricCard(
            label="CPU",
            sublabel="",
            unit="",
            source="cpu",
            border="#3d2f1a",
        )
        self._gpu_model_card = MetricCard(
            label="GPU",
            sublabel="",
            unit="",
            source="gpu",
            border="#3d2f1a",
        )

        for card in (
            self._gpu_util_card,
            self._gpu_vram_card,
            self._gpu_power_card,
            self._cpu_model_card,
            self._gpu_model_card,
        ):
            row2.addWidget(card)

        layout.addLayout(row2)

        self._cpu_model_set = False
        self._gpu_model_set = False

    def update(self, snapshot: dict) -> None:
        """Update all rows from a snapshot dict.

        Args:
            snapshot: Decoded snapshot dict from the daemon.
        """
        thresholds = snapshot.get("thresholds", {})
        cpu_warn = thresholds.get("cpu_warn", 85.0)
        cpu_crit = thresholds.get("cpu_critical", 90.0)
        gpu_warn = thresholds.get("gpu_warn", 80.0)
        gpu_crit = thresholds.get("gpu_critical", 90.0)

        self._update_cpu(snapshot.get("cpu_temp"), cpu_warn, cpu_crit)
        self._update_gpu_temp(snapshot.get("gpu_temp"), gpu_warn, gpu_crit)
        self._update_fan1(snapshot.get("fan1_rpm"))
        self._update_fan2(snapshot.get("fan2_rpm"))
        self._update_load(snapshot.get("cpu_usage"))
        self._update_ram(
            snapshot.get("ram_used"),
            snapshot.get("ram_total"),
            snapshot.get("ram_percent"),
        )
        self._update_gpu_util(snapshot.get("gpu_util"))
        self._update_gpu_vram(
            snapshot.get("gpu_vram_used"),
            snapshot.get("gpu_vram_total"),
        )
        self._update_gpu_power(snapshot.get("gpu_power"))
        self._update_cpu_model(snapshot.get("cpu_model"))
        self._update_gpu_model(snapshot.get("gpu_name"))

    def clear(self) -> None:
        """Set all cards to unavailable state on disconnect."""
        for card in (
            self._cpu_card,
            self._gpu_card,
            self._fan1_card,
            self._fan2_card,
            self._load_card,
            self._ram_card,
            self._gpu_util_card,
            self._gpu_vram_card,
            self._gpu_power_card,
        ):
            card.set_unavailable()

    def _update_cpu(self, temp: float | None, warn: float, crit: float) -> None:
        """Update CPU temperature card.

        Args:
            temp: CPU temperature in degrees Celsius, or None.
            warn: Warning threshold.
            crit: Critical threshold.
        """
        if temp is None:
            self._cpu_card.set_unavailable()
            return
        self._cpu_card.set_value(
            display=f"{temp:.0f}",
            status=_status_from_temp(temp, warn, crit),
            bar_value=_temp_bar_value(temp, crit),
        )

    def _update_gpu_temp(self, temp: float | None, warn: float, crit: float) -> None:
        """Update GPU temperature card.

        Args:
            temp: GPU temperature in degrees Celsius, or None.
            warn: Warning threshold.
            crit: Critical threshold.
        """
        if temp is None:
            self._gpu_card.set_unavailable()
            return
        self._gpu_card.set_value(
            display=f"{temp:.0f}",
            status=_status_from_temp(temp, warn, crit),
            bar_value=_temp_bar_value(temp, crit),
        )

    def _update_fan1(self, rpm: int | None) -> None:
        """Update fan 1 RPM card.

        Args:
            rpm: Fan 1 speed in RPM, or None.
        """
        if rpm is None:
            self._fan1_card.set_unavailable()
            return
        self._fan1_card.set_value(
            display=f"{rpm:,}",
            status=_status_from_rpm(rpm),
            bar_value=min(100, int((rpm / 5000) * 100)),
        )

    def _update_fan2(self, rpm: int | None) -> None:
        """Update fan 2 RPM card.

        Args:
            rpm: Fan 2 speed in RPM, or None.
        """
        if rpm is None:
            self._fan2_card.set_unavailable()
            return
        self._fan2_card.set_value(
            display=f"{rpm:,}",
            status=_status_from_rpm(rpm),
            bar_value=min(100, int((rpm / 5000) * 100)),
        )

    def _update_load(self, load: float | None) -> None:
        """Update CPU load card.

        Args:
            load: CPU usage percentage 0.0-100.0, or None.
        """
        if load is None:
            self._load_card.set_unavailable()
            return
        self._load_card.set_value(
            display=f"{load:.0f}",
            status=_status_from_load(load),
            bar_value=int(load),
        )

    def _update_ram(
        self,
        used: float | None,
        total: float | None,
        percent: float | None,
    ) -> None:
        """Update RAM usage card.

        Args:
            used: RAM used in GB, or None.
            total: RAM total in GB, or None.
            percent: RAM usage percentage 0.0-100.0, or None.
        """
        if used is None or total is None or percent is None:
            self._ram_card.set_unavailable()
            return
        status = "warn" if percent >= 80 else "normal" if percent >= 40 else "low"
        self._ram_card.set_value(
            display=f"{percent:.0f}",
            status=status,
            bar_value=int(percent),
            sublabel=f"{used:.1f} / {total:.1f} GB",
        )

    def _update_gpu_util(self, util: float | None) -> None:
        """Update GPU utilization card.

        Args:
            util: GPU utilization percentage 0.0-100.0, or None.
        """
        if util is None:
            self._gpu_util_card.set_unavailable()
            return
        self._gpu_util_card.set_value(
            display=f"{util:.0f}",
            status=_status_from_util(util),
            bar_value=int(util),
        )

    def _update_gpu_vram(self, used: int | None, total: int | None) -> None:
        """Update GPU VRAM card showing percentage with raw in sublabel.

        Args:
            used: VRAM used in MiB, or None.
            total: VRAM total in MiB, or None.
        """
        if used is None or total is None:
            self._gpu_vram_card.set_unavailable()
            return
        pct = (used / total * 100) if total > 0 else 0.0
        status = "warn" if pct >= 80 else "normal" if pct >= 40 else "low"
        self._gpu_vram_card.set_value(
            display=f"{pct:.1f}",
            status=status,
            bar_value=int(pct),
            sublabel=f"{used} / {total} MiB",
        )

    def _update_gpu_power(self, power: float | None) -> None:
        """Update GPU power draw card.

        Args:
            power: GPU power draw in Watts, or None.
        """
        if power is None:
            self._gpu_power_card.set_unavailable()
            return
        self._gpu_power_card.set_value(
            display=f"{power:.1f}",
            status=_status_from_power(power),
            bar_value=min(100, int((power / 115) * 100)),
        )

    def _update_cpu_model(self, model: str | None) -> None:
        """Set CPU model name — text only, called once on first snapshot.

        Args:
            model: CPU model name string, or None.
        """
        if model and not self._cpu_model_set:
            self._cpu_model_set = True
            short = model.replace("with Radeon Graphics", "").strip()
            self._cpu_model_card.set_text_only(line1=short, line2="CPU MODEL")

    def _update_gpu_model(self, name: str | None) -> None:
        """Set GPU model name — text only, called once on first snapshot.

        Args:
            name: GPU model name string, or None.
        """
        if name and not self._gpu_model_set:
            self._gpu_model_set = True
            self._gpu_model_card.set_text_only(line1=name, line2="GPU MODEL")
