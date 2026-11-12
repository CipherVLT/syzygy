"""Backward-compatible wrapper – the theme engine lives in ``syzygy.ui.theme``."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from syzygy.ui import theme


def apply_theme(app: QApplication, dark: bool = True) -> None:
    theme.apply_theme(app, theme.THEME_GLASS if dark else theme.THEME_LATTE)
