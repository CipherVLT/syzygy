from __future__ import annotations

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

def apply_theme(app: QApplication, dark: bool = True) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
