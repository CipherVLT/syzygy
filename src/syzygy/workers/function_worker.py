"""Run a plain (Qt-free) callable on the thread pool and hand its return value back."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Signal, Slot

from syzygy.workers.base_worker import BaseWorker, WorkerSignals

logger = logging.getLogger(__name__)


class FunctionWorkerSignals(WorkerSignals):
    # (request_id, return value) – request_id lets callers discard stale results.
    result = Signal(int, object)
    # (request_id, error message)
    failed = Signal(int, str)


class FunctionWorker(BaseWorker):
    """Execute ``fn()`` off the UI thread.

    Intended for read-only queries (``repoquery``, ``flatpak list`` …) whose output is parsed by
    ``syzygy.core``. Mutations should go through ``CommandWorker`` + ``TaskDialog`` instead.

    The worker is created with ``autoDelete`` disabled: the owner keeps a Python reference until
    ``done`` is True, so the signals object can never be collected while results are in flight.
    """

    def __init__(self, fn: Callable[[], Any], *, request_id: int = 0) -> None:
        super().__init__()
        self.signals: FunctionWorkerSignals = FunctionWorkerSignals()
        self.setAutoDelete(False)
        self._fn = fn
        self.request_id = request_id
        self.done = False

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            value = self._fn()
        except Exception as exc:
            logger.exception("FunctionWorker %s failed", self.request_id)
            if not self.is_cancelled:
                self.signals.failed.emit(self.request_id, str(exc))
            self._emit_error(str(exc))
        else:
            if not self.is_cancelled:
                self.signals.result.emit(self.request_id, value)
            self._emit_finished(True, "")
        finally:
            self.done = True
