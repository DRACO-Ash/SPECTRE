"""SIPC MainWindow — top-level QMainWindow shell."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QStatusBar, QTabWidget, QVBoxLayout, QWidget

from sipc.ui.panels.asset_panel import AssetPanel
from sipc.ui.panels.intercept_panel import InterceptPanel
from sipc.ui.panels.run_log_panel import RunLogPanel


class MainWindow(QMainWindow):
    """Top-level application window.

    Layout:
    - Central widget with a QTabWidget containing the three main panels.
    - Status bar showing connection state and current run ID.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SIPC — STK Intercept Planning Console")
        self.setMinimumSize(1200, 800)

        self._setup_ui()
        self._setup_status_bar()

    def _setup_ui(self) -> None:
        """Build the central widget and tab layout."""
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tabs = QTabWidget()
        self._asset_panel = AssetPanel()
        self._intercept_panel = InterceptPanel()
        self._run_log_panel = RunLogPanel()

        self._tabs.addTab(self._asset_panel, "Assets")
        self._tabs.addTab(self._intercept_panel, "Intercept Planning")
        self._tabs.addTab(self._run_log_panel, "Run Log")

        layout.addWidget(self._tabs)

    def _setup_status_bar(self) -> None:
        """Configure the status bar."""
        bar = QStatusBar()
        self.setStatusBar(bar)
        self._status_label = QLabel("STK: Disconnected  |  Run: —")
        bar.addPermanentWidget(self._status_label)

    def set_status(self, message: str) -> None:
        """Update the status bar message.

        Args:
            message: Human-readable status string.
        """
        self._status_label.setText(message)
