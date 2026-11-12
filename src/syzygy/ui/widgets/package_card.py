"""Card widget representing one RPM / COPR / Flatpak package with a primary action button."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from syzygy.core.models import Package, PackageSource, PackageStatus
from syzygy.ui.widgets.badge import BLUE, GREEN, MAUVE, PEACH, SURFACE1, YELLOW, Badge

ACTION_INSTALL = "install"
ACTION_REMOVE = "remove"
ACTION_UPDATE = "update"

_SOURCE_BADGES: dict[PackageSource, tuple[str, str]] = {
    PackageSource.DNF: ("RPM", BLUE),
    PackageSource.COPR: ("COPR", PEACH),
    PackageSource.FLATPAK: ("Flatpak", MAUVE),
    PackageSource.LOCAL: ("Local", SURFACE1),
    PackageSource.UNKNOWN: ("?", SURFACE1),
}


def package_key(pkg: Package) -> str:
    """Stable identity for a package across refreshes (Flatpak by app-id, RPM by name)."""
    if pkg.source is PackageSource.FLATPAK:
        key = f"flatpak:{pkg.app_id or pkg.name}"
        # Installed lists can hold the same app twice (stable + beta, system + user).
        if pkg.installation:
            key += f"//{pkg.branch or ''}@{pkg.installation}"
        return key
    if pkg.arch and pkg.version:
        # Status-independent on purpose (a refresh flips status but must keep the key).
        # Installed RPMs can coexist per version (installonly kernels) and per arch (multilib).
        return f"rpm:{pkg.name}-{pkg.version}.{pkg.arch}"
    return f"rpm:{pkg.name}"


class PackageCard(QFrame):
    """Emits ``action_requested(package, action)`` where action is install/remove/update."""

    action_requested = Signal(object, str)

    def __init__(
        self,
        package: Package,
        parent: QWidget | None = None,
        *,
        show_update_action: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("packageCard")  # styled globally in ui/styles.py
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._package = package
        self._show_update_action = show_update_action
        self._actions_enabled = True
        self._busy_text: str | None = None
        self._locked_label: str | None = None
        self._locked_reason = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(12)

        info = QVBoxLayout()
        info.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.name_lbl = QLabel()
        self.name_lbl.setObjectName("cardName")
        self.name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.version_lbl = QLabel()
        self.version_lbl.setObjectName("cardVersion")
        self.source_badge = Badge("")
        self.status_badge = Badge("")
        title_row.addWidget(self.name_lbl)
        title_row.addWidget(self.version_lbl)
        title_row.addWidget(self.source_badge)
        title_row.addWidget(self.status_badge)
        title_row.addStretch()
        info.addLayout(title_row)

        self.summary_lbl = QLabel()
        self.summary_lbl.setWordWrap(True)
        self.summary_lbl.setObjectName("cardSummary")
        info.addWidget(self.summary_lbl)

        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("cardMeta")
        self.meta_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.addWidget(self.meta_lbl)

        root.addLayout(info, stretch=1)

        self.action_btn = QPushButton()
        self.action_btn.setMinimumWidth(104)
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.clicked.connect(self._on_clicked)
        root.addWidget(self.action_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.set_package(package)

    # ------------------------------------------------------------------ API
    @property
    def package(self) -> Package:
        return self._package

    @property
    def key(self) -> str:
        return package_key(self._package)

    def set_package(self, package: Package) -> None:
        self._package = package
        self.name_lbl.setText(package.name)
        self.version_lbl.setText(package.version)
        self.version_lbl.setVisible(bool(package.version))

        text, color = _SOURCE_BADGES.get(package.source, _SOURCE_BADGES[PackageSource.UNKNOWN])
        self.source_badge.update_badge(text, color)

        if package.status is PackageStatus.INSTALLED:
            self.status_badge.update_badge("Installed", GREEN)
            self.status_badge.show()
        elif package.status is PackageStatus.UPDATABLE:
            self.status_badge.update_badge("Update", YELLOW)
            self.status_badge.show()
        else:
            self.status_badge.hide()

        self.summary_lbl.setText(package.summary or "No description available")

        meta = [part for part in (package.repo, package.arch, package.size) if part]
        if package.source is PackageSource.FLATPAK:
            fields = (package.app_id, package.branch, package.repo, package.installation,
                      package.size)
            meta = [p for p in fields if p]
        self.meta_lbl.setText("  ·  ".join(meta))
        self.meta_lbl.setVisible(bool(meta))

        self._busy_text = None
        self._refresh_button()

    def set_actions_enabled(self, enabled: bool) -> None:
        self._actions_enabled = enabled
        self._refresh_button()

    def set_locked(self, reason: str | None, label: str = "Protected") -> None:
        """Permanently disable the action (e.g. DNF-protected package, running kernel)."""
        self._locked_label = label if reason else None
        self._locked_reason = reason or ""
        self._refresh_button()

    def set_busy(self, text: str | None) -> None:
        """Show e.g. 'Installing…' on this card's button; ``None`` restores the normal label."""
        self._busy_text = text
        self._refresh_button()

    # ------------------------------------------------------------------ internals
    def _action(self) -> str:
        status = self._package.status
        if status is PackageStatus.UPDATABLE and self._show_update_action:
            return ACTION_UPDATE
        if status in (PackageStatus.INSTALLED, PackageStatus.UPDATABLE):
            return ACTION_REMOVE
        return ACTION_INSTALL

    def _refresh_button(self) -> None:
        action = self._action()
        label = {ACTION_INSTALL: "Install", ACTION_REMOVE: "Remove", ACTION_UPDATE: "Update"}
        if self._locked_label is not None:
            self.action_btn.setText(self._locked_label)
            self.action_btn.setEnabled(False)
            self.action_btn.setToolTip(self._locked_reason)
            action = ""  # neutral styling
        else:
            self.action_btn.setText(self._busy_text or label[action])
            self.action_btn.setEnabled(self._actions_enabled and self._busy_text is None)
            self.action_btn.setToolTip("")
        # Property-driven QSS (styles.py) needs an explicit re-polish when the value changes.
        self.action_btn.setProperty("primary", action in (ACTION_INSTALL, ACTION_UPDATE))
        self.action_btn.setProperty("danger", action == ACTION_REMOVE)
        style = self.action_btn.style()
        style.unpolish(self.action_btn)
        style.polish(self.action_btn)

    @Slot()
    def _on_clicked(self) -> None:
        self.action_requested.emit(self._package, self._action())
