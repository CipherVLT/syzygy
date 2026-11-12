"""Hover glow for cards: a soft accent-coloured drop shadow while the pointer is over a widget.

The effect is attached only while hovered (one widget at a time), so long card lists stay
cheap to paint.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from syzygy.ui import theme


class HoverGlow(QObject):
    def __init__(self, widget: QWidget, *, radius: int = 26, alpha: int = 110) -> None:
        super().__init__(widget)
        self._radius = radius
        self._alpha = alpha
        widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 – Qt override
        if not isinstance(obj, QWidget):
            return False
        if event.type() == QEvent.Type.Enter:
            color_name = theme.current_palette().glow
            if color_name and obj.isEnabled():
                color = QColor(color_name)
                color.setAlpha(self._alpha)
                effect = QGraphicsDropShadowEffect(obj)
                effect.setBlurRadius(self._radius)
                effect.setOffset(0, 0)
                effect.setColor(color)
                obj.setGraphicsEffect(effect)
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
            obj.setGraphicsEffect(None)
        return False


def install_hover_glow(widget: QWidget) -> HoverGlow:
    return HoverGlow(widget)
