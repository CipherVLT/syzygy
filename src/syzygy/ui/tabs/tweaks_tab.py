"""Tweaks tab – one-click system tweaks with live Active / Available state."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QWidget

from syzygy.core import tweaks
from syzygy.core.tweaks import Tweak, TweakState
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, GREEN, PEACH, SURFACE1
from syzygy.ui.widgets.page import (
    SCOPE_FLATPAK,
    SCOPE_KERNELS,
    SCOPE_PACKAGES,
    SCOPE_REPOS,
    BasePage,
)


def _probe() -> dict[str, TweakState]:
    # Fresh registry each time so cached environment facts (RPM Fusion, Flathub) are re-read.
    return tweaks.probe_all(tweaks.build_registry())


class TweaksTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_PACKAGES, SCOPE_REPOS, SCOPE_FLATPAK})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Tweaks", "One-click system setup", parent)
        self._registry = tweaks.build_registry()
        self._cards: dict[str, ActionCard] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._states: dict[str, TweakState] = {}

        scroll, column = self.make_scroll_column()
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, tweak in enumerate(self._registry):
            card = ActionCard(tweak.title, tweak.description)
            card.add_badge("Checking…", SURFACE1)
            btn = card.add_button(tweak.action_label, primary=True)
            btn.clicked.connect(lambda _c=False, t=tweak: self._apply(t))
            btn.setEnabled(False)
            self.track(btn)
            self._cards[tweak.id] = card
            self._buttons[tweak.id] = btn
            grid.addWidget(card, index // 2, index % 2)
        column.addLayout(grid)
        note = QLabel("States are detected live from the RPM database, Flatpak and "
                      "/etc/dnf/dnf.conf. NVIDIA driver setup (official .run installer path) "
                      "is planned for a future release.")
        note.setObjectName("hintText")
        note.setWordWrap(True)
        column.addWidget(note)
        column.addStretch()
        self.root.addWidget(scroll, stretch=1)

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Detecting current system state…")
        self.run_query("probe", _probe, self._on_states)

    def _on_states(self, value: object) -> None:
        states: dict[str, TweakState] = dict(value)  # type: ignore[call-overload]
        self._states = states
        active = 0
        for tweak in self._registry:
            state = states.get(tweak.id, TweakState(False))
            active += state.active
            self._render_card(tweak, state)
        self.set_status(f"{active} of {len(self._registry)} tweaks active")

    def _render_card(self, tweak: Tweak, state: TweakState) -> None:
        card = self._cards[tweak.id]
        btn = self._buttons[tweak.id]
        card.clear_badges()
        if state.active:
            card.add_badge("Active", GREEN)
        elif state.available:
            card.add_badge("Available", BLUE)
        else:
            card.add_badge("Unavailable", SURFACE1)
        if tweak.use_pkexec:
            card.add_badge("admin", PEACH)
        card.set_meta(state.note)

        partially = state.active and bool(state.note) and state.note.startswith("Missing")
        btn.setProperty("syzygyLocked", False)
        btn.setToolTip("")
        if state.active and not partially:
            btn.setText("Active ✔")
            self.lock(btn, "Already applied")
        elif not state.available:
            btn.setText(tweak.action_label)
            self.lock(btn, state.note or "Prerequisites missing")
        else:
            btn.setText("Complete install" if partially else tweak.action_label)
            btn.setEnabled(not self.busy)

    # ================================================================== actions
    def _apply(self, tweak: Tweak) -> None:
        state = self._states.get(tweak.id, TweakState(False))
        confirm = f"<b>{escape(tweak.title)}</b><br><br>{escape(tweak.description)}"
        if state.warning:
            confirm += f"<br><br>⚠ <b>{escape(state.warning)}</b>"
        command_preview = " ".join(tweak.command())
        if len(command_preview) < 200:
            confirm += f"<br><br><code>{escape(command_preview)}</code>"

        scope_map = {"packages": SCOPE_PACKAGES, "repos": SCOPE_REPOS,
                     "flatpak": SCOPE_FLATPAK, "kernels": SCOPE_KERNELS}
        scopes = [scope_map[s] for s in tweak.scopes if s in scope_map]

        def broadcast(success: bool) -> None:
            if success:
                for scope in scopes[1:]:  # first one is emitted by run_task itself
                    self.system_changed.emit(scope)

        self.run_task(
            tweak.title, tweak.command(), use_pkexec=tweak.use_pkexec, confirm=confirm,
            scope=scopes[0] if scopes else None, on_done=broadcast,
            success_message=f"{tweak.title} applied",
            failure_message=f"{tweak.title} failed",
        )
