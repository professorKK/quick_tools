"""Windows screen and window capture.

Screen pixels use Pillow's GDI-backed ImageGrab. Virtual-screen coordinates and
window rectangles are obtained through ctypes so multi-monitor origins (which
may be negative) are preserved.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from PIL import ImageGrab

from ..models import (
    CapturedImage,
    CaptureMode,
    CaptureUnavailable,
    Point,
    Rect,
    ScreenInfo,
    WindowInfo,
)
from .base import CaptureCapabilities, CaptureStatus

log = logging.getLogger(__name__)

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
SW_RESTORE = 9
INPUT_MOUSE = 0
MOUSEEVENTF_WHEEL = 0x0800


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


if sys.platform == "win32":
    _MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_RECT),
        ctypes.c_void_p,
    )
    _ENUMWINDOWSPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
    )
else:
    _MONITORENUMPROC = ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_RECT),
        ctypes.c_void_p,
    )
    _ENUMWINDOWSPROC = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
    )


class WindowsBackend:
    name = "windows"

    def __init__(self) -> None:
        if sys.platform != "win32":
            self.status = CaptureStatus(False, "Windows", "当前系统不是 Windows")
            self._user32 = None
            self._dwmapi = None
            return
        self._user32 = ctypes.windll.user32
        try:
            self._dwmapi = ctypes.windll.dwmapi
        except Exception:
            self._dwmapi = None
        self.status = CaptureStatus(True, "Windows", "GDI 抓屏")

    # ----------------------------------------------------------- protocol
    def capabilities(self) -> CaptureCapabilities:
        return CaptureCapabilities(
            custom_overlay=True,
            window_enumeration=True,
            freeform=True,
            scrolling=True,
            interactive_portal=False,
        )

    def _virtual_screen(self) -> Rect:
        assert self._user32 is not None
        x = int(self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        y = int(self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        width = int(self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        height = int(self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        return Rect(x, y, width, height)

    def screens(self) -> list[ScreenInfo]:
        if self._user32 is None:
            return []
        screens: list[ScreenInfo] = []

        def callback(hmonitor, _hdc, _rect, _data):
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if self._user32.GetMonitorInfoW(
                ctypes.c_void_p(hmonitor), ctypes.byref(info)
            ):
                rc = info.rcMonitor
                screens.append(
                    ScreenInfo(
                        name=f"显示器 {len(screens) + 1}",
                        rect=Rect(
                            int(rc.left),
                            int(rc.top),
                            int(rc.right - rc.left),
                            int(rc.bottom - rc.top),
                        ),
                        scale=1.0,
                        primary=bool(info.dwFlags & 1),
                    )
                )
            return 1

        proc = _MONITORENUMPROC(callback)
        try:
            self._user32.EnumDisplayMonitors(None, None, proc, 0)
        except Exception:
            log.debug("EnumDisplayMonitors 失败", exc_info=True)
        if not screens:
            rect = self._virtual_screen()
            screens.append(
                ScreenInfo(
                    name="显示器 1",
                    rect=rect,
                    scale=1.0,
                    primary=True,
                )
            )
        return screens

    def cursor_position(self) -> Point | None:
        if self._user32 is None:
            return None
        point = _POINT()
        if self._user32.GetCursorPos(ctypes.byref(point)):
            return Point(int(point.x), int(point.y))
        return None

    def grab_screen(self) -> CapturedImage:
        if self._user32 is None:
            raise CaptureUnavailable("当前系统不是 Windows")
        try:
            image = ImageGrab.grab(all_screens=True).convert("RGB")
        except Exception as exc:
            raise CaptureUnavailable(f"Windows 抓屏失败：{exc}") from exc
        origin = self._virtual_screen()
        return CapturedImage(
            image=image,
            origin=Point(origin.x, origin.y),
            scale=1.0,
            backend=self.name,
        )

    def _window_rect(self, hwnd: int) -> Rect | None:
        if self._user32 is None:
            return None
        if self._dwmapi is not None:
            rect = _RECT()
            result = self._dwmapi.DwmGetWindowAttribute(
                ctypes.c_void_p(hwnd),
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if result == 0:
                return Rect(
                    int(rect.left),
                    int(rect.top),
                    int(rect.right - rect.left),
                    int(rect.bottom - rect.top),
                )
        rect = _RECT()
        if self._user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            return Rect(
                int(rect.left),
                int(rect.top),
                int(rect.right - rect.left),
                int(rect.bottom - rect.top),
            )
        return None

    def _is_cloaked(self, hwnd: int) -> bool:
        if self._dwmapi is None:
            return False
        cloaked = ctypes.c_int(0)
        result = self._dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(hwnd),
            DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return result == 0 and bool(cloaked.value)

    def list_windows(self) -> list[WindowInfo]:
        if self._user32 is None:
            return []
        windows: list[WindowInfo] = []

        def callback(hwnd, _data):
            try:
                if not self._user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                    return 1
                if self._user32.IsIconic(ctypes.c_void_p(hwnd)):
                    return 1
                exstyle = int(
                    self._user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
                )
                if exstyle & WS_EX_TOOLWINDOW:
                    return 1
                if self._is_cloaked(hwnd):
                    return 1
                length = int(
                    self._user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
                )
                if length <= 0:
                    return 1
                buffer = ctypes.create_unicode_buffer(length + 1)
                self._user32.GetWindowTextW(
                    ctypes.c_void_p(hwnd), buffer, length + 1
                )
                title = buffer.value.strip()
                if not title:
                    return 1
                rect = self._window_rect(hwnd)
                if rect is None or rect.width <= 1 or rect.height <= 1:
                    return 1
                index = len(windows)
                windows.append(
                    WindowInfo(
                        handle=int(hwnd),
                        title=title,
                        app_name=title,
                        rect=rect,
                        z_order=-index,
                    )
                )
            except Exception:
                log.debug("跳过无法读取的 Windows 窗口", exc_info=True)
            return 1

        proc = _ENUMWINDOWSPROC(callback)
        try:
            self._user32.EnumWindows(proc, 0)
        except Exception:
            log.debug("EnumWindows 失败", exc_info=True)
        return windows

    def capture_interactive(self, mode: CaptureMode) -> CapturedImage:
        raise CaptureUnavailable("Windows 使用截图插件的自定义选区覆盖层")

    def raise_window(self, handle: int) -> bool:
        if self._user32 is None:
            return False
        try:
            hwnd = ctypes.c_void_p(int(handle))
            self._user32.ShowWindow(hwnd, SW_RESTORE)
            self._user32.BringWindowToTop(hwnd)
            self._user32.SetForegroundWindow(hwnd)
            return True
        except Exception:
            log.debug("抬升 Windows 窗口失败：%s", handle, exc_info=True)
            return False

    def scroll_at(self, point: Point, vertical: int) -> None:
        if self._user32 is None or vertical == 0:
            return
        try:
            self._user32.SetCursorPos(int(point.x), int(point.y))
            notches = min(20, max(1, abs(int(vertical))))
            delta = 120 * notches * (1 if vertical > 0 else -1)
            event = _INPUT()
            event.type = INPUT_MOUSE
            event.u.mi.dx = 0
            event.u.mi.dy = 0
            event.u.mi.mouseData = ctypes.c_ulong(delta & 0xFFFFFFFF)
            event.u.mi.dwFlags = MOUSEEVENTF_WHEEL
            event.u.mi.time = 0
            event.u.mi.dwExtraInfo = None
            sent = self._user32.SendInput(
                1, ctypes.byref(event), ctypes.sizeof(_INPUT)
            )
            if sent != 1:
                raise CaptureUnavailable("Windows 滚轮注入失败")
        except CaptureUnavailable:
            raise
        except Exception as exc:
            raise CaptureUnavailable(f"Windows 滚轮注入失败：{exc}") from exc

    def close(self) -> None:
        pass
