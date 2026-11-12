from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from syzygy.ui import theme


class TaskDialog(QDialog):
    """Live output for a long-running command: glass panel + embedded terminal."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(780, 520)
        self.setMinimumSize(560, 360)
        self._running = True
        if theme.is_translucent():
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        root = QFrame()
        root.setObjectName("dialogRoot")
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        self.header = QLabel(title)
        self.header.setObjectName("dialogTitle")
        layout.addWidget(self.header)

        self.status_lbl = QLabel("Running…")
        self.status_lbl.setObjectName("dialogStatus")
        layout.addWidget(self.status_lbl)

        terminal = QFrame()
        terminal.setObjectName("terminal")
        term_layout = QVBoxLayout(terminal)
        term_layout.setContentsMargins(0, 0, 0, 0)
        term_layout.setSpacing(0)
        self.terminal_title = QLabel("●  output")
        self.terminal_title.setObjectName("terminalTitle")
        term_layout.addWidget(self.terminal_title)
        self.output = QTextEdit()
        self.output.setObjectName("terminalOutput")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        mono = QFont("JetBrains Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.output.setFont(mono)
        term_layout.addWidget(self.output, stretch=1)
        layout.addWidget(terminal, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton("Copy output")
        self.btn_copy.clicked.connect(self._copy_output)
        btn_row.addWidget(self.btn_copy)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setProperty("primary", True)
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self._set_state("running")

    # ------------------------------------------------------------------ output
    @Slot(str)
    def append_line(self, line: str) -> None:
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(line + "\n")
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    @Slot()
    def _copy_output(self) -> None:
        QApplication.clipboard().setText(self.output.toPlainText())

    # ------------------------------------------------------------------ state
    def _set_state(self, state: str) -> None:
        for label in (self.header, self.status_lbl):
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)
        dots = {"running": "●  running", "success": "●  finished", "failure": "●  failed"}
        self.terminal_title.setText(dots.get(state, "●  output"))

    @property
    def is_running(self) -> bool:
        return self._running

    def reject(self) -> None:
        # Esc must not hide a dialog whose transaction is still streaming output.
        if not self._running:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 – Qt override
        if self._running:
            event.ignore()
        else:
            super().closeEvent(event)

    def set_status(self, message: str) -> None:
        self.status_lbl.setText(message)

    def set_running(self, message: str = "Running…") -> None:
        self._running = True
        self.status_lbl.setText(message)
        self.btn_close.setEnabled(False)
        self._set_state("running")

    def set_success(self, message: str = "Task Completed Successfully") -> None:
        self._running = False
        self.header.setText(message)
        self.status_lbl.setText("Finished successfully")
        self.btn_close.setEnabled(True)
        self._set_state("success")

    def set_failure(
        self, message: str = "Task Failed", detail: str = "Finished with errors"
    ) -> None:
        self._running = False
        self.header.setText(message)
        self.status_lbl.setText(detail)
        self.btn_close.setEnabled(True)
        self._set_state("failure")
