"""Repos tab – DNF repositories, RPM Fusion / Flathub one-click setup, COPR management."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QWidget,
)

from syzygy.core import repos
from syzygy.core.models import Repository
from syzygy.core.repos import KIND_COPR, QuickSetupState
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import GREEN, RED, SURFACE1, TEXT, YELLOW
from syzygy.ui.widgets.page import (
    SCOPE_FLATPAK,
    SCOPE_PACKAGES,
    SCOPE_REPOS,
    BasePage,
    SortItem,
    check_item,
    make_table,
)

COL_ENABLED, COL_ID, COL_NAME, COL_KIND, COL_FILE = range(5)
_CORE_REPOS = ("fedora", "updates")

_FLATHUB_TEXT = {
    "missing": ("Not added", SURFACE1, TEXT),
    "filtered": ("Fedora-filtered", YELLOW, None),
    "disabled": ("Disabled", RED, None),
    "enabled": ("Enabled", GREEN, None),
}


class ReposTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_REPOS})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Repositories", "dnf5 / dnf · RPM Fusion · Flathub · COPR", parent)
        self._repos: list[Repository] = []
        self._populating = False

        # ------------------------------------------------ quick setup cards
        cards = QHBoxLayout()
        cards.setSpacing(10)

        self.rpmfusion_card = ActionCard(
            "RPM Fusion",
            "Community repos for codecs, NVIDIA drivers, Steam and other software Fedora "
            "can't ship.",
        )
        self.rpmfusion_btn = self.rpmfusion_card.add_button("Enable Free + Nonfree", primary=True)
        self.rpmfusion_btn.clicked.connect(self._enable_rpmfusion)
        cards.addWidget(self.rpmfusion_card)

        self.flathub_card = ActionCard(
            "Flathub",
            "The full Flathub catalogue. Fedora ships a curated, filtered subset by default.",
        )
        self.flathub_btn = self.flathub_card.add_button("Enable full Flathub", primary=True)
        self.flathub_btn.clicked.connect(self._enable_flathub)
        cards.addWidget(self.flathub_card)

        self.copr_card = ActionCard("Add COPR", "Enable a community build repo by owner/project.")
        self.copr_edit = QLineEdit()
        self.copr_edit.setPlaceholderText("owner/project  or  @group/project")
        self.copr_edit.returnPressed.connect(self._add_copr)
        self.copr_card.button_row.insertWidget(0, self.copr_edit, stretch=1)
        self.copr_btn = self.copr_card.add_button("Enable")
        self.copr_btn.clicked.connect(self._add_copr)
        cards.addWidget(self.copr_card)
        self.root.addLayout(cards)

        # ------------------------------------------------ table controls
        controls = QHBoxLayout()
        controls.setSpacing(8)
        section = QLabel("Configured repositories")
        section.setObjectName("sectionTitle")
        controls.addWidget(section)
        controls.addStretch()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter repositories…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._render)
        controls.addWidget(self.filter_edit)
        self.show_disabled = QCheckBox("Show disabled")
        self.show_disabled.setChecked(True)
        self.show_disabled.toggled.connect(self._render)
        controls.addWidget(self.show_disabled)
        self.remove_copr_btn = QPushButton("Remove selected COPR")
        self.remove_copr_btn.setProperty("danger", True)
        self.remove_copr_btn.clicked.connect(self._remove_selected_copr)
        controls.addWidget(self.remove_copr_btn)
        self.root.addLayout(controls)

        self.table = make_table(["On", "Repo ID", "Name", "Type", "File"], stretch_column=COL_NAME)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._sync_remove_button)
        self.root.addWidget(self.table, stretch=1)

        hint = QLabel("Tick or untick a repository to enable/disable it (requires administrator "
                      "authentication).")
        hint.setObjectName("hintText")
        self.root.addWidget(hint)

        self.track(self.rpmfusion_btn, self.flathub_btn, self.copr_btn, self.copr_edit,
                   self.remove_copr_btn)
        self._sync_remove_button()

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Reading repository configuration…")
        self.run_query("repos", repos.list_repositories, self._on_repos)
        self.run_query("setup", repos.get_quick_setup_state, self._on_setup)

    def _on_repos(self, value: object) -> None:
        self._repos = list(value)  # type: ignore[call-overload]
        self._render()

    def _on_setup(self, value: object) -> None:
        assert isinstance(value, QuickSetupState)
        card = self.rpmfusion_card
        card.clear_badges()
        card.add_badge("Free ✔" if value.rpmfusion_free else "Free ✘",
                       GREEN if value.rpmfusion_free else SURFACE1)
        card.add_badge("Nonfree ✔" if value.rpmfusion_nonfree else "Nonfree ✘",
                       GREEN if value.rpmfusion_nonfree else SURFACE1)
        both = value.rpmfusion_free and value.rpmfusion_nonfree
        self.rpmfusion_btn.setText("Installed" if both else "Enable Free + Nonfree")
        self._set_locked(self.rpmfusion_btn, both, "RPM Fusion Free and Nonfree are installed")

        self.flathub_card.clear_badges()
        text, color, _fg = _FLATHUB_TEXT.get(value.flathub, _FLATHUB_TEXT["missing"])
        self.flathub_card.add_badge(text, color)
        full = value.flathub == "enabled"
        self.flathub_btn.setText("Enabled" if full else "Enable full Flathub")
        self._set_locked(self.flathub_btn, full, "Flathub is enabled without filter")

    def _set_locked(self, btn: QPushButton, locked: bool, reason: str) -> None:
        if locked:
            self.lock(btn, reason)
        else:
            btn.setProperty("syzygyLocked", False)
            btn.setToolTip("")
            btn.setEnabled(not self.busy)

    def _render(self) -> None:
        text = self.filter_edit.text().strip().lower()
        show_disabled = self.show_disabled.isChecked()
        visible = [
            r for r in self._repos
            if (show_disabled or r.enabled)
            and (not text or text in r.id.lower() or text in r.name.lower())
        ]
        self._populating = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for repo in visible:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = check_item(repo.enabled, enabled=not self.busy)
            check.setData(Qt.ItemDataRole.UserRole, repo.id)
            self.table.setItem(row, COL_ENABLED, check)
            id_item = SortItem(repo.id)
            id_item.setData(Qt.ItemDataRole.UserRole, repo.id)
            self.table.setItem(row, COL_ID, id_item)
            self.table.setItem(row, COL_NAME, SortItem(repo.name))
            self.table.setItem(row, COL_KIND, SortItem(repos.repo_kind(repo)))
            file_item = SortItem(repo.file_path.name if repo.file_path else "")
            if repo.file_path:
                file_item.setToolTip(str(repo.file_path))
            self.table.setItem(row, COL_FILE, file_item)
        self.table.setSortingEnabled(True)
        self._populating = False

        enabled = sum(r.enabled for r in self._repos)
        copr = sum(repos.repo_kind(r) == KIND_COPR for r in self._repos)
        self.set_status(f"{len(self._repos)} repositories · {enabled} enabled · {copr} COPR")
        self._sync_remove_button()

    def _repo(self, repo_id: str) -> Repository | None:
        return next((r for r in self._repos if r.id == repo_id), None)

    def on_busy_changed(self, busy: bool) -> None:
        self.table.setEnabled(not busy)
        if not busy:
            self._sync_remove_button()

    # ================================================================== toggling
    @Slot(QTableWidgetItem)
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() != COL_ENABLED:
            return
        repo_id = item.data(Qt.ItemDataRole.UserRole)
        enable = item.checkState() == Qt.CheckState.Checked
        if not enable and repo_id in _CORE_REPOS:
            ok = self.confirm(
                "Disable core repository",
                f"<b>{escape(repo_id)}</b> is a core Fedora repository. Disabling it stops "
                "updates and security fixes for most packages.<br><br>Disable anyway?",
            )
            if not ok:
                self._render()
                return
        command = repos.cmd_enable_repo(repo_id) if enable else repos.cmd_disable_repo(repo_id)
        verb = "Enabling" if enable else "Disabling"
        started = self.run_task(
            f"{verb} {repo_id}", command, use_pkexec=True, scope=SCOPE_REPOS,
            success_message=f"{repo_id} {'enabled' if enable else 'disabled'}",
            on_done=lambda success: None if success else self.refresh(),  # revert checkbox
        )
        if not started:
            self._render()

    # ================================================================== quick setup
    @Slot()
    def _enable_rpmfusion(self) -> None:
        self.run_task(
            "Enabling RPM Fusion", repos.cmd_install_rpmfusion_both(), use_pkexec=True,
            scope=SCOPE_REPOS, success_message="RPM Fusion enabled",
            confirm=f"Install the RPM Fusion Free and Nonfree release packages for Fedora "
                    f"{escape(repos.get_fedora_version())}?<br><br>This downloads them from "
                    "mirrors.rpmfusion.org and imports their signing keys.",
            on_done=lambda ok: ok and self.system_changed.emit(SCOPE_PACKAGES),
        )

    @Slot()
    def _enable_flathub(self) -> None:
        self.run_task(
            "Enabling Flathub", repos.cmd_enable_full_flathub(), use_pkexec=False,
            scope=SCOPE_FLATPAK, success_message="Flathub enabled",
        )

    @Slot()
    def _add_copr(self) -> None:
        slug = self.copr_edit.text().strip()
        if not repos.is_valid_copr_slug(slug):
            self.set_status("COPR must look like owner/project or @group/project.",
                            level="warning")
            self.copr_edit.setFocus()
            return
        if self.run_task(
            f"Enabling COPR {slug}", repos.cmd_add_copr(slug), use_pkexec=True,
            scope=SCOPE_REPOS, success_message=f"COPR {slug} enabled",
            confirm=f"Enable COPR <b>{escape(slug)}</b>?<br><br>COPR repositories are built by "
                    "community members and are not reviewed by Fedora.",
        ):
            self.copr_edit.clear()

    def _selected_copr(self) -> tuple[str, str] | None:
        rows = {i.row() for i in self.table.selectedItems()}
        if len(rows) != 1:
            return None
        id_item = self.table.item(rows.pop(), COL_ID)
        repo_id = id_item.data(Qt.ItemDataRole.UserRole) if id_item else None
        repo = self._repo(repo_id) if repo_id else None
        if repo is None or repos.repo_kind(repo) != KIND_COPR:
            return None
        slug = repos.copr_slug_from_repo_id(repo.id)
        return (repo.id, slug) if slug else None

    def _sync_remove_button(self) -> None:
        if not self.busy:
            self.remove_copr_btn.setEnabled(self._selected_copr() is not None)

    @Slot()
    def _remove_selected_copr(self) -> None:
        selected = self._selected_copr()
        if selected is None:
            return
        _repo_id, slug = selected
        self.run_task(
            f"Removing COPR {slug}", repos.cmd_remove_copr(slug), use_pkexec=True,
            scope=SCOPE_REPOS, success_message=f"COPR {slug} removed",
            confirm=f"Remove COPR <b>{escape(slug)}</b>?<br><br>Packages already installed from "
                    "it stay installed but will no longer receive updates.",
        )
