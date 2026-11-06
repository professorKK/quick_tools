"""gp 悬浮窗：桌面上的圆形无边框小窗。

这个模块只运行在 helper 进程里（PyQt6 独立进程），主进程的 Tk 永远不会
导入它，避免两套事件循环混用。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from PyQt6.QtCore import QPoint, QTimer, Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QMenu, QWidget

from .geometry import (
    SCREEN_MARGIN,
    Rect,
    Size,
    clamp_into,
    default_position,
    position_after_resize,
    resolve_position,
    screen_by_name,
    screen_for_rect,
)
from .qt_screens import (
    primary_screen_name,
    rect_for,
    screen_areas,
)
from .settings import DEFAULT_TEXT, GpSettings

# 填充背景关闭时的描边色与文字色：保持透明圆圈也能看清。
RING_COLOR = QColor("#94a3b8")
TEXT_COLOR = QColor("#0f172a")
TEXT_HALO_COLOR = QColor("#ffffff")
# 填充背景打开时的配色。
FILLED_RING_COLOR = QColor("#ffffff")
FILLED_TEXT_COLOR = QColor("#ffffff")
FILL_COLOR = QColor("#2563eb")

EVENT_CLOSED = "closed"

# 手动输入允许直径 0，但窗口至少保留这么大的可点击区域，避免完全消失后
# 无法再右键打开设置恢复。
MIN_RENDER_DIAMETER = 10


class FloatingWidget(QWidget):
    """A circular, always-on-top desktop widget with hover transparency."""

    def __init__(
        self,
        settings: GpSettings,
        *,
        on_open_settings: Callable[[], None],
        on_exit: Callable[[], None],
        emit: Callable[[str], None],
        persist: Callable[[GpSettings], None],
    ) -> None:
        super().__init__(None)
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit
        self._emit = emit
        self._persist = persist
        self._settings = settings.normalized()
        self._hovered = False
        # 右键菜单是独立弹窗，会抢走鼠标并触发本窗口的 leaveEvent。
        # 菜单打开期间保持悬停透明度，关闭后再按鼠标实际位置重新判定。
        self._menu_open = False
        self._dragging = False
        self._drag_offset: QPoint | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 不抢焦点，悬浮窗只是安静地待在桌面上。
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle("gp 插件")
        render_diameter = max(self._settings.diameter, MIN_RENDER_DIAMETER)
        self.setFixedSize(render_diameter, render_diameter)
        self._apply_opacity()

    # ------------------------------------------------------------- settings
    @property
    def settings(self) -> GpSettings:
        return self._settings

    def apply_appearance(self, values: GpSettings) -> bool:
        """Apply appearance fields and keep the saved position in control.

        Returns True when a saved position changed (the caller should persist
        immediately instead of waiting for the debounce timer).
        """
        normalized = values.normalized()
        old_rect = rect_for(self)
        old_diameter = self.width()
        self._settings = replace(
            self._settings,
            idle_opacity=normalized.idle_opacity,
            active_opacity=normalized.active_opacity,
            diameter=normalized.diameter,
            text=normalized.text,
            fill_background=normalized.fill_background,
        )
        moved = False
        render_diameter = max(normalized.diameter, MIN_RENDER_DIAMETER)
        if render_diameter != old_diameter:
            self.setFixedSize(render_diameter, render_diameter)
            moved = self._reposition_after_resize(old_rect)
        self._apply_opacity()
        self.update()
        return moved

    def _reposition_after_resize(self, old_rect: Rect) -> bool:
        """Keep the circle centered and fully inside a screen after resizing."""
        screens = screen_areas()
        size = Size(self.width(), self.height())
        if self._settings.x is None or self._settings.y is None:
            area = screen_by_name(primary_screen_name(), screens)
            if area is None and screens:
                area = screens[0]
            if area is not None:
                x, y = default_position(size, area, SCREEN_MARGIN)
                self.move(x, y)
            # 默认位置模式不写入坐标，继续跟随右下角。
            return False
        x, y, screen_name = position_after_resize(old_rect, size, screens)
        self.move(x, y)
        self._settings = replace(
            self._settings, x=x, y=y, screen=screen_name
        )
        return True

    # -------------------------------------------------------------- display
    def show_widget(self) -> None:
        """Show the widget at its saved (or default) position."""
        x, y = resolve_position(
            self._settings.x,
            self._settings.y,
            self._settings.screen,
            Size(self.width(), self.height()),
            screen_areas(),
            primary_screen_name(),
            SCREEN_MARGIN,
        )
        self.move(x, y)
        self.show()
        self.raise_()

    def reset_position(self) -> None:
        """Forget the saved coordinates and go back to the default corner."""
        self._settings = replace(self._settings, x=None, y=None, screen=None)
        screens = screen_areas()
        area = screen_by_name(primary_screen_name(), screens)
        if area is None and screens:
            area = screens[0]
        if area is not None:
            x, y = default_position(
                Size(self.width(), self.height()), area, SCREEN_MARGIN
            )
            self.move(x, y)
        self._persist(self._settings)
        self._emit(f"position {self.x()} {self.y()}")

    def _apply_opacity(self) -> None:
        value = (
            self._settings.active_opacity
            if self._hovered
            else self._settings.idle_opacity
        )
        self.setWindowOpacity(max(0.05, min(1.0, float(value))))

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margin = max(2, self.width() // 24)
        box = self.rect().adjusted(margin, margin, -margin, -margin)
        filled = self._settings.fill_background
        if filled:
            painter.setBrush(FILL_COLOR)
            painter.setPen(QPen(FILLED_RING_COLOR, max(1.0, self.width() / 48.0)))
        else:
            # 背景色关闭：圆圈只留一圈描边，中间完全透明。
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(RING_COLOR, max(1.0, self.width() / 48.0)))
        painter.drawEllipse(box)
        self._draw_text(painter, box)

    def _draw_text(self, painter: QPainter, box) -> None:
        text = self._settings.text or DEFAULT_TEXT
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(8.0, self.width() * 0.19))
        painter.setFont(font)
        if not self._settings.fill_background:
            # 透明背景下先描一圈浅色边，浅色桌面上也能看清文字。
            painter.setPen(QPen(TEXT_HALO_COLOR, max(2.0, self.width() / 30.0)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        color = FILLED_TEXT_COLOR if self._settings.fill_background else TEXT_COLOR
        painter.setPen(QPen(color))
        painter.setBrush(color)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # --------------------------------------------------------------- events
    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._menu_open:
            self._hovered = True
            self._apply_opacity()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._menu_open:
            self._hovered = False
            self._apply_opacity()
        super().leaveEvent(event)

    def _cursor_inside(self) -> bool:
        """Whether the mouse is currently over the widget's window rect."""
        try:
            return self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        except (TypeError, RuntimeError):
            return False

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt naming
        menu = QMenu(self)
        settings_action = menu.addAction("设置")
        quit_action = menu.addAction("退出")
        # 菜单弹出会抢走鼠标并触发 leaveEvent；先锁定悬停状态，菜单
        # 关闭后再根据鼠标是否仍在悬浮窗上恢复。
        self._menu_open = True
        self._hovered = True
        self._apply_opacity()
        try:
            chosen = menu.exec(event.globalPos())
        finally:
            self._menu_open = False
            self._hovered = self._cursor_inside()
            self._apply_opacity()
        if chosen is settings_action:
            # 等 QMenu.exec() 完全退出后再打开对话框，避免键鼠焦点竞争
            # 导致第一次点击没有反应。
            QTimer.singleShot(0, self._on_open_settings)
        elif chosen is quit_action:
            # “退出”关闭 gp 插件本身（helper 退出），QuickTools 继续运行。
            self._emit(EVENT_CLOSED)
            self._on_exit()
            self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and shift
            and not self._dragging
        ):
            self._dragging = True
            # 固定按下时的全局偏移。移动过程中不再用局部坐标，避免窗口
            # 自身移动导致反馈抖动。
            self._drag_offset = (
                event.globalPosition().toPoint() - self.pos()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_offset = None
            self._finish_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # 隐藏时取消半途的拖动，不保存中间位置。
        self._dragging = False
        self._drag_offset = None
        super().hideEvent(event)

    def _finish_drag(self) -> None:
        """Clamp the widget on screen, persist the position and report it."""
        rect = rect_for(self)
        area = screen_for_rect(rect, screen_areas())
        if area is not None:
            x, y = clamp_into(rect, area)
            if (x, y) != (self.x(), self.y()):
                self.move(x, y)
            self._settings = replace(
                self._settings, x=x, y=y, screen=area.name or None
            )
        else:
            self._settings = replace(
                self._settings, x=self.x(), y=self.y(), screen=None
            )
        self._persist(self._settings)
        self._emit(f"position {self.x()} {self.y()}")
