"""Syzygy theme engine: one tokenized QSS template rendered with Glass / Mocha / Latte palettes.

*Glass* is a translucent dark theme. Qt paints the window with semi-transparent colours; the
frosted **blur** itself comes from the Wayland compositor (Hyprland, KWin, mangowc … with blur
enabled for app-id ``syzygy``). Without compositor blur it renders as tinted glass.

Translucency needs ``WA_TranslucentBackground`` before the window is first shown, so it is
decided once at startup (``SYZYGY_GLASS=0`` disables it). Switching to an opaque theme at
runtime always works because the root frame then paints an opaque background.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace
from string import Template

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

THEME_GLASS = "glass"
THEME_MOCHA = "mocha"
THEME_LATTE = "latte"
THEME_ORDER = (THEME_GLASS, THEME_MOCHA, THEME_LATTE)
THEME_LABELS = {THEME_GLASS: "Glass", THEME_MOCHA: "Mocha", THEME_LATTE: "Latte"}


@dataclass(frozen=True)
class Palette:
    window_bg: str
    root_border: str
    root_radius: str
    surface: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    subtext: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    accent_border: str
    danger: str
    danger_soft: str
    success: str
    warning: str
    input_bg: str
    table_bg: str
    table_alt: str
    selection: str
    terminal_bg: str
    terminal_text: str
    popup_bg: str
    pill_bg: str
    pill_hover: str
    sidebar_bg: str
    row_alt: str
    scroll_handle: str
    tooltip_bg: str
    glow: str  # hover glow colour (QGraphicsDropShadowEffect), "" disables
    dark: bool = True


GLASS = Palette(
    window_bg="rgba(17, 17, 27, 0.80)",
    root_border="rgba(255, 255, 255, 0.10)",
    root_radius="14px",
    surface="rgba(255, 255, 255, 0.045)",
    surface_hover="rgba(255, 255, 255, 0.085)",
    border="rgba(255, 255, 255, 0.08)",
    border_strong="rgba(255, 255, 255, 0.18)",
    text="#e4e8f7",
    subtext="#a6adc8",
    muted="#7f849c",
    accent="#89b4fa",
    accent_hover="#b4befe",
    accent_text="#11111b",
    accent_soft="rgba(137, 180, 250, 0.16)",
    accent_border="rgba(137, 180, 250, 0.55)",
    danger="#f38ba8",
    danger_soft="rgba(243, 139, 168, 0.16)",
    success="#a6e3a1",
    warning="#f9e2af",
    input_bg="rgba(0, 0, 0, 0.28)",
    table_bg="rgba(0, 0, 0, 0.22)",
    table_alt="rgba(255, 255, 255, 0.025)",
    selection="rgba(137, 180, 250, 0.24)",
    terminal_bg="rgba(8, 8, 14, 0.78)",
    terminal_text="#cdd6f4",
    popup_bg="#181825",
    pill_bg="rgba(255, 255, 255, 0.05)",
    pill_hover="rgba(255, 255, 255, 0.10)",
    sidebar_bg="rgba(0, 0, 0, 0.20)",
    row_alt="rgba(0, 0, 0, 0.28)",
    scroll_handle="rgba(255, 255, 255, 0.16)",
    tooltip_bg="#232336",
    glow="#89b4fa",
)

MOCHA = replace(
    GLASS,
    window_bg="#1e1e2e",
    root_border="#1e1e2e",
    root_radius="0px",
    surface="#26263a",
    surface_hover="#313244",
    border="#313244",
    border_strong="#45475a",
    input_bg="#181825",
    table_bg="#181825",
    table_alt="#1e1e2e",
    terminal_bg="#11111b",
    pill_bg="#26263a",
    pill_hover="#313244",
    sidebar_bg="#181825",
    row_alt="#11111b",
    scroll_handle="#45475a",
)

LATTE = Palette(
    window_bg="#eff1f5",
    root_border="#eff1f5",
    root_radius="0px",
    surface="#ffffff",
    surface_hover="#e6e9ef",
    border="#ccd0da",
    border_strong="#acb0be",
    text="#4c4f69",
    subtext="#5c5f77",
    muted="#8c8fa1",
    accent="#1e66f5",
    accent_hover="#7287fd",
    accent_text="#ffffff",
    accent_soft="rgba(30, 102, 245, 0.12)",
    accent_border="rgba(30, 102, 245, 0.55)",
    danger="#d20f39",
    danger_soft="rgba(210, 15, 57, 0.10)",
    success="#40a02b",
    warning="#df8e1d",
    input_bg="#ffffff",
    table_bg="#ffffff",
    table_alt="#f5f6f9",
    selection="rgba(30, 102, 245, 0.18)",
    terminal_bg="#1e1e2e",
    terminal_text="#cdd6f4",
    popup_bg="#eff1f5",
    pill_bg="#ffffff",
    pill_hover="#e6e9ef",
    sidebar_bg="#e6e9ef",
    row_alt="#e6e9ef",
    scroll_handle="#bcc0cc",
    tooltip_bg="#ffffff",
    glow="#1e66f5",
    dark=False,
)

PALETTES = {THEME_GLASS: GLASS, THEME_MOCHA: MOCHA, THEME_LATTE: LATTE}

_QSS = Template("""
* { outline: none; }
QWidget {
    background: transparent;
    color: $text;
    font-family: "Inter", "Cantarell", "Noto Sans", sans-serif;
    font-size: 13px;
}
QMainWindow { background: transparent; }
QDialog, QMessageBox, QFileDialog, QInputDialog { background-color: $popup_bg; }
QDialog#taskDialog { background: transparent; }

