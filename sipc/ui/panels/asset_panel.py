"""AssetPanel — UI panel for managing blue and red assets."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AssetPanel(QWidget):
    """Panel for viewing and editing blue/red asset sets.

    Provides two list views (blue assets, red tracks) and placeholder
    buttons for adding, editing, and removing entries.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the panel layout."""
        root = QHBoxLayout(self)

        # Blue assets group
        blue_group = QGroupBox("Blue Assets")
        blue_layout = QVBoxLayout(blue_group)
        self._blue_list = QListWidget()
        blue_layout.addWidget(self._blue_list)
        blue_layout.addWidget(self._make_crud_buttons("blue"))
        root.addWidget(blue_group)

        # Red tracks group
        red_group = QGroupBox("Red Tracks")
        red_layout = QVBoxLayout(red_group)
        self._red_list = QListWidget()
        red_layout.addWidget(self._red_list)
        red_layout.addWidget(self._make_crud_buttons("red"))
        root.addWidget(red_group)

    def _make_crud_buttons(self, side: str) -> QWidget:
        """Create Add / Edit / Remove button row for a given side.

        Args:
            side: ``"blue"`` or ``"red"`` — used for object-naming only.

        Returns:
            A QWidget containing the button row.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QPushButton("Add"))
        layout.addWidget(QPushButton("Edit"))
        layout.addWidget(QPushButton("Remove"))
        return container
