from __future__ import annotations

import logging
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    started = Signal()
    output_line = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    error = Signal(str)


class BaseWorker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._is_cancelled = False
        self.setAutoDelete(True)

    @Slot()
    def cancel(self) -> None:
        logger.info("Cancel requested for %s", self.__class__.__name__)
        self._is_cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled

    def _emit_finished(self, success: bool, message: str = "") -> None:
        if not self.is_cancelled:
            self.signals.finished.emit(success, message)

    def _emit_error(self, message: str) -> None:
        self.signals.error.emit(message)
        self._emit_finished(False, message)
