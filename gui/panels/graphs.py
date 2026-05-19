"""
gui/panels/graphs.py
--------------------
Graphs panel — 60-second history charts for CPU temp, GPU temp,
and fan speeds (fan 1 + fan 2 on the same graph).

Each graph:
    - Maintains a fixed-length deque of data points per series
    - Draws a filled area chart using QPainter directly
    - Shows current value and label overlay
    - Updates on every snapshot tick

No external charting library needed — pure QPainter.
"""

import logging
from collections import deque

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from config import HISTORY_LENGTH

log = logging.getLogger(__name__)

_FILL_ALPHA = 40


class GraphWidget(QFrame):
    """A filled area chart showing a rolling history of one or two series.

    Draws directly with QPainter — no external charting dependency.
    When a second series is provided it is drawn on top of the first
    using a different colour, sharing the same Y axis.

    Attributes:
        _data: Rolling deque of float values for series 1.
        _data2: Optional rolling deque for series 2.
        _color: Line and fill colour for series 1.
        _color2: Line and fill colour for series 2.
        _label: Chart title shown in the top-left.
        _unit: Unit string appended to the current value overlay.
        _y_max: Fixed maximum for the Y axis. If None, uses data max.

    Example:
        graph = GraphWidget(
            label="FAN SPEED · 60s",
            color="#fb923c",
            color2="#fdba74",
            unit=" RPM",
            y_max=5500.0,
        )
        graph.push(2400.0)
        graph.push2(0.0)
    """

    def __init__(
        self,
        label: str,
        color: str,
        unit: str,
        y_max: float | None = None,
        color2: str | None = None,
        label2: str | None = None,
        parent: QWidget | None = None,
    ):
        """Initialise the graph widget.

        Args:
            label: Title string overlaid in the top-left corner.
            color: Hex colour for series 1 line and fill.
            unit: Unit string shown after the current value.
            y_max: Fixed Y-axis maximum. If None, scales to data range.
            color2: Optional hex colour for series 2. If None, only
                one series is drawn.
            label2: Optional label for the series 2 value overlay.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("GraphCard")
        self.setMinimumHeight(90)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self._data: deque[float] = deque(maxlen=HISTORY_LENGTH)
        self._data2: deque[float] | None = (
            deque(maxlen=HISTORY_LENGTH) if color2 else None
        )
        self._color = color
        self._color2 = color2
        self._label = label
        self._label2 = label2
        self._unit = unit
        self._y_max = y_max
        self._current: float | None = None
        self._current2: float | None = None

    def push(self, value: float | None):
        """Append a new data point for series 1 and trigger a repaint.

        Args:
            value: New value to append. Skipped if None.
        """
        if value is None:
            return
        self._current = value
        self._data.append(value)
        self.update()

    def push2(self, value: float | None):
        """Append a new data point for series 2 and trigger a repaint.

        Args:
            value: New value to append. Skipped if None or no series 2.
        """
        if value is None or self._data2 is None:
            return
        self._current2 = value
        self._data2.append(value)
        self.update()

    def clear(self):
        """Clear all data points and repaint."""
        self._data.clear()
        if self._data2 is not None:
            self._data2.clear()
        self._current = None
        self._current2 = None
        self.update()

    def set_warn_line(self, value: float):
        """Set a dashed horizontal warn threshold line.

        Args:
            value: Y value at which to draw the dashed line.
        """
        self._warn_line = value
        self.update()

    def paintEvent(self, event):
        """Draw the graph using QPainter.

        Args:
            event: QPaintEvent from the Qt framework.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        pad_top = 28
        pad_bottom = 8
        pad_left = 8
        pad_right = 8

        draw_h = h - pad_top - pad_bottom
        draw_w = w - pad_left - pad_right

        painter.fillRect(0, 0, w, h, QColor("#110e0a"))

        font = QFont("Courier New", 7)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        painter.setFont(font)
        painter.setPen(QColor("#e6ee57"))
        painter.drawText(pad_left + 2, 14, self._label)

        # current value overlays
        if self._current is not None:
            val_font = QFont("Courier New", 9)
            val_font.setBold(True)
            painter.setFont(val_font)
            painter.setPen(QColor(self._color))
            val_str = f"{self._current:.0f}{self._unit}"
            # shift left if two values to show
            x_pos = w - 120 if self._color2 else w - 60
            painter.drawText(x_pos, 16, val_str)

        if self._current2 is not None and self._color2:
            val_font = QFont("Courier New", 9)
            val_font.setBold(True)
            painter.setFont(val_font)
            painter.setPen(QColor(self._color2))
            val_str2 = f"{self._current2:.0f}{self._unit}"
            painter.drawText(w - 60, 16, val_str2)

        if len(self._data) < 2:
            painter.end()
            return

        # compute y scale across both series
        data_list = list(self._data)
        all_values = list(data_list)
        if self._data2 and len(self._data2) > 0:
            all_values += list(self._data2)

        y_max = self._y_max if self._y_max is not None else max(all_values) * 1.1
        y_min = 0.0

        if y_max <= y_min:
            y_max = y_min + 1.0

        def to_screen(i: int, val: float) -> QPointF:
            x = pad_left + (i / (HISTORY_LENGTH - 1)) * draw_w
            y = pad_top + draw_h - ((val - y_min) / (y_max - y_min)) * draw_h
            return QPointF(x, y)

        def draw_series(
            data: list[float],
            color: str,
        ) -> None:
            pad_count = HISTORY_LENGTH - len(data)
            padded = [data[0]] * pad_count + data
            points = [to_screen(i, v) for i, v in enumerate(padded)]

            fill_path = QPainterPath()
            fill_path.moveTo(points[0])
            for pt in points[1:]:
                fill_path.lineTo(pt)
            fill_path.lineTo(QPointF(points[-1].x(), pad_top + draw_h))
            fill_path.lineTo(QPointF(points[0].x(), pad_top + draw_h))
            fill_path.closeSubpath()

            fill_color = QColor(color)
            fill_color.setAlpha(_FILL_ALPHA)
            painter.fillPath(fill_path, QBrush(fill_color))

            line_path = QPainterPath()
            line_path.moveTo(points[0])
            for pt in points[1:]:
                line_path.lineTo(pt)

            pen = QPen(QColor(color))
            pen.setWidth(2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(line_path)

        # draw series 1
        draw_series(data_list, self._color)

        # draw series 2 on top
        if self._data2 and len(self._data2) >= 2:
            draw_series(list(self._data2), self._color2)

        # threshold line
        if self._y_max is not None and hasattr(self, "_warn_line"):
            warn_y = (
                pad_top
                + draw_h
                - ((self._warn_line - y_min) / (y_max - y_min)) * draw_h
            )
            pen = QPen(QColor("#3d2010"))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(
                int(pad_left),
                int(warn_y),
                int(pad_left + draw_w),
                int(warn_y),
            )

        painter.end()


class GraphsPanel(QWidget):
    """Row of three area charts — CPU temp, GPU temp, fan 1 + fan 2 speed.

    Attributes:
        _cpu_graph: CPU temperature history chart.
        _gpu_graph: GPU temperature history chart.
        _fan_graph: Fan speed chart showing fan 1 and fan 2.
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialise the graphs panel with three graph widgets.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._cpu_graph = GraphWidget(
            label="CPU TEMPERATURE · 60s",
            color="#f97316",
            unit="°C",
            y_max=100.0,
        )
        self._gpu_graph = GraphWidget(
            label="GPU TEMPERATURE · 60s",
            color="#eab308",
            unit="°C",
            y_max=100.0,
        )
        self._fan_graph = GraphWidget(
            label="FAN SPEED · 60s",
            color="#fb923c",
            color2="#fdba74",
            unit=" RPM",
            y_max=5500.0,
        )

        for graph in (self._cpu_graph, self._gpu_graph, self._fan_graph):
            layout.addWidget(graph)

    def update(self, snapshot: dict):
        """Push new data points from a snapshot dict.

        Args:
            snapshot: Decoded snapshot dict from the daemon.
        """
        self._cpu_graph.push(snapshot.get("cpu_temp"))
        self._gpu_graph.push(snapshot.get("gpu_temp"))
        self._fan_graph.push(snapshot.get("fan1_rpm"))
        self._fan_graph.push2(snapshot.get("fan2_rpm"))

        thresholds = snapshot.get("thresholds", {})
        self._cpu_graph.set_warn_line(thresholds.get("cpu_warn", 85.0))
        self._gpu_graph.set_warn_line(thresholds.get("gpu_warn", 80.0))

    def clear(self):
        """Clear all graph history on daemon disconnect."""
        self._cpu_graph.clear()
        self._gpu_graph.clear()
        self._fan_graph.clear()
