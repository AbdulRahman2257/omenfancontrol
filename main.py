"""
main.py
-------
Entry point for the OMEN dashboard GUI.

Run:
    python main.py

Requires the daemon to be running:
    sudo python -m daemon.daemon
"""

import sys
import logging

from PyQt6.QtWidgets import QApplication

from gui.theme import apply_theme
from gui.main_window import MainWindow


def main():
    """Start the OMEN dashboard application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("OMEN Dashboard")

    apply_theme(app)

    win = MainWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
