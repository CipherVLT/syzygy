"""Shared scaffolding for system tabs: header, background queries, privileged tasks, busy state.

Every tab built on ``BasePage`` gets the same behaviour for free:

* lazy loading – ``refresh()`` runs the first time the tab is shown, not at startup;
* ``run_query()`` – run a Qt-free ``syzygy.core`` function on the thread pool, drop stale results;
* ``run_task()`` – optional confirmation → ``CommandTask`` (CommandWorker + TaskDialog) →
  success/failure status → ``system_changed`` broadcast → automatic refresh;
* one transaction at a time – every widget passed to ``track()`` is disabled while it runs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

import shiboken6
from PySide6.QtCore import Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from syzygy.ui.widgets.task_runner import CommandTask
from syzygy.workers.function_worker import FunctionWorker

logger = logging.getLogger(__name__)

# Scopes broadcast through ``system_changed`` so other tabs know to reload.
SCOPE_PACKAGES = "packages"
SCOPE_FLATPAK = "flatpak"
SCOPE_REPOS = "repos"
SCOPE_KERNELS = "kernels"
SCOPE_FIRMWARE = "firmware"

_LOCK_PROPERTY = "syzygyLocked"


class BasePage(QWidget):
    status_message = Signal(str, int)  # → main window status bar
    system_changed = Signal(str)  # scope; emitted after a successful transaction

    #: Scopes that make this page stale when another page changes them.
    WATCH_SCOPES: frozenset[str] = frozenset()

    def __init__(
        self,
        title: str,
        hint: str = "",
        parent: QWidget | None = None,
        *,
        refresh_label: str | None = "Refresh",
    ) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._workers: list[FunctionWorker] = []
        self._next_request = 0
        self._latest: dict[str, int] = {}
        self._queries: dict[int, tuple[str, Callable[[Any], None], Callable[[str], None] | None]] = {}
        self._tracked: list[QWidget] = []
        self._busy = False
        self._loaded_once = False
        self._stale = False

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 16, 16, 12)
        self.root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("pageTitle")
        header.addWidget(title_lbl)
        if hint:
            hint_lbl = QLabel(hint)
            hint_lbl.setObjectName("hintText")
            header.addWidget(hint_lbl)
        header.addStretch()
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(8)
        header.addLayout(self.header_actions)
        self.refresh_btn: QPushButton | None = None
        if refresh_label:
            self.refresh_btn = self.add_header_button(refresh_label, self.refresh)
        self.root.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        self.root.addWidget(self.progress)

        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("statusText")
        self.status_lbl.setWordWrap(True)
        self.root.addWidget(self.status_lbl)

    # ================================================================== building helpers
    def add_header_button(
        self,
        text: str,
        slot: Callable[[], None],
        *,
        primary: bool = False,
        tooltip: str = "",
    ) -> QPushButton:
        btn = QPushButton(text)
        if primary:
            btn.setProperty("primary", True)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.clicked.connect(lambda _checked=False: slot())
        self.header_actions.addWidget(btn)
        self.track(btn)
        return btn

    def make_scroll_column(self) -> tuple[QScrollArea, QVBoxLayout]:
        """A transparent scroll area whose inner column layout ends with a stretch."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contents = QWidget()
        contents.setObjectName("scrollContents")
        column = QVBoxLayout(contents)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(10)
        scroll.setWidget(contents)
        return scroll, column

    # ================================================================== status
    def set_status(self, text: str, *, level: str = "info") -> None:
        name = {"info": "statusText", "warning": "warningText", "error": "errorText"}[level]
        if self.status_lbl.objectName() != name:
            self.status_lbl.setObjectName(name)
            self.status_lbl.style().unpolish(self.status_lbl)
            self.status_lbl.style().polish(self.status_lbl)
        self.status_lbl.setText(text)

    # ================================================================== lazy loading
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 – Qt override
        super().showEvent(event)
        if not self._loaded_once or self._stale:
            self._loaded_once = True
            self._stale = False
            self.refresh()

    @Slot()
    def refresh(self) -> None:
        """Reload the page's data. Subclasses call ``run_query`` here."""

    def mark_stale(self) -> None:
        """Another tab changed the system: reload now if visible, else on next show."""
        if not self._loaded_once:
            return
        if self.isVisible() and not self._busy:
            self.refresh()
        else:
            self._stale = True

    # ================================================================== background queries
    def run_query(
        self,
        key: str,
        fn: Callable[[], Any],
        on_result: Callable[[Any], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        """Run ``fn`` off the UI thread; only the newest request per ``key`` is delivered."""
        self._next_request += 1
        request_id = self._next_request
        self._latest[key] = request_id
        self._queries[request_id] = (key, on_result, on_error)

        self._workers = [w for w in self._workers if not w.done]
        worker = FunctionWorker(fn, request_id=request_id)
        worker.signals.result.connect(self._on_query_result)
        worker.signals.failed.connect(self._on_query_failed)
        self._workers.append(worker)
        self._update_progress()
        self._pool.start(worker)

    def _take_query(
        self, request_id: int
    ) -> tuple[Callable[[Any], None], Callable[[str], None] | None] | None:
        entry = self._queries.pop(request_id, None)
        self._update_progress()
        if entry is None:
            return None
        key, on_result, on_error = entry
        if self._latest.get(key) != request_id:
            return None  # superseded by a newer request for the same key
        return on_result, on_error

    @Slot(int, object)
    def _on_query_result(self, request_id: int, value: object) -> None:
        callbacks = self._take_query(request_id)
        if callbacks is not None:
            callbacks[0](value)

    @Slot(int, str)
    def _on_query_failed(self, request_id: int, message: str) -> None:
        callbacks = self._take_query(request_id)
        if callbacks is None:
            return
        if callbacks[1] is not None:
            callbacks[1](message)
        else:
            self.set_status(f"Error: {message}", level="error")
            self.status_message.emit(message, 8000)

    def _update_progress(self) -> None:
        self.progress.setVisible(bool(self._queries))

    # ================================================================== busy state
    @property
    def busy(self) -> bool:
        return self._busy

    def track(self, *widgets: QWidget) -> None:
        """Disable these widgets while a transaction runs (dead widgets are pruned)."""
        self._tracked = [w for w in self._tracked if shiboken6.isValid(w)]
        for widget in widgets:
            self._tracked.append(widget)
            if self._busy:
                widget.setEnabled(False)

    @staticmethod
    def lock(widget: QWidget, reason: str) -> None:
        """Keep a widget disabled permanently (it won't be re-enabled after a transaction)."""
        widget.setProperty(_LOCK_PROPERTY, True)
        widget.setEnabled(False)
        widget.setToolTip(reason)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        alive: list[QWidget] = []
        for widget in self._tracked:
            if not shiboken6.isValid(widget):
                continue
            alive.append(widget)
            widget.setEnabled(not busy and not widget.property(_LOCK_PROPERTY))
        self._tracked = alive
        self.on_busy_changed(busy)

    def on_busy_changed(self, busy: bool) -> None:
        """Hook for subclasses with extra state (e.g. checkable table rows)."""

    # ================================================================== privileged tasks
    def confirm(self, title: str, html: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            html,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def run_task(
        self,
        title: str,
        command: Sequence[str],
        *,
        use_pkexec: bool,
        success_message: str | None = None,
        failure_message: str | None = None,
        confirm: str | None = None,
        scope: str | None = None,
        on_done: Callable[[bool], None] | None = None,
        refresh_after: bool = True,
        timeout: int | None = 3600,
    ) -> bool:
        """Start a streaming command in ``TaskDialog``. Returns False if not started."""
        if self._busy:
            self.status_message.emit("Another task is still running", 4000)
            return False
        if confirm and not self.confirm(title, confirm):
            return False

        task = CommandTask(
            self,
            title,
            command,
            use_pkexec=use_pkexec,
            timeout=timeout,
            success_message=success_message,
            failure_message=failure_message,
        )

        def finished(success: bool, message: str) -> None:
            self._set_busy(False)
            self.status_message.emit(success_message or title if success else message, 6000)
            if success and scope:
                self.system_changed.emit(scope)
            if on_done is not None:
                on_done(success)
            if refresh_after and success and not self._busy:
                self.refresh()

        task.done.connect(finished)
        self._set_busy(True)
        self.status_message.emit(f"{title}…", 0)
        task.start()
        return True


# ====================================================================== tables
class SortItem(QTableWidgetItem):
    """Table item that sorts by an explicit key (e.g. bytes) instead of its display text."""

    def __init__(self, text: str, sort_key: Any = None) -> None:
        super().__init__(text)
        self._sort_key = sort_key if sort_key is not None else text.lower()
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortItem):
            try:
                return bool(self._sort_key < other._sort_key)
            except TypeError:
                return str(self._sort_key) < str(other._sort_key)
        return super().__lt__(other)


def make_table(headers: Sequence[str], *, stretch_column: int = 1) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    header.setHighlightSections(False)
    return table


def check_item(checked: bool = False, *, enabled: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem()
    flags = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
    if enabled:
        flags |= Qt.ItemFlag.ItemIsEnabled
    item.setFlags(flags)
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    return item
