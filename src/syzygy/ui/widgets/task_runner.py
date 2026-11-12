"""Glue between ``CommandWorker`` and ``TaskDialog`` – the one way tabs run mutations.

Usage from any tab::

    task = CommandTask(self, "Installing htop", dnf.cmd_install_rpm("htop"), use_pkexec=True)
    task.done.connect(self._on_task_done)   # (success: bool, message: str)
    task.start()
"""

from __future__ import annotations

import logging
import shlex
from collections.abc import Sequence

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QWidget

from syzygy.ui.widgets.progress_dialog import TaskDialog
from syzygy.workers.command_worker import CommandWorker

logger = logging.getLogger(__name__)

# pkexec(1): 126 = the user dismissed the authentication dialog,
#            127 = not authorized / authentication failed.
PKEXEC_DISMISSED = 126
PKEXEC_NOT_AUTHORIZED = 127


class CommandTask(QObject):
    """Owns one ``CommandWorker`` and its ``TaskDialog`` for the lifetime of a transaction.

    The object is parented to the requesting widget, so callers don't need to keep a reference.
    It cleans itself (and the dialog) up once the user closes the finished dialog.
    """

    done = Signal(bool, str)

    def __init__(
        self,
        parent: QWidget,
        title: str,
        command: Sequence[str],
        *,
        use_pkexec: bool = False,
        timeout: int | None = 3600,
        success_message: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._command = list(command)
        self._use_pkexec = use_pkexec
        self._success_message = success_message or f"{title} – done"
        self._failure_message = failure_message or f"{title} – failed"
        self._error_text: str | None = None

        self.dialog = TaskDialog(title, parent)
        # Long transactions (kernel, gaming stack) easily exceed the worker's 600 s default.
        self.worker = CommandWorker(self._command, use_pkexec=use_pkexec, timeout=timeout)
        # We hold the Python reference until the dialog closes; never let the pool delete it.
        self.worker.setAutoDelete(False)

        signals = self.worker.signals
        signals.output_line.connect(self.dialog.append_line)
        signals.error.connect(self._on_error)
        signals.finished.connect(self._on_finished)
        self.dialog.finished.connect(self._on_dialog_closed)

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        shown = ["pkexec", *self._command] if self._use_pkexec else self._command
        self.dialog.append_line("$ " + " ".join(shlex.quote(part) for part in shown))
        self.dialog.set_running(
            "Waiting for authentication…" if self._use_pkexec else "Running…"
        )
        self.dialog.open()  # window-modal but non-blocking: the event loop keeps streaming
        logger.info("Starting task: %s", self._title)
        QThreadPool.globalInstance().start(self.worker)

    # ------------------------------------------------------------------ slots
    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._error_text = message
        self.dialog.append_line(f"[error] {message}")

    @Slot(bool, str)
    def _on_finished(self, success: bool, message: str) -> None:
        code = self.worker.returncode
        if success:
            self.dialog.set_success(self._success_message)
        elif self._use_pkexec and code == PKEXEC_DISMISSED:
            message = "Authentication cancelled – nothing was changed"
            self.dialog.set_failure(self._failure_message, message)
        elif self._use_pkexec and code == PKEXEC_NOT_AUTHORIZED:
            message = "Not authorized – administrator authentication failed"
            self.dialog.set_failure(self._failure_message, message)
        else:
            message = self._error_text or message
            self.dialog.set_failure(self._failure_message, message)
        logger.info("Task finished (%s): %s – %s", success, self._title, message)
        self.done.emit(success, message)

    @Slot(int)
    def _on_dialog_closed(self, _result: int) -> None:
        # By the time the user can close the dialog the worker's run() has returned.
        self.dialog.deleteLater()
        self.deleteLater()