/* ---------- window chrome ------------------------------------------------------------ */
QFrame#glassRoot, QFrame#dialogRoot {
    background-color: $window_bg;
    border: 1px solid $root_border;
    border-radius: $root_radius;
}
QLabel#appTitle { color: $accent; font-size: 15px; font-weight: 700; letter-spacing: 0.5px; }
QLabel#appSubtitle { color: $muted; font-size: 12px; }

QPushButton#navPill {
    background-color: $pill_bg;
    color: $subtext;
    border: 1px solid $border;
    border-radius: 16px;
    padding: 6px 15px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton#navPill:hover { background-color: $pill_hover; color: $text; border-color: $border_strong; }
QPushButton#navPill:checked {
    background-color: $accent;
    color: $accent_text;
    border: 1px solid $accent;
}
QPushButton#utilityPill {
    background-color: $pill_bg;
    color: $subtext;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 4px 12px;
    min-height: 20px;
}
QPushButton#utilityPill:hover { color: $text; background-color: $pill_hover; }

/* ---------- typography ----------------------------------------------------------------- */
QLabel#pageTitle { font-size: 20px; font-weight: 700; color: $text; }
QLabel#sectionTitle { font-size: 15px; font-weight: 700; color: $accent; padding-top: 6px; }
QLabel#hintText, QLabel#cardMeta { color: $muted; }
QLabel#statusText { color: $subtext; }
QLabel#warningText { color: $warning; }
QLabel#errorText { color: $danger; }
QLabel#emptyState { color: $muted; font-size: 14px; padding: 48px; }
QLabel#cardName { font-size: 14px; font-weight: 700; color: $text; }
QLabel#cardTitleLink { font-size: 14px; font-weight: 600; color: $accent; }
QLabel#cardVersion { color: $subtext; font-family: "JetBrains Mono", monospace; font-size: 12px; }
QLabel#cardSummary { color: $subtext; }
QLabel#cardMeta { font-size: 11px; }
QLabel#detailTitle { color: $accent; font-size: 13px; font-weight: 600; }

