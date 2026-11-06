"""平台输入模式：让 gp 悬浮窗在不按 Shift 时点击穿透。

X11 用 Shape 扩展清空输入区域，Windows 用 ``WS_EX_TRANSPARENT``；两种
方式都只改原生窗口的输入行为，**不调用 setWindowFlags()**（那会重建窗口，
导致闪烁和位置/原生句柄失效）。Wayland/XWayland 无法可靠读取全局修饰键，
回退为“始终可交互”，避免窗口永久卡在穿透状态。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from typing import Protocol

log = logging.getLogger(__name__)

# Windows 扩展样式。
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_VK_SHIFT = 0x10


class InputMode(Protocol):
    """Platform-specific way to make the floating window click-through."""

    def supported(self) -> bool: ...

    def shift_down(self) -> bool: ...

    def set_click_through(self, widget: object, enabled: bool) -> bool: ...

    def close(self) -> None: ...


def _is_wayland_session() -> bool:
    """True for native Wayland and XWayland sessions.

    XWayland keeps ``DISPLAY`` and Qt reports ``xcb``, but global modifier
    queries and X input shapes are not reliable there; treat it like Wayland
    and keep the widget interactive.
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


class UnsupportedInputMode:
    """Fallback that never applies click-through."""

    def supported(self) -> bool:
        return False

    def shift_down(self) -> bool:
        return False

    def set_click_through(self, widget: object, enabled: bool) -> bool:
        # Nothing to apply; the widget stays interactive.
        return True

    def close(self) -> None:
        pass


class X11InputMode:
    """X11 implementation using the Shape extension's input region."""

    def __init__(self) -> None:
        self._display = None
        self._x = None
        self._shape = None
        self._root = None
        self._window_id: int | None = None
        self._last_error: object | None = None
        self._unavailable = False

    def supported(self) -> bool:
        if self._unavailable:
            return False
        return self._ensure_display()

    def _ensure_display(self) -> bool:
        if self._display is not None:
            return True
        if self._unavailable:
            return False
        try:
            from Xlib import X, display
            from Xlib.ext import shape
        except Exception:
            self._unavailable = True
            log.debug("Xlib/Shape 不可用，gp 悬浮窗保持可交互", exc_info=True)
            return False
        try:
            connection = display.Display()
        except Exception:
            self._unavailable = True
            log.debug("无法连接 X11，gp 悬浮窗保持可交互", exc_info=True)
            return False
        try:
            if not connection.has_extension("SHAPE"):
                connection.close()
                self._unavailable = True
                log.info("X11 不支持 SHAPE，gp 悬浮窗保持可交互")
                return False
            connection.set_error_handler(self._on_x_error)
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            self._unavailable = True
            log.debug("初始化 X11 SHAPE 失败，gp 悬浮窗保持可交互", exc_info=True)
            return False
        self._display = connection
        self._x = X
        self._shape = shape
        self._root = connection.screen().root
        return True

    def _on_x_error(self, error, request) -> None:
        # Shape 请求没有回复，错误是异步的；记录下来供 set_click_through
        # 在 sync() 之后判断是否成功。
        self._last_error = (error, request)
        log.debug("X11 输入区域请求失败：%r", error)

    def shift_down(self) -> bool:
        if not self._ensure_display():
            return False
        try:
            return bool(
                self._root.query_pointer().mask & self._x.ShiftMask
            )
        except Exception as exc:
            raise RuntimeError("无法读取 X11 Shift 状态") from exc

    def set_click_through(self, widget: object, enabled: bool) -> bool:
        if not self._ensure_display():
            return False
        try:
            window_id = int(widget.winId())
        except Exception:
            return False
        if not window_id:
            return False
        try:
            window = self._display.create_resource_object(
                "window", window_id
            )
            self._last_error = None
            if enabled:
                # 空输入区域：所有鼠标事件穿透到下层窗口。
                window.shape_rectangles(
                    self._shape.SO.Set,
                    self._shape.SK.Input,
                    0,
                    0,
                    0,
                    [],
                )
            else:
                # 移除客户端输入区域，恢复默认的整窗矩形。
                window.shape_mask(
                    self._shape.SO.Set,
                    self._shape.SK.Input,
                    0,
                    0,
                    self._x.NONE,
                )
            self._display.sync()
        except Exception:
            log.debug("设置 X11 输入区域失败", exc_info=True)
            return False
        if self._last_error is not None:
            log.warning("X11 输入区域设置失败：%r", self._last_error)
            self._last_error = None
            return False
        if self._window_id is not None and self._window_id != window_id:
            log.warning(
                "gp 悬浮窗原生窗口 ID 已变化：%s -> %s",
                self._window_id,
                window_id,
            )
        self._window_id = window_id
        return True

    def close(self) -> None:
        connection, self._display = self._display, None
        self._root = None
        self._window_id = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            log.debug("关闭 X11 连接失败", exc_info=True)


