"""
gui/notifier.py
---------------
Desktop notifications for hardware alerts.

Sends system notifications when alert levels change:
    ok to warn     : warning notification
    warn to critical: critical notification
    any to ok      : recovery notification

Uses QSystemTrayIcon.showMessage() — no external dependencies.
"""

import logging

from PyQt6.QtWidgets import QSystemTrayIcon

log = logging.getLogger(__name__)

_NOTIFY_DURATION_MS = 4000


class Notifier:
    """Fires desktop notifications when alert levels change.

    Tracks the previous alert state per source so notifications
    only fire on transitions, not every second.

    Attributes:
        _tray: QSystemTrayIcon used to show notifications.
        _prev_levels: Dict mapping source to last known level.

    Example:
        notifier = Notifier(tray)
        notifier.process_alerts(snapshot.get("alerts", []))
    """

    def __init__(self, tray: QSystemTrayIcon):
        """Initialise the notifier.

        Args:
            tray: The system tray icon used to display notifications.
        """
        self._tray = tray
        self._prev_levels: dict[str, str] = {}

    def process_alerts(self, alerts: list[dict]) -> None:
        """Check alerts and fire notifications on level transitions.

        Compares current alert levels against the previous tick.
        Fires a notification only when a source transitions between
        levels, not on every tick.

        Args:
            alerts: List of alert dicts from the snapshot, each
                containing level, source, temp, and message keys.
        """
        current_levels: dict[str, dict] = {}
        for alert in alerts:
            source = alert.get("source", "")
            if source:
                current_levels[source] = alert

        all_sources = set(self._prev_levels) | set(current_levels)

        for source in all_sources:
            prev_level = self._prev_levels.get(source, "ok")
            curr_alert = current_levels.get(source)
            curr_level = curr_alert.get("level", "ok") if curr_alert else "ok"

            if curr_level == prev_level:
                continue

            if curr_level == "warn":
                self._notify_warn(curr_alert)
            elif curr_level == "critical":
                self._notify_critical(curr_alert)
            elif curr_level == "ok" and prev_level != "ok":
                self._notify_recovery(source, curr_alert)

            self._prev_levels[source] = curr_level

        for source in list(self._prev_levels):
            if source not in current_levels:
                prev = self._prev_levels.pop(source)
                if prev != "ok":
                    self._notify_recovery(source, None)

    def reset(self) -> None:
        """Clear all tracked alert states.

        Call when the daemon disconnects so stale levels
        do not suppress notifications on reconnect.
        """
        self._prev_levels.clear()

    def _notify_warn(self, alert: dict) -> None:
        """Show a warning notification.

        Args:
            alert: Alert dict containing source, temp, and message.
        """
        source = alert.get("source", "").upper()
        temp = alert.get("temp", 0.0)
        log.info("notify warn: %s %.1f°C", source, temp)
        self._tray.showMessage(
            f"{source} WARNING",
            f"temperature: {temp:.1f}°C",
            QSystemTrayIcon.MessageIcon.Warning,
            _NOTIFY_DURATION_MS,
        )

    def _notify_critical(self, alert: dict) -> None:
        """Show a critical notification.

        Args:
            alert: Alert dict containing source, temp, and message.
        """
        source = alert.get("source", "").upper()
        temp = alert.get("temp", 0.0)
        body = (
            f"temperature: {temp:.1f}°C — fans automatically set to MAX"
            if source == "CPU"
            else f"temperature: {temp:.1f}°C — take action immediately"
        )
        log.warning("notify critical: %s %.1f°C", source, temp)
        self._tray.showMessage(
            f"{source} CRITICAL",
            body,
            QSystemTrayIcon.MessageIcon.Critical,
            _NOTIFY_DURATION_MS,
        )

    def _notify_recovery(self, source: str, alert: dict | None) -> None:
        """Show a recovery notification.

        Args:
            source: Hardware source string — "cpu" or "gpu".
            alert: Alert dict if available, or None.
        """
        source_upper = source.upper()
        if alert:
            temp = alert.get("temp", 0.0)
            body = f"temperature: {temp:.1f}°C — back to normal"
            if source == "cpu":
                body += " — fans restored to AUTO"
        else:
            body = "temperature back to normal"
        log.info("notify recovery: %s", source_upper)
        self._tray.showMessage(
            f"{source_upper} RECOVERED",
            body,
            QSystemTrayIcon.MessageIcon.Information,
            _NOTIFY_DURATION_MS,
        )
