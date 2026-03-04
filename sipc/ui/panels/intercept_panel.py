"""InterceptPanel — UI panel for configuring and launching planning runs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


class InterceptPanel(QWidget):
    """Panel for intercept planning run configuration and results.

    Sections:
    - Run configuration (operator, source tag, scenario path).
    - Run controls (Plan / Cancel).
    - Results table showing candidate intercept windows.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the panel layout."""
        root = QVBoxLayout(self)

        # Configuration group
        config_group = QGroupBox("Run Configuration")
        config_form = QFormLayout(config_group)
        self._operator_edit = QLineEdit()
        self._source_edit = QLineEdit()
        self._scenario_edit = QLineEdit()
        config_form.addRow("Operator:", self._operator_edit)
        config_form.addRow("Data Source:", self._source_edit)
        config_form.addRow("Scenario Path:", self._scenario_edit)
        root.addWidget(config_group)

        # Controls
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self._plan_button = QPushButton("Run Plan")
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setEnabled(False)
        controls_layout.addWidget(self._plan_button)
        controls_layout.addWidget(self._cancel_button)
        controls_layout.addStretch()
        root.addWidget(controls)

        # Results table
        results_group = QGroupBox("Intercept Windows")
        results_layout = QVBoxLayout(results_group)
        self._results_table = QTableWidget(0, 4)
        self._results_table.setHorizontalHeaderLabels(
            ["Start (UTC)", "End (UTC)", "Duration (s)", "Min Range (km)"]
        )
        results_layout.addWidget(self._results_table)
        root.addWidget(results_group)
