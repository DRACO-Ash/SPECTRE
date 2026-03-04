"""RunLogPanel — UI panel displaying the provenance log for the current run."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RunLogPanel(QWidget):
    """Panel showing the structured provenance log for the active planning run.

    Displays a scrollable plain-text view of log entries emitted during
    the run. Provides a Clear and Export button for analyst workflow support.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the panel layout."""
        root = QVBoxLayout(self)

        # Log view
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setPlaceholderText("Run log entries will appear here...")
        root.addWidget(self._log_view)

        # Controls
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addStretch()
        controls_layout.addWidget(QPushButton("Export Log"))
        controls_layout.addWidget(QPushButton("Clear"))
        root.addWidget(controls)

    def append_entry(self, text: str) -> None:
        """Append a log entry to the view.

        Args:
            text: Pre-formatted log line to append.
        """
        self._log_view.appendPlainText(text)

    def clear(self) -> None:
        """Clear all log entries from the view."""
        self._log_view.clear()
