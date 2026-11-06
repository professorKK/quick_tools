"""Qt 与纯几何模块之间的适配层。

只有 helper 进程会导入这个模块；``geometry.py`` 本身保持无 Qt 依赖。
"""

from __future__ import annotations

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget

from .geometry import Rect, ScreenArea, Size


def screen_areas() -> list[ScreenArea]:
    """Snapshot every screen's available geometry."""
    areas: list[ScreenArea] = []
    for screen in QGuiApplication.screens():
        geometry = screen.availableGeometry()
        areas.append(
            ScreenArea(
                name=screen.name() or "",
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
        )
    return areas


def primary_screen_name() -> str | None:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    return screen.name() or None


def rect_for(widget: QWidget) -> Rect:
    return Rect(
        x=widget.x(),
        y=widget.y(),
        width=widget.width(),
        height=widget.height(),
    )


def size_of(widget: QWidget) -> Size:
    return Size(width=widget.width(), height=widget.height())
