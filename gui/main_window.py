"""
gui/main_window.py
------------------
Main application window — assembles all panels and wires signals.

Layout:
    title bar
    metric cards (always visible)
    tab bar: GRAPHS + CORES · CONTROLS
    alert banner (visible only when alerts are active)
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import APP_NAME, APP_VERSION
from gui.ipc_client import IPCClient
from gui.notifier import Notifier
from gui.panels.controls import ControlsPanel
from gui.panels.graphs import GraphsPanel
from gui.panels.metrics import CoresPanel, MetricsPanel
from gui.tray import SystemTray

log = logging.getLogger(__name__)


class AlertBanner(QFrame):
    """Full-width alert banner shown below the tab area.

    Hidden when no alerts are active. Shows the most severe active
    alert with appropriate border colour.

    Attributes:
        _icon: Alert icon label.
        _text: Alert message label.
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialise the alert banner in hidden state.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setObjectName("AlertBanner")
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._icon = QLabel("△")
        self._icon.setObjectName("AlertText")
        self._icon.setFixedWidth(16)
        layout.addWidget(self._icon)

        self._text = QLabel("")
        self._text.setObjectName("AlertText")
        self._text.setWordWrap(True)
        layout.addWidget(self._text)
        layout.addStretch()

    def show_alert(self, level: str, message: str) -> None:
        """Display an alert message.

        Args:
            level: Alert level — "warn" or "critical".
            message: Human-readable alert message string.
        """
        self._text.setText(message)
        self.setProperty("level", level)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(True)

    def clear(self) -> None:
        """Hide the banner when no alerts are active."""
        self.setVisible(False)
        self._text.setText("")


class GraphsCoresTab(QWidget):
    """Combined tab showing graphs on top and CPU cores below.

    Uses a QSplitter so the user can drag the divider between
    graphs and cores to redistribute vertical space.

    Attributes:
        _graphs: Graph panel with CPU, GPU, and fan history charts.
        _cores: CPU cores panel with 16 horizontal bars.
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialise the graphs + cores tab.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #1e1810;
            }
            QSplitter::handle:hover {
                background-color: #f97316;
            }
        """)

        self._graphs = GraphsPanel()
        self._graphs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        splitter.addWidget(self._graphs)

        cores_container = QWidget()
        cores_layout = QVBoxLayout(cores_container)
        cores_layout.setContentsMargins(0, 4, 0, 0)
        cores_layout.setSpacing(0)
        self._cores = CoresPanel(core_count=16)
        cores_layout.addWidget(self._cores)
        cores_layout.addStretch()
        splitter.addWidget(cores_container)

        splitter.setSizes([300, 450])
        layout.addWidget(splitter)

    def update_graphs(self, snapshot: dict) -> None:
        """Push new snapshot data to the graphs panel.

        Args:
            snapshot: Decoded snapshot dict from the daemon.
        """
        self._graphs.update(snapshot)

    def update_cores(self, cores: list[dict]) -> None:
        """Push new core data to the cores panel.

        Args:
            cores: List of core dicts with usage and freq keys.
        """
        self._cores.update(cores)

    def clear(self) -> None:
        """Clear all graph history and reset core bars."""
        self._graphs.clear()
        self._cores.clear()


