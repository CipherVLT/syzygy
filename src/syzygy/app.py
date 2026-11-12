from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from syzygy.ui.main_window import MainWindow
from syzygy.ui.styles import apply_theme


def main() -> int:
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
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("Syzygy")
    app.setDesktopFileName("syzygy")

    apply_theme(app, dark=True)

    window = MainWindow()
    window.show()

    return app.exec()