/* ---------- buttons (pill shaped) ------------------------------------------------------ */
QPushButton {
    background-color: $surface;
    color: $text;
    border: 1px solid $border;
    border-radius: 15px;
    padding: 6px 16px;
    min-height: 18px;
}
QPushButton:hover { background-color: $surface_hover; border-color: $border_strong; }
QPushButton:pressed { background-color: $pill_hover; }
QPushButton:disabled { color: $muted; background-color: $pill_bg; border-color: $border; }
QPushButton[primary="true"] {
    background-color: $accent;
    color: $accent_text;
    border: 1px solid $accent;
    font-weight: 600;
}
QPushButton[primary="true"]:hover { background-color: $accent_hover; border-color: $accent_hover; }
QPushButton[danger="true"] {
    background-color: transparent;
    color: $danger;
    border: 1px solid $danger;
    font-weight: 600;
}
QPushButton[danger="true"]:hover { background-color: $danger_soft; }
QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled {
    background-color: $pill_bg;
    color: $muted;
    border: 1px solid $border;
}

/* ---------- inputs --------------------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox {
    background-color: $input_bg;
    border: 1px solid $border;
    border-radius: 12px;
    padding: 6px 12px;
    selection-background-color: $accent;
    selection-color: $accent_text;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid $accent_border; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: $popup_bg;
    border: 1px solid $border_strong;
    border-radius: 8px;
    selection-background-color: $selection;
    selection-color: $text;
    padding: 4px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator, QTableWidget::indicator, QListView::indicator {
    width: 16px; height: 16px;
    border-radius: 5px;
    border: 1px solid $border_strong;
    background-color: $input_bg;
}
QCheckBox::indicator:checked, QTableWidget::indicator:checked {
    background-color: $accent;
    border: 1px solid $accent;
}
QCheckBox:disabled { color: $muted; }

/* ---------- cards ---------------------------------------------------------------------- */
QFrame#packageCard, QFrame#card, QFrame#propertyCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#packageCard:hover, QFrame#card:hover {
    background-color: $surface_hover;
    border: 1px solid $accent_border;
}
QFrame#card[accent="blue"] { border-left: 3px solid $accent; }
QFrame#card[accent="green"] { border-left: 3px solid $success; }
QFrame#card[accent="yellow"] { border-left: 3px solid $warning; }
QFrame#card[accent="red"] { border-left: 3px solid $danger; }
QFrame#card QLineEdit, QFrame#card QComboBox { background-color: $input_bg; }

QFrame#propRow { border-radius: 8px; background: transparent; }
QFrame#propRow[alt="true"] { background-color: $row_alt; }
QLabel#propKey { color: $subtext; font-size: 12px; min-width: 140px; }
QLabel#propValue { color: $text; font-size: 12px; }
QLabel#propValue[accent="true"] { color: $accent; }

/* ---------- sidebar -------------------------------------------------------------------- */
QListWidget#sidebar {
    background-color: $sidebar_bg;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 8px 6px;
}
QListWidget#sidebar::item {
    background-color: $pill_bg;
    border: 1px solid $border;
    border-radius: 14px;
    color: $text;
    padding: 6px 12px;
    margin: 2px 2px;
}
QListWidget#sidebar::item:hover { background-color: $pill_hover; border-color: $border_strong; }
QListWidget#sidebar::item:selected {
    background-color: $accent;
    color: $accent_text;
    border: 1px solid $accent;
}
QListWidget#sidebar::item:disabled {
    background: transparent;
    border: none;
    color: $subtext;
    padding: 12px 6px 2px 6px;
    font-weight: 600;
}

/* ---------- segmented sub-tabs --------------------------------------------------------- */
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab {
    background-color: $pill_bg;
    color: $subtext;
    border: 1px solid $border;
    border-radius: 14px;
    padding: 6px 16px;
    margin-right: 6px;
    margin-bottom: 8px;
}
QTabBar::tab:hover:!selected { background-color: $pill_hover; color: $text; }
QTabBar::tab:selected { background-color: $accent_soft; color: $accent; border-color: $accent_border; }

/* ---------- tables & lists ------------------------------------------------------------- */
QTableWidget, QAbstractItemView {
    background-color: $table_bg;
    alternate-background-color: $table_alt;
    border: 1px solid $border;
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: $selection;
    selection-color: $text;
}
QTableWidget::item { padding: 5px 8px; border: none; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background-color: $surface;
    color: $subtext;
    border: none;
    border-bottom: 1px solid $border;
    padding: 8px 10px;
    font-weight: 600;
}
QTableCornerButton::section { background: transparent; border: none; }