class WindowsInputMode:
    """Windows implementation using the WS_EX_TRANSPARENT extended style."""

    def __init__(self) -> None:
        self._user32 = None
        self._get_long = None
        self._set_long = None

    def supported(self) -> bool:
        return sys.platform == "win32" and self._ensure_api()

    def _ensure_api(self) -> bool:
        if self._user32 is not None:
            return True
        if sys.platform != "win32":
            return False
        try:
            user32 = ctypes.windll.user32
            try:
                get_long = user32.GetWindowLongPtrW
                set_long = user32.SetWindowLongPtrW
                long_type = ctypes.c_longlong
            except AttributeError:
                get_long = user32.GetWindowLongW
                set_long = user32.SetWindowLongW
                long_type = ctypes.c_long
            get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
            get_long.restype = long_type
            set_long.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                long_type,
            ]
            set_long.restype = long_type
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short
        except Exception:
            log.debug("Windows 输入样式 API 不可用", exc_info=True)
            return False
        self._user32 = user32
        self._get_long = get_long
        self._set_long = set_long
        return True

    def shift_down(self) -> bool:
        if not self._ensure_api():
            return False
        return bool(self._user32.GetAsyncKeyState(_VK_SHIFT) & 0x8000)

    def set_click_through(self, widget: object, enabled: bool) -> bool:
        if not self._ensure_api():
            return False
        try:
            hwnd = int(widget.winId())
        except Exception:
            return False
        if not hwnd:
            return False
        try:
            style = int(self._get_long(hwnd, _GWL_EXSTYLE))
            if enabled:
                new_style = style | _WS_EX_TRANSPARENT
            else:
                new_style = style & ~_WS_EX_TRANSPARENT
            if new_style != style:
                self._set_long(hwnd, _GWL_EXSTYLE, new_style)
            # 读回确认；保留 WS_EX_LAYERED 等其他位。
            applied = int(self._get_long(hwnd, _GWL_EXSTYLE))
        except Exception:
            log.debug("设置 Windows 输入穿透失败", exc_info=True)
            return False
        return bool(applied & _WS_EX_TRANSPARENT) == enabled

    def close(self) -> None:
        self._user32 = None
        self._get_long = None
        self._set_long = None


def create_input_mode(
    platform_name: str | None = None,
) -> InputMode:
    """Pick the input mode for the current platform/session."""
    if platform_name is None:
        try:
            from PyQt6.QtGui import QGuiApplication

            platform_name = QGuiApplication.platformName()
        except Exception:
            platform_name = ""
    platform_name = (platform_name or "").lower()

    if sys.platform == "win32":
        return WindowsInputMode()
    if (
        sys.platform.startswith("linux")
        and platform_name == "xcb"
        and not _is_wayland_session()
        and os.environ.get("DISPLAY")
    ):
        return X11InputMode()
    return UnsupportedInputMode()
