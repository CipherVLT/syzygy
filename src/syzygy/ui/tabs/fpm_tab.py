"""FPM tab – Flatpak remotes, local .flatpakref/.flatpak installs and permission overrides."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from syzygy.core import flatpak, fpm
from syzygy.core.flatpak import FlatpakEntry
from syzygy.core.fpm import FlatpakRemote
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, GREEN, SURFACE1, YELLOW
from syzygy.ui.widgets.page import SCOPE_FLATPAK, BasePage
from syzygy.ui.widgets.sidebar import SidebarItem, SidebarSplit, heading


def _load() -> tuple[list[FlatpakRemote], list[FlatpakEntry]]:
    return fpm.list_flatpak_remotes(), flatpak.list_installed_apps()


class FpmTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_FLATPAK})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Flatpak Manager", "Remotes · bundles · permissions", parent)
        self._remotes: list[FlatpakRemote] = []
        self._apps: list[FlatpakEntry] = []

        self._remote_cards: list[QWidget] = []

        self.split = SidebarSplit(sidebar_width=210)
        self.split.add_page("remotes", self._build_remotes_page())
        self.split.add_page("install", self._build_install_page())
        self.split.add_page("permissions", self._build_permissions_page())
        self.root.addWidget(self.split, stretch=1)
        self._set_sidebar()

    def _set_sidebar(self) -> None:
        self.split.set_items([
            heading("Flatpak"),
            SidebarItem("remotes", "Remotes", "remotes", len(self._remotes) or None),
            SidebarItem("install", "Install from file", "install"),
            SidebarItem("permissions", "Permissions", "permissions", len(self._apps) or None),
        ])

    # ================================================================== pages
    def _build_remotes_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        add_card = ActionCard("Add remote", "Name plus a repository URL or .flatpakrepo URL.")
        self.remote_name = QLineEdit()
        self.remote_name.setPlaceholderText("name (e.g. flathub-beta)")
        self.remote_url = QLineEdit()
        self.remote_url.setPlaceholderText(
            "https://flathub.org/beta-repo/flathub-beta.flatpakrepo")
        self.remote_user = QCheckBox("Per-user")
        self.remote_user.setToolTip("Add to your user installation instead of system-wide")
        add_card.button_row.insertWidget(0, self.remote_name, stretch=1)
        add_card.button_row.insertWidget(1, self.remote_url, stretch=2)
        add_card.button_row.insertWidget(2, self.remote_user)
        self.add_remote_btn = add_card.add_button("Add", primary=True)
        self.add_remote_btn.clicked.connect(self._add_remote)
        layout.addWidget(add_card)

        scroll, self.remotes_column = self.make_scroll_column()
        self.remotes_column.addStretch()
        layout.addWidget(scroll, stretch=1)

        self.track(self.add_remote_btn, self.remote_name, self.remote_url, self.remote_user)
        return page

    def _build_install_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        card = ActionCard(
            "Install a local Flatpak file",
            "• .flatpakref – a reference to an app in a remote (installs from the network)\n"
            "• .flatpak – a self-contained single-file bundle\n"
            "• .flatpakrepo – adds the remote it describes",
        )
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Choose a .flatpakref, .flatpak or .flatpakrepo file…")
        self.file_edit.setReadOnly(True)
        card.button_row.insertWidget(0, self.file_edit, stretch=1)
        browse = card.add_button("Browse…")
        browse.clicked.connect(self._browse)
        self.install_file_btn = card.add_button("Install", primary=True)
        self.install_file_btn.clicked.connect(self._install_file)
        self.install_file_btn.setEnabled(False)
        layout.addWidget(card)
        layout.addStretch()
        self.track(browse, self.install_file_btn)
        return page

    def _build_permissions_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        row.addWidget(QLabel("App:"))
        self.app_combo = QComboBox()
        self.app_combo.setMinimumWidth(320)
        self.app_combo.currentIndexChanged.connect(self._on_app_changed)
        row.addWidget(self.app_combo, stretch=1)
        layout.addLayout(row)

        self.overrides_text = QPlainTextEdit()
        self.overrides_text.setReadOnly(True)
        self.overrides_text.setPlaceholderText("Per-user overrides for the selected app…")
        layout.addWidget(self.overrides_text, stretch=1)

        fs_card = ActionCard(
            "Filesystem access",
            "Grant or revoke access for the selected app. Use a preset or a path; append "
            ":ro for read-only. Overrides are per-user (no password needed), like Flatseal.",
        )
        self.fs_combo = QComboBox()
        self.fs_combo.setEditable(True)
        self.fs_combo.addItems(list(fpm.FILESYSTEM_PRESETS))
        self.fs_combo.setCurrentText("xdg-download")
        fs_card.button_row.insertWidget(0, self.fs_combo, stretch=1)
        self.grant_btn = fs_card.add_button("Grant", primary=True)
        self.grant_btn.clicked.connect(lambda: self._filesystem(grant=True))
        self.revoke_btn = fs_card.add_button("Revoke")
        self.revoke_btn.clicked.connect(lambda: self._filesystem(grant=False))
        self.reset_btn = fs_card.add_button("Reset all overrides", danger=True)
        self.reset_btn.clicked.connect(self._reset_overrides)
        layout.addWidget(fs_card)

        self.track(self.app_combo, self.fs_combo, self.grant_btn, self.revoke_btn,
                   self.reset_btn)
        return page

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Reading Flatpak remotes and apps…")
        self.run_query("load", _load, self._on_loaded)

    def _on_loaded(self, value: object) -> None:
        remotes, apps = value  # type: ignore[misc]
        self._remotes, self._apps = remotes, apps
        self._render_remotes()

        current = self.app_combo.currentData()
        self.app_combo.blockSignals(True)
        self.app_combo.clear()
        for app in sorted(apps, key=lambda a: a.name.lower()):
            self.app_combo.addItem(f"{app.name}  ({app.application})", app.application)
        index = self.app_combo.findData(current) if current else 0
        self.app_combo.setCurrentIndex(max(index, 0))
        self.app_combo.blockSignals(False)
        self._on_app_changed()

        self._set_sidebar()
        enabled = sum(r.is_enabled for r in remotes)
        self.set_status(f"{len(remotes)} remotes ({enabled} enabled)   ·   "
                        f"{len(apps)} apps installed")

    def _render_remotes(self) -> None:
        for card in self._remote_cards:
            self.remotes_column.removeWidget(card)
            card.deleteLater()
        self._remote_cards.clear()
        for remote in self._remotes:
            card = ActionCard(remote.title or remote.name, remote.url)
            card.add_badge(remote.name, SURFACE1)
            card.add_badge(remote.installation, BLUE)
            if remote.is_enabled:
                card.add_badge("Enabled", GREEN)
                card.set_accent("green")
            else:
                card.add_badge("Disabled", SURFACE1)
            if "filtered" in remote.options:
                card.add_badge("Filtered", YELLOW)
            toggle = card.add_button("Disable" if remote.is_enabled else "Enable",
                                     primary=not remote.is_enabled)
            toggle.clicked.connect(lambda _c=False, r=remote: self._toggle_remote(r))
            remove = card.add_button("Remove", danger=True)
            remove.clicked.connect(lambda _c=False, r=remote: self._remove_remote(r))
            self.track(toggle, remove)
            self.remotes_column.insertWidget(self.remotes_column.count() - 1, card)
            self._remote_cards.append(card)
        if not self._remotes:
            card = ActionCard("No Flatpak remotes",
                              "Add Flathub from the Repos tab or with the form above.")
            self.remotes_column.insertWidget(0, card)
            self._remote_cards.append(card)

    def on_busy_changed(self, busy: bool) -> None:
        if not busy:
            self.install_file_btn.setEnabled(fpm.bundle_kind(self.file_edit.text()) is not None)
            has_app = bool(self._current_app())
            for widget in (self.grant_btn, self.revoke_btn, self.reset_btn):
                widget.setEnabled(has_app)

    def _toggle_remote(self, remote: FlatpakRemote) -> None:
        enable = not remote.is_enabled
        confirm = None
        if not enable and remote.name == "flathub":
            confirm = ("Disable <b>flathub</b>?<br><br>Apps installed from it will stop "
                       "receiving updates until it is enabled again.")
        self.run_task(
            f"{'Enabling' if enable else 'Disabling'} remote {remote.name}",
            fpm.cmd_toggle_remote(remote.name, enable, remote.installation),
            use_pkexec=False, scope=SCOPE_FLATPAK, confirm=confirm,
            success_message=f"Remote {remote.name} {'enabled' if enable else 'disabled'}",
        )

    def _remove_remote(self, remote: FlatpakRemote) -> None:
        self.run_task(
            f"Removing remote {remote.name}",
            fpm.cmd_remove_remote(remote.name, remote.installation),
            use_pkexec=False, scope=SCOPE_FLATPAK,
            success_message=f"Remote {remote.name} removed",
            confirm=f"Remove remote <b>{escape(remote.name)}</b> ({escape(remote.installation)})?"
                    "<br><br><code>--force</code> is used: apps installed from it stay installed "
                    "but can no longer be updated.",
        )

    @Slot()
    def _add_remote(self) -> None:
        name = self.remote_name.text().strip()
        url = self.remote_url.text().strip()
        if not fpm.is_valid_remote_name(name):
            self.set_status("Remote name may only contain letters, digits, '.', '_' and '-'.",
                            level="warning")
            return
        if not fpm.is_valid_remote_url(url):
            self.set_status("Enter an https:// URL or a .flatpakrepo URL.", level="warning")
            return
        if self.run_task(
            f"Adding remote {name}", fpm.cmd_add_remote(name, url,
                                                        user=self.remote_user.isChecked()),
            use_pkexec=False, scope=SCOPE_FLATPAK, success_message=f"Remote {name} added",
        ):
            self.remote_name.clear()
            self.remote_url.clear()

    # ================================================================== install from file
    @Slot()
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Flatpak file", str(Path.home() / "Downloads"),
            "Flatpak files (*.flatpakref *.flatpak *.flatpakrepo);;All files (*)",
        )
        if path:
            self.file_edit.setText(path)
            self.install_file_btn.setEnabled(fpm.bundle_kind(path) is not None and not self.busy)
            if fpm.bundle_kind(path) is None:
                self.set_status("Unsupported file type – pick a .flatpakref, .flatpak or "
                                ".flatpakrepo file.", level="warning")

    @Slot()
    def _install_file(self) -> None:
        path = self.file_edit.text()
        kind = fpm.bundle_kind(path)
        if not path or kind is None:
            return
        label = {"ref": "Installing from .flatpakref", "bundle": "Installing Flatpak bundle",
                 "repo": "Adding remote from .flatpakrepo"}[kind]
        self.run_task(
            label, fpm.cmd_install_flatpakref(path), use_pkexec=False, scope=SCOPE_FLATPAK,
            success_message=f"{Path(path).name} installed",
            confirm=f"{label}:<br><code>{escape(path)}</code>?<br><br>Only install files from "
                    "sources you trust.",
        )

    # ================================================================== permissions
    def _current_app(self) -> str:
        data = self.app_combo.currentData()
        return data if isinstance(data, str) else ""

    @Slot()
    def _on_app_changed(self, _index: int = 0) -> None:
        app_id = self._current_app()
        has_app = bool(app_id)
        for widget in (self.grant_btn, self.revoke_btn, self.reset_btn):
            widget.setEnabled(has_app and not self.busy)
        if not has_app:
            self.overrides_text.setPlainText("No Flatpak apps installed.")
            return
        self.overrides_text.setPlainText("Loading…")
        self.run_query("overrides", lambda: fpm.get_app_overrides(app_id, user=True),
                       self._on_overrides)

    def _on_overrides(self, value: object) -> None:
        self.overrides_text.setPlainText(str(value))

    def _filesystem(self, *, grant: bool) -> None:
        app_id = self._current_app()
        fs_value = self.fs_combo.currentText().strip()
        if not app_id:
            return
        if not fpm.is_valid_filesystem(fs_value):
            self.set_status("Use a preset (home, host, xdg-download…) or an absolute/~ path.",
                            level="warning")
            return
        command = (fpm.cmd_grant_filesystem_override(app_id, fs_value) if grant
                   else fpm.cmd_revoke_filesystem_override(app_id, fs_value))
        verb = "Granting" if grant else "Revoking"
        confirm = None
        if grant and fs_value.split(":")[0] in ("host", "host-os", "host-etc", "home"):
            confirm = (f"Give <b>{escape(app_id)}</b> access to <code>{escape(fs_value)}</code>?"
                       "<br><br>This weakens the sandbox considerably.")
        self.run_task(
            f"{verb} {fs_value} for {app_id}", command, use_pkexec=False, confirm=confirm,
            success_message=f"Override updated for {app_id}",
            on_done=lambda ok: self._on_app_changed(), refresh_after=False,
        )

    @Slot()
    def _reset_overrides(self) -> None:
        app_id = self._current_app()
        if not app_id:
            return
        self.run_task(
            f"Resetting overrides for {app_id}", fpm.cmd_reset_overrides(app_id),
            use_pkexec=False, success_message=f"Overrides reset for {app_id}",
            confirm=f"Remove all per-user overrides for <b>{escape(app_id)}</b>?",
            on_done=lambda ok: self._on_app_changed(), refresh_after=False,
        )
