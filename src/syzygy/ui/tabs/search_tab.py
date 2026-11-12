"""Search tab – debounced RPM (dnf repoquery) + Flatpak search with Install / Remove actions."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from syzygy.core import dnf
from syzygy.core.models import Package, PackageSource, PackageStatus
from syzygy.ui.widgets.package_card import (
    ACTION_INSTALL,
    ACTION_REMOVE,
    PackageCard,
    package_key,
)
from syzygy.ui.widgets.task_runner import CommandTask
from syzygy.workers.function_worker import FunctionWorker

logger = logging.getLogger(__name__)

SOURCE_RPM = "rpm"
SOURCE_FLATPAK = "flatpak"

# (combo label, sources searched)
_SOURCE_CHOICES: list[tuple[str, tuple[str, ...]]] = [
    ("All sources", (SOURCE_RPM, SOURCE_FLATPAK)),
    ("RPM (DNF / COPR)", (SOURCE_RPM,)),
    ("Flatpak", (SOURCE_FLATPAK,)),
]

FILTER_ANY = 0
FILTER_INSTALLED = 1
FILTER_AVAILABLE = 2

# (source, packages, error message or None)
SearchPayload = tuple[str, list[Package], str | None]


def _search_job(source: str, query: str) -> Callable[[], SearchPayload]:
    fn = dnf.search_rpm if source == SOURCE_RPM else dnf.search_flatpak

    def job() -> SearchPayload:
        try:
            return source, fn(query), None
        except Exception as exc:
            logger.exception("%s search failed", source)
            return source, [], str(exc)

    return job


class SearchTab(QWidget):
    """Search Fedora repos, enabled COPRs and Flatpak remotes in parallel."""

    status_message = Signal(str, int)  # (text, timeout ms) → main window status bar
    packages_changed = Signal()  # emitted after a successful install/remove

    DEBOUNCE_MS = 400
    MIN_QUERY_LEN = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._request_id = 0
        self._query = ""
        self._sources: tuple[str, ...] = ()
        self._pending: set[str] = set()
        self._results: dict[str, list[Package]] = {}
        self._errors: dict[str, str] = {}
        self._workers: list[FunctionWorker] = []
        self._cards: dict[str, PackageCard] = {}
        self._busy_key: str | None = None
        self._busy_text: str | None = None

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self.DEBOUNCE_MS)
        self._debounce.timeout.connect(self._search_now)

        self._build_ui()
        self._show_idle()

    # ================================================================== UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Search Packages")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        hint = QLabel("Fedora repos · COPR · Flatpak remotes")
        hint.setObjectName("hintText")
        header.addWidget(hint)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search packages and apps…  (Enter to search now)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_text_changed)
        self.search_edit.returnPressed.connect(self._search_now)
        controls.addWidget(self.search_edit, stretch=1)

        self.source_combo = QComboBox()
        for label, _sources in _SOURCE_CHOICES:
            self.source_combo.addItem(label)
        self.source_combo.setToolTip("Which backends to search")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        controls.addWidget(self.source_combo)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["Any status", "Installed", "Not installed"])
        self.status_filter.setToolTip("Filter the current results")
        self.status_filter.currentIndexChanged.connect(self._render)
        controls.addWidget(self.status_filter)
        root.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        root.addWidget(self.progress)

        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("statusText")
        root.addWidget(self.status_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contents = QWidget()
        contents.setObjectName("scrollContents")
        self.results_layout = QVBoxLayout(contents)
        self.results_layout.setContentsMargins(0, 0, 6, 0)
        self.results_layout.setSpacing(8)

        self.empty_lbl = QLabel()
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setObjectName("emptyState")
        self.results_layout.addWidget(self.empty_lbl)
        self.results_layout.addStretch()
        self.scroll.setWidget(contents)
        root.addWidget(self.scroll, stretch=1)

    # ================================================================== public
    @Slot()
    def refresh_statuses(self) -> None:
        """Re-check install state of the visible results (e.g. after another tab changed them)."""
        dnf.invalidate_caches()
        self._refresh_statuses()

    def focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    # ================================================================== searching
    @Slot(str)
    def _on_text_changed(self, _text: str) -> None:
        self._debounce.start()  # restarts if already running

    @Slot(int)
    def _on_source_changed(self, _index: int) -> None:
        if len(self.search_edit.text().strip()) >= self.MIN_QUERY_LEN:
            self._search_now()

    @Slot()
    def _search_now(self) -> None:
        self._debounce.stop()
        query = self.search_edit.text().strip()
        if len(query) < self.MIN_QUERY_LEN:
            self._request_id += 1  # invalidate anything in flight
            self._query = ""
            self._pending.clear()
            self._results.clear()
            self._errors.clear()
            self._show_idle()
            return
        _label, sources = _SOURCE_CHOICES[self.source_combo.currentIndex()]
        if query == self._query and sources == self._sources and self._pending:
            return  # identical search already running

        self._request_id += 1
        self._query = query
        self._sources = sources
        self._results.clear()
        self._errors.clear()
        self._pending = set(sources)

        self._workers = [w for w in self._workers if not w.done]
        for source in sources:
            worker = FunctionWorker(_search_job(source, query), request_id=self._request_id)
            worker.signals.result.connect(self._on_search_result)
            self._workers.append(worker)
            self._pool.start(worker)

        self.progress.show()
        self._clear_cards()
        self.empty_lbl.hide()
        self._update_status_label()

    @Slot(int, object)
    def _on_search_result(self, request_id: int, payload: object) -> None:
        if request_id != self._request_id:
            return  # stale: user kept typing
        source, packages, error = payload  # type: ignore[misc]
        self._results[source] = packages
        if error:
            self._errors[source] = error
        self._pending.discard(source)
        if not self._pending:
            self.progress.hide()
        self._render()

    # ================================================================== rendering
    def _all_results(self) -> list[Package]:
        merged = self._results.get(SOURCE_RPM, []) + self._results.get(SOURCE_FLATPAK, [])
        return dnf.rank_packages(merged, self._query) if self._query else merged

    def _passes_filter(self, pkg: Package) -> bool:
        mode = self.status_filter.currentIndex()
        installed = pkg.status in (PackageStatus.INSTALLED, PackageStatus.UPDATABLE)
        if mode == FILTER_INSTALLED:
            return installed
        if mode == FILTER_AVAILABLE:
            return not installed
        return True

    def _clear_cards(self) -> None:
        for card in self._cards.values():
            self.results_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    @Slot()
    def _render(self) -> None:
        self._clear_cards()
        if not self._query:
            self._show_idle()
            return

        visible = [pkg for pkg in self._all_results() if self._passes_filter(pkg)]
        insert_at = self.results_layout.indexOf(self.empty_lbl)
        for offset, pkg in enumerate(visible):
            card = PackageCard(pkg)
            card.action_requested.connect(self._on_action)
            card.set_actions_enabled(self._busy_key is None)
            if card.key == self._busy_key:
                card.set_busy(self._busy_text)
            self.results_layout.insertWidget(insert_at + offset, card)
            self._cards[card.key] = card

        if visible:
            self.empty_lbl.hide()
        elif not self._pending:
            total = len(self._all_results())
            self.empty_lbl.setText(
                f"No results for “{self._query}”."
                if total == 0
                else "No results match the current status filter."
            )
            self.empty_lbl.show()
        self._update_status_label()

    def _update_status_label(self) -> None:
        if not self._query:
            self.status_lbl.setText("Type at least two characters to search.")
            return
        rpm = self._results.get(SOURCE_RPM, [])
        flatpak = self._results.get(SOURCE_FLATPAK, [])
        parts: list[str] = []
        if self._pending:
            waiting = " + ".join(
                "RPM" if s == SOURCE_RPM else "Flatpak" for s in sorted(self._pending)
            )
            parts.append(f"Searching {waiting} for “{self._query}”…")
        total = len(rpm) + len(flatpak)
        if total or not self._pending:
            counts = f"{total} result{'s' if total != 1 else ''}"
            breakdown = []
            if SOURCE_RPM in self._results:
                breakdown.append(f"{len(rpm)} RPM")
            if SOURCE_FLATPAK in self._results:
                breakdown.append(f"{len(flatpak)} Flatpak")
            if breakdown:
                counts += " (" + ", ".join(breakdown) + ")"
            hidden = total - len(self._cards)
            if hidden > 0 and not self._pending:
                counts += f" · {hidden} hidden by filter"
            parts.append(counts)
        for source, error in self._errors.items():
            parts.append(f"⚠ {'RPM' if source == SOURCE_RPM else 'Flatpak'} search failed: {error}")
        self.status_lbl.setText("   ".join(parts))

    def _show_idle(self) -> None:
        self.progress.hide()
        self._clear_cards()
        self.empty_lbl.setText(
            "Search Fedora repositories, enabled COPRs and Flathub.\n"
            "Results show live install status – install or remove with one click."
        )
        self.empty_lbl.show()
        self._update_status_label()

    # ================================================================== actions
    @Slot(object, str)
    def _on_action(self, pkg: Package, action: str) -> None:
        if self._busy_key is not None:
            return  # one transaction at a time – dnf/rpm hold a global lock anyway

        is_flatpak = pkg.source is PackageSource.FLATPAK
        ident = (pkg.app_id or pkg.name) if is_flatpak else pkg.name

        if action == ACTION_REMOVE:
            extra = (
                "Unused runtimes are kept; clean them up from the Flatpak tab."
                if is_flatpak
                else "DNF will also remove any packages that depend on it.\n"
                "Review the transaction in the output window."
            )
            answer = QMessageBox.question(
                self,
                "Remove package",
                f"Remove <b>{pkg.name}</b>?<br><br>{extra.replace(chr(10), '<br>')}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            command = dnf.cmd_remove_flatpak(ident) if is_flatpak else dnf.cmd_remove_rpm(ident)
            verb, done_word, busy = "Removing", "removed", "Removing…"
        elif action == ACTION_INSTALL:
            command = (
                dnf.cmd_install_flatpak(ident, pkg.repo or "flathub")
                if is_flatpak
                else dnf.cmd_install_rpm(ident)
            )
            verb, done_word, busy = "Installing", "installed", "Installing…"
        else:
            logger.warning("Unsupported action %r for %s", action, ident)
            return

        # Flatpak system installs authorize through flatpak-system-helper's own polkit
        # policy, so only RPM transactions are wrapped in pkexec.
        task = CommandTask(
            self,
            f"{verb} {pkg.name}",
            command,
            use_pkexec=not is_flatpak,
            success_message=f"{pkg.name} {done_word}",
            failure_message=f"Could not {action} {pkg.name}",
        )
        task.done.connect(self._on_task_done)
        self._set_busy(package_key(pkg), busy)
        self.status_message.emit(f"{verb} {pkg.name}…", 0)
        task.start()

    def _set_busy(self, key: str | None, text: str | None) -> None:
        self._busy_key = key
        self._busy_text = text
        for card_key, card in self._cards.items():
            card.set_actions_enabled(key is None)
            card.set_busy(text if card_key == key else None)

    @Slot(bool, str)
    def _on_task_done(self, success: bool, message: str) -> None:
        self._set_busy(None, None)
        self.status_message.emit(message if not success else "Transaction complete", 5000)
        if not success:
            return
        dnf.invalidate_caches()
        self.packages_changed.emit()
        self._refresh_statuses()

    # ================================================================== status refresh
    def _refresh_statuses(self) -> None:
        """Re-check install state of every result (dnf may have pulled/removed dependencies)."""
        snapshot = self._all_results()
        if not snapshot:
            return
        # Tagged with the current search id: a newer search makes this result stale.
        worker = FunctionWorker(
            lambda: dnf.refresh_statuses(snapshot), request_id=self._request_id
        )
        worker.signals.result.connect(self._on_statuses_refreshed)
        self._workers = [w for w in self._workers if not w.done]
        self._workers.append(worker)
        self._pool.start(worker)

    @Slot(int, object)
    def _on_statuses_refreshed(self, request_id: int, refreshed: object) -> None:
        if request_id != self._request_id or self._pending:
            return  # a newer search replaced these results
        by_key = {package_key(p): p for p in refreshed}  # type: ignore[attr-defined]
        for source, packages in self._results.items():
            self._results[source] = [by_key.get(package_key(p), p) for p in packages]

        if self.status_filter.currentIndex() != FILTER_ANY:
            self._render()  # membership may have changed
            return
        for key, card in self._cards.items():
            updated = by_key.get(key)
            if updated is not None and updated != card.package:
                card.set_package(updated)