/* ---------- terminal / text ------------------------------------------------------------ */
QPlainTextEdit, QTextEdit {
    background-color: $terminal_bg;
    color: $terminal_text;
    border: 1px solid $border;
    border-radius: 12px;
    padding: 6px;
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 12px;
    selection-background-color: $selection;
}
QFrame#terminal {
    background-color: $terminal_bg;
    border: 1px solid $border;
    border-radius: 12px;
}
QLabel#terminalTitle {
    color: $muted;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px;
    padding: 8px 14px 6px 14px;
    border-bottom: 1px solid $border;
}
QTextEdit#terminalOutput {
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 8px 14px;
}
QLabel#dialogTitle { font-size: 17px; font-weight: 700; color: $accent; }
QLabel#dialogTitle[state="success"] { color: $success; }
QLabel#dialogTitle[state="failure"] { color: $danger; }
QLabel#dialogStatus { color: $subtext; }
QLabel#dialogStatus[state="running"] { color: $accent; }
QLabel#dialogStatus[state="success"] { color: $success; }
QLabel#dialogStatus[state="failure"] { color: $danger; }

/* ---------- misc ----------------------------------------------------------------------- */
QProgressBar { background-color: $pill_bg; border: none; border-radius: 2px; max-height: 3px; }
QProgressBar::chunk { background-color: $accent; border-radius: 2px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 4px; min-height: 32px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll_handle; border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QStatusBar { background: transparent; color: $muted; border-top: 1px solid $border; }
QStatusBar::item { border: none; }
QToolTip {
    background-color: $tooltip_bg;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 6px;
    padding: 5px 8px;
}
QMenu { background-color: $popup_bg; border: 1px solid $border_strong; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background-color: $selection; }
""")


# ---------------------------------------------------------------------- state
_current = THEME_GLASS
_translucent = False


def render_qss(name: str) -> str:
    palette = PALETTES[name]
    return _QSS.substitute({k: v for k, v in palette.__dict__.items() if isinstance(v, str)})


def translucency_requested() -> bool:
    """True unless SYZYGY_GLASS=0 – decided once, before the main window is created."""
    return os.environ.get("SYZYGY_GLASS", "1").strip().lower() not in ("0", "false", "no", "off")


def set_translucent(enabled: bool) -> None:
    global _translucent
    _translucent = enabled


def is_translucent() -> bool:
    return _translucent


def current_theme() -> str:
    return _current


def current_palette() -> Palette:
    return PALETTES[_current]


def saved_theme() -> str:
    value = QSettings("Syzygy", "Syzygy").value("theme", THEME_GLASS)
    return value if value in PALETTES else THEME_GLASS


def next_theme(name: str) -> str:
    return THEME_ORDER[(THEME_ORDER.index(name) + 1) % len(THEME_ORDER)]


def apply_theme(app: QApplication, name: str | None = None, *, save: bool = True) -> str:
    global _current
    name = name if name in PALETTES else saved_theme()
    _current = name
    palette = PALETTES[name]
    app.setStyle("Fusion")
    # Base palette for anything QSS doesn't reach (native dialog bits, disabled text, …).
    qpal = QPalette()
    window = QColor("#11111b" if palette.dark else "#eff1f5")
    qpal.setColor(QPalette.ColorRole.Window, window)
    qpal.setColor(QPalette.ColorRole.Base, QColor(palette.popup_bg))
    qpal.setColor(QPalette.ColorRole.Text, QColor(palette.text))
    qpal.setColor(QPalette.ColorRole.WindowText, QColor(palette.text))
    qpal.setColor(QPalette.ColorRole.ButtonText, QColor(palette.text))
    qpal.setColor(QPalette.ColorRole.Highlight, QColor(palette.accent))
    qpal.setColor(QPalette.ColorRole.HighlightedText, QColor(palette.accent_text))
    app.setPalette(qpal)
    app.setStyleSheet(render_qss(name))
    if save:
        QSettings("Syzygy", "Syzygy").setValue("theme", name)
    logger.info("Theme: %s (translucent window: %s)", name, _translucent)
    return name
