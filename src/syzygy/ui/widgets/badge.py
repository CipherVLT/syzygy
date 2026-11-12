"""Small pill-shaped status labels (source, Installed, Running, Default, Active …)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

# Catppuccin Mocha accents
BLUE = "#89b4fa"
GREEN = "#a6e3a1"
PEACH = "#fab387"
MAUVE = "#cba6f7"
RED = "#f38ba8"
YELLOW = "#f9e2af"
TEAL = "#94e2d5"
SURFACE1 = "#45475a"
BASE = "#1e1e2e"
TEXT = "#cdd6f4"


class Badge(QLabel):
    def __init__(
        self,
        text: str,
        color: str = BLUE,
        *,
        foreground: str = BASE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_colors(color, foreground)

    def set_colors(self, color: str, foreground: str = BASE) -> None:
        self.setStyleSheet(
            f"background-color: {color}; color: {foreground}; border-radius: 8px;"
            " padding: 1px 8px; font-size: 11px; font-weight: 600;"
        )

    def update_badge(self, text: str, color: str, foreground: str = BASE) -> None:
        self.setText(text)
        self.set_colors(color, foreground)
