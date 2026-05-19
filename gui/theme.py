"""
gui/theme.py
------------
Loads and applies the QSS stylesheet to the application.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def apply_theme(app, name: str = "dark") -> None:
    """Load and apply a QSS stylesheet to the Qt application.

    Args:
        app: The QApplication instance to style.
        name: Stylesheet name without extension. Looks for
            gui/styles/{name}.qss relative to this file.
    """
    path = Path(__file__).parent / "styles" / f"{name}.qss"
    try:
        app.setStyleSheet(path.read_text())
        log.info("theme loaded: %s", path)
    except OSError as e:
        log.warning("could not load theme %s: %s", path, e)


def reload_theme(app, name: str = "dark") -> None:
    """Reload the stylesheet at runtime without restarting.

    Args:
        app: The QApplication instance to restyle.
        name: Stylesheet name without extension.
    """
    log.info("reloading theme: %s", name)
    apply_theme(app, name)
