"""SIPC application entry point — QApplication setup and main() function."""

from __future__ import annotations

import sys


def main() -> None:
    """Launch the SIPC Qt application.

    This function is the console_scripts entry point defined in pyproject.toml.
    It creates the QApplication, shows the main window, and runs the event loop.
    """
    from PySide6.QtWidgets import QApplication

    from sipc.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SIPC")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("SIPC")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
