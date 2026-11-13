from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from syzygy.ui import theme
from syzygy.ui.main_window import MainWindow

# Benign Qt warnings on Fedora/Wayland:
#  * qt.qpa.services – portal can't map app-id "syzygy" until syzygy.desktop is installed
#    (./build.sh --desktop installs it);
#  * qt.qpa.wayland.textinput – text-input-v3 focus bookkeeping spam on every focus change.
_QUIET_QT_CATEGORIES = (
    "qt.qpa.services=false",
    "qt.qpa.wayland.textinput=false",
    "qt.qpa.wayland.textinput.debug=false",
)


def _silence_benign_qt_warnings() -> None:
    existing = os.environ.get("QT_LOGGING_RULES", "")
    rules = [r for r in existing.split(";") if r.strip()]
    # User-supplied rules come last so they win (later rules override earlier ones).
    os.environ["QT_LOGGING_RULES"] = ";".join([*_QUIET_QT_CATEGORIES, *rules])


def main() -> int:
    _silence_benign_qt_warnings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Syzygy")
    app.setApplicationVersion("0.3.6")
    app.setOrganizationName("Syzygy")
    app.setDesktopFileName("syzygy")

    # Translucency must be decided before the first window is created.
    theme.set_translucent(theme.translucency_requested())
    theme.apply_theme(app)  # last used theme, Glass by default

    window = MainWindow()
    window.show()

    return app.exec()