class MainWindow(QMainWindow):
    """Main application window.

    Assembles metric panels, tab widget, and alert banner.
    Wires the IPC client signals to panel update methods and
    control panel signals back to the IPC client send methods.

    Attributes:
        _client: IPC client background thread.
        _metrics: Top two rows of metric cards.
        _graphs_cores: Combined graphs + cores tab.
        _controls: Controls panel shown in CONTROLS tab.
        _tabs: Tab widget with GRAPHS+CORES and CONTROLS tabs.
        _alert_banner: Full-width alert banner at the bottom.
        _connected: Current connection state.
    """

    def __init__(self, parent: QWidget | None = None):
        """Initialise the main window and start the IPC client.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumWidth(1000)
        self.setMinimumHeight(600)

        self._connected = False

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # title bar
        title_row = QHBoxLayout()

        title = QLabel("▶ OMEN /// SYSTEM MONITOR")
        title.setObjectName("AppTitle")
        title_row.addWidget(title)
        title_row.addStretch()

        self._conn_label = QLabel("● DISCONNECTED")
        self._conn_label.setObjectName("StatusDisconnected")
        title_row.addWidget(self._conn_label)

        layout.addLayout(title_row)

        # metric cards
        self._metrics = MetricsPanel()
        self._metrics.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self._metrics)

        # tab widget
        self._tabs = QTabWidget()
        self._tabs.setObjectName("MainTabs")
        self._tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self._graphs_cores = GraphsCoresTab()
        self._tabs.addTab(self._graphs_cores, "GRAPHS + CORES")

        self._controls = ControlsPanel()
        self._tabs.addTab(self._controls, "CONTROLS")

        layout.addWidget(self._tabs, stretch=1)

        # alert banner
        self._alert_banner = AlertBanner()
        layout.addWidget(self._alert_banner)

        # ipc client
        self._client = IPCClient()
        self._client.snapshot_received.connect(self._on_snapshot)
        self._client.connected.connect(self._on_connected)
        self._client.disconnected.connect(self._on_disconnected)
        self._client.start()

        # system tray
        self._tray = SystemTray(parent=self)
        self._tray.fan_changed.connect(self._client.send_fan)
        self._tray.power_changed.connect(self._client.send_power)
        self._tray.show_window_requested.connect(self._toggle_window)
        self._tray.quit_requested.connect(QApplication.quit)
        self._tray.show()

        # notifier
        self._notifier = Notifier(self._tray)

        # wire controls to client
        self._controls.fan_changed.connect(self._client.send_fan)
        self._controls.power_changed.connect(self._client.send_power)
        self._controls.thresholds_changed.connect(self._client.send_thresholds)

    def closeEvent(self, event) -> None:
        """Stop the IPC client gracefully on window close.

        Args:
            event: QCloseEvent from the Qt framework.
        """
        log.info("window closing — stopping IPC client")
        self._client.stop()
        event.accept()

    def _on_snapshot(self, snapshot: dict) -> None:
        """Update all panels from a new snapshot dict.

        Args:
            snapshot: Decoded snapshot dict from the daemon.
        """
        self._metrics.update(snapshot)
        self._controls.update(snapshot)
        self._graphs_cores.update_graphs(snapshot)

        if self._tabs.currentIndex() == 0:
            cores = snapshot.get("cpu_cores", [])
            if cores:
                self._graphs_cores.update_cores(cores)

        self._update_alerts(snapshot.get("alerts", []))
        self._tray.update(snapshot)
        self._notifier.process_alerts(snapshot.get("alerts", []))

    def _on_connected(self) -> None:
        """Handle daemon connection established."""
        self._connected = True
        self._conn_label.setObjectName("StatusConnected")
        self._conn_label.setText("● CONNECTED")
        self._conn_label.style().unpolish(self._conn_label)
        self._conn_label.style().polish(self._conn_label)
        self._controls.set_connected(True)
        self._tray.set_connected(True)
        log.info("GUI connected to daemon")

    def _on_disconnected(self) -> None:
        """Handle daemon connection lost."""
        self._connected = False
        self._conn_label.setObjectName("StatusDisconnected")
        self._conn_label.setText("● DISCONNECTED")
        self._conn_label.style().unpolish(self._conn_label)
        self._conn_label.style().polish(self._conn_label)
        self._metrics.clear()
        self._graphs_cores.clear()
        self._controls.set_connected(False)
        self._alert_banner.clear()
        self._tray.set_connected(False)
        self._notifier.reset()
        log.info("GUI disconnected from daemon")

    def _toggle_window(self) -> None:
        """Toggle main window visibility."""
        if self.isVisible():
            self.hide()
            self._tray._act_show.setText("show window")
        else:
            self.show()
            self.raise_()
            self.activateWindow()
            self._tray._act_show.setText("hide window")

    def _update_alerts(self, alerts: list[dict]) -> None:
        """Update the alert banner from the snapshot alerts list.

        Args:
            alerts: List of alert dicts from the snapshot.
        """
        if not alerts:
            self._alert_banner.clear()
            return

        critical = [a for a in alerts if a.get("level") == "critical"]
        active = critical[0] if critical else alerts[0]

        self._alert_banner.show_alert(
            level=active.get("level", "warn"),
            message=active.get("message", ""),
        )
