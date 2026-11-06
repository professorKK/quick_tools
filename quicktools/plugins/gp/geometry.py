"""悬浮窗的纯几何计算。

这个模块**不导入 Qt**，所有函数只接受普通数据类，方便在没有显示环境时用
假屏幕做回归测试。Qt 侧的 ``qt_screens.py`` 负责把 ``QScreen`` / ``QRect``
转换成这里的结构。

坐标系与 Qt 一致：全局设备无关像素，``right`` / ``bottom`` 为右开、下开边界。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# 悬浮窗与屏幕边缘的默认间距。
SCREEN_MARGIN = 20
# 设置对话框与悬浮窗之间的间距，以及对话框与屏幕边缘的最小间距。
DIALOG_GAP = 12
DIALOG_MARGIN = 8
# 对话框底部留出更多空间：悬浮窗默认在右下角时，设置框不再贴着屏幕底边。
DIALOG_BOTTOM_MARGIN = 56


@dataclass(frozen=True)
class ScreenArea:
    """一块显示器的可用区域（已排除任务栏/面板）。"""

    name: str
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass(frozen=True)
class Size:
    width: int
    height: int


def screen_by_name(
    name: str | None, screens: Sequence[ScreenArea]
) -> ScreenArea | None:
    """Return the screen with this exact name, or None."""
    if not name:
        return None
    for screen in screens:
        if screen.name == name:
            return screen
    return None


def _intersection_area(rect: Rect, area: ScreenArea) -> int:
    left = max(rect.x, area.x)
    top = max(rect.y, area.y)
    right = min(rect.right, area.right)
    bottom = min(rect.bottom, area.bottom)
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def _distance_squared(rect: Rect, area: ScreenArea) -> int:
    dx = rect.center_x - area.center_x
    dy = rect.center_y - area.center_y
    return dx * dx + dy * dy


def screen_for_rect(
    rect: Rect, screens: Sequence[ScreenArea]
) -> ScreenArea | None:
    """Pick the screen that owns a rectangle.

    The screen with the largest overlap wins. When the rectangle sits in a gap
    between displays (no overlap at all), the display whose center is closest
    is used so the window can always be brought back into view.
    """
    if not screens:
        return None
    best: ScreenArea | None = None
    best_overlap = 0
    for screen in screens:
        overlap = _intersection_area(rect, screen)
        if overlap > best_overlap:
            best = screen
            best_overlap = overlap
    if best is not None:
        return best
    return min(screens, key=lambda screen: _distance_squared(rect, screen))


def clamp_into(rect: Rect, area: ScreenArea) -> tuple[int, int]:
    """Clamp a rectangle fully into a screen's available area.

    A rectangle larger than the screen is anchored at the screen's top-left so
    at least its top-left corner stays reachable.
    """
    max_x = max(area.x, area.right - rect.width)
    max_y = max(area.y, area.bottom - rect.height)
    x = min(max(rect.x, area.x), max_x)
    y = min(max(rect.y, area.y), max_y)
    return x, y


def default_position(
    size: Size, area: ScreenArea, margin: int = SCREEN_MARGIN
) -> tuple[int, int]:
    """Bottom-right corner of a screen, leaving a margin."""
    return (
        area.right - margin - size.width,
        area.bottom - margin - size.height,
    )


def resolve_position(
    saved_x: int | None,
    saved_y: int | None,
    saved_screen: str | None,
    size: Size,
    screens: Sequence[ScreenArea],
    primary_name: str | None = None,
    margin: int = SCREEN_MARGIN,
) -> tuple[int, int]:
    """Resolve the position to display at, without changing saved settings.

    Rules:
    - No saved position: bottom-right of the primary screen.
    - Saved screen still exists: use it and clamp the saved coordinates into
      that screen (the desktop layout may have changed).
    - Saved screen is gone: fall back to the screen with the largest overlap,
      then the nearest screen. The saved values are deliberately left intact so
      reconnecting the display restores the original position.
    """
    if not screens:
        return (saved_x or 0, saved_y or 0)
    if saved_x is None or saved_y is None:
        area = screen_by_name(primary_name, screens) or screens[0]
        return default_position(size, area, margin)
    rect = Rect(saved_x, saved_y, size.width, size.height)
    area = screen_by_name(saved_screen, screens)
    if area is None:
        area = screen_for_rect(rect, screens)
    assert area is not None  # screens is non-empty
    return clamp_into(rect, area)


def position_after_resize(
    current_rect: Rect,
    new_size: Size,
    screens: Sequence[ScreenArea],
) -> tuple[int, int, str | None]:
    """Keep the widget centered while resizing, then clamp it on screen.

    Returns the new top-left and the name of the screen it was clamped into.
    """
    area = screen_for_rect(current_rect, screens)
    if area is None:
        return current_rect.x, current_rect.y, None
    candidate = Rect(
        current_rect.center_x - new_size.width // 2,
        current_rect.center_y - new_size.height // 2,
        new_size.width,
        new_size.height,
    )
    x, y = clamp_into(candidate, area)
    return x, y, area.name or None


def place_dialog(
    widget_rect: Rect,
    dialog_size: Size,
    area: ScreenArea,
    gap: int = DIALOG_GAP,
    margin: int = DIALOG_MARGIN,
    bottom_margin: int = DIALOG_BOTTOM_MARGIN,
) -> tuple[int, int]:
    """Place the settings dialog next to the widget on the same screen.

    Prefer the left side; flip to the right when the left side does not fit.
    Either way the dialog stays inside the screen's available area. Vertically
    it is centered on the widget and then clamped. The bottom edge keeps a
    larger margin so the dialog does not hug the bottom of the screen.
    """
    min_x = area.x + margin
    max_x = max(min_x, area.right - margin - dialog_size.width)
    min_y = area.y + margin
    max_y = max(min_y, area.bottom - bottom_margin - dialog_size.height)

    left_x = widget_rect.x - gap - dialog_size.width
    right_x = widget_rect.right + gap
    if left_x >= min_x:
        x = min(left_x, max_x)
    elif right_x <= max_x:
        x = max(right_x, min_x)
    else:
        x = min(max(left_x, min_x), max_x)

    y = min(
        max(widget_rect.center_y - dialog_size.height // 2, min_y),
        max_y,
    )
    return x, y
