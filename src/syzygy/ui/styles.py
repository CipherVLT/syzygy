from __future__ import annotations

import re

from PySide6.QtWidgets import QApplication

DARK_QSS = """
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Inter", "Cantarell", "Noto Sans", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #1e1e2e;
}
QTabWidget::pane {
    border: 1px solid #313244;
    background-color: #181825;
    border-radius: 6px;
}
QTabBar::tab {
    background-color: #313244;
    color: #a6adc8;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: #45475a;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    color: #6c7086;
}
QPushButton[primary="true"] {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background-color: #b4befe;
}
QPushButton[danger="true"] {
    background-color: transparent;
    color: #f38ba8;
    border: 1px solid #f38ba8;
    font-weight: 600;
}
QPushButton[danger="true"]:hover {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled {
    background-color: #313244;
    color: #6c7086;
    border: 1px solid #45475a;
}
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 2px;
    max-height: 4px;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 2px;
}
QScrollArea, QScrollArea > QWidget > QWidget#scrollContents {
    background: transparent;
    border: none;
}
QFrame#packageCard {
    background-color: #313244;
    border: 1px solid #313244;
    border-radius: 8px;
}
QFrame#packageCard:hover {
    border: 1px solid #45475a;
}
QFrame#packageCard QLabel {
    background: transparent;
}
QLabel#pageTitle {
    font-size: 18px;
    font-weight: 700;
    color: #89b4fa;
}
QLabel#hintText, QLabel#cardMeta {
    color: #7f849c;
}
QLabel#statusText {
    color: #a6adc8;
}
QLabel#emptyState {
    color: #6c7086;
    font-size: 14px;
    padding: 48px;
}
QLabel#cardName {
    font-size: 14px;
    font-weight: 700;
    color: #cdd6f4;
}
QLabel#cardVersion {
    color: #a6adc8;
    font-family: "JetBrains Mono", monospace;
    font-size: 12px;
}
QLabel#cardSummary {
    color: #bac2de;
}
QLabel#cardMeta {
    font-size: 11px;
}
QCheckBox {
    spacing: 6px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #45475a;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border: 1px solid #89b4fa;
}
QCheckBox:disabled {
    color: #6c7086;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
}
QLineEdit, QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #89b4fa;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #89b4fa;
}
QScrollBar:vertical {
    background: #181825;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    background-color: #11111b;
    color: #a6adc8;
}
QTextEdit {
    background-color: #11111b;
    color: #cdd6f4;
    border-radius: 6px;
}
"""

# Catppuccin Mocha → Catppuccin Latte, applied in a single regex pass so that no colour is
# rewritten twice (e.g. base → text → …).
_MOCHA_TO_LATTE: dict[str, str] = {
    "#1e1e2e": "#eff1f5",  # base
    "#181825": "#e6e9ef",  # mantle
    "#11111b": "#dce0e8",  # crust
    "#313244": "#ccd0da",  # surface0
    "#45475a": "#bcc0cc",  # surface1
    "#585b70": "#acb0be",  # surface2
    "#6c7086": "#9ca0b0",  # overlay0
    "#7f849c": "#8c8fa1",  # overlay1
    "#a6adc8": "#6c6f85",  # subtext0
    "#bac2de": "#5c5f77",  # subtext1
    "#cdd6f4": "#4c4f69",  # text
    "#89b4fa": "#1e66f5",  # blue
    "#b4befe": "#7287fd",  # lavender
    "#f38ba8": "#d20f39",  # red
    "#a6e3a1": "#40a02b",  # green
}
_HEX_RE = re.compile("|".join(re.escape(k) for k in _MOCHA_TO_LATTE), re.IGNORECASE)

LIGHT_QSS = _HEX_RE.sub(lambda m: _MOCHA_TO_LATTE[m.group(0).lower()], DARK_QSS)


def apply_theme(app: QApplication, dark: bool = True) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS if dark else LIGHT_QSS)
