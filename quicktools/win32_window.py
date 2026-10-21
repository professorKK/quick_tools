"""Win32 helpers for frameless QuickTools windows.

Tk's ``overrideredirect(True)`` removes the native caption on every platform,
but Windows then marks the window as a tool window: it disappears from the
taskbar, Alt+Tab and the shell's window menu. The helpers here restore normal
top-level behaviour, add Windows 11 rounded corners and expose the monitor work
area for custom maximize logic.

Every function is a safe no-op outside Windows; callers do not need to guard.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes

from .logging_setup import get_logger

log = get_logger(__name__)

_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_SYSMENU = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SW_MINIMIZE = 6
_SW_RESTORE = 9
_MONITOR_DEFAULTTONEAREST = 2
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def is_windows() -> bool:
    return sys.platform == "win32"


def hwnd(window: tk.Misc) -> int:
    """Return the top-level Win32 handle behind a Tk widget."""
    if not is_windows():
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        handle = int(window.winfo_id())
        parent = user32.GetParent(handle)
        return int(parent) if parent else handle
    except Exception:
        log.debug("读取窗口句柄失败", exc_info=True)
        return 0


def _get_long(handle: int, index: int) -> int:
    user32 = ctypes.windll.user32
    try:
        getter = user32.GetWindowLongPtrW
        getter.restype = ctypes.c_longlong
    except AttributeError:
        getter = user32.GetWindowLongW
        getter.restype = ctypes.c_long
    getter.argtypes = [wintypes.HWND, ctypes.c_int]
    return int(getter(wintypes.HWND(handle), index))


def _set_long(handle: int, index: int, value: int) -> None:
    user32 = ctypes.windll.user32
    try:
        setter = user32.SetWindowLongPtrW
        setter.restype = ctypes.c_longlong
    except AttributeError:
        setter = user32.SetWindowLongW
        setter.restype = ctypes.c_long
    setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
    setter(wintypes.HWND(handle), index, value)


def _work_area_from_handle(handle: int) -> tuple[int, int, int, int] | None:
    if not handle:
        return None
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [
            wintypes.HMONITOR,
            ctypes.POINTER(_MONITORINFO),
        ]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user32.MonitorFromWindow(
            wintypes.HWND(handle), _MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcWork
        return (
            int(rect.left),
            int(rect.top),
            int(rect.right - rect.left),
            int(rect.bottom - rect.top),
        )
    except Exception:
        log.debug("读取工作区失败", exc_info=True)
        return None


def prepare_top_level(window: tk.Misc) -> None:
    """Make a frameless window behave like a normal taskbar application.

    Must run after ``overrideredirect(True)`` and before the first map when
    possible. Clears ``WS_EX_TOOLWINDOW`` (Tk sets it for override-redirect
    windows) and forces ``WS_EX_APPWINDOW`` so the window keeps a taskbar
    button and Alt+Tab entry.
    """
    if not is_windows():
        return
    handle = hwnd(window)
    if not handle:
        return
    try:
        ex_style = _get_long(handle, _GWL_EXSTYLE)
        ex_style &= ~_WS_EX_TOOLWINDOW
        ex_style |= _WS_EX_APPWINDOW
        _set_long(handle, _GWL_EXSTYLE, ex_style)
        ctypes.windll.user32.SetWindowPos(
            wintypes.HWND(handle),
            wintypes.HWND(0),
            0,
            0,
            0,
            0,
            _SWP_NOMOVE
            | _SWP_NOSIZE
            | _SWP_NOZORDER
            | _SWP_NOACTIVATE
            | _SWP_FRAMECHANGED,
        )
    except Exception:
        log.debug("设置无边框窗口样式失败", exc_info=True)


def prepare_tool_window(window: tk.Misc) -> None:
    """Keep a borderless helper (dialog, tooltip) out of the taskbar."""
    if not is_windows():
        return
    handle = hwnd(window)
    if not handle:
        return
    try:
        ex_style = _get_long(handle, _GWL_EXSTYLE)
        ex_style |= _WS_EX_TOOLWINDOW
        ex_style &= ~_WS_EX_APPWINDOW
        _set_long(handle, _GWL_EXSTYLE, ex_style)
    except Exception:
        log.debug("设置工具窗口样式失败", exc_info=True)


def enable_rounded_corners(window: tk.Misc) -> None:
    """Ask DWM for rounded corners (Windows 11; ignored on older systems)."""
    if not is_windows():
        return
    handle = hwnd(window)
    if not handle:
        return
    try:
        preference = ctypes.c_int(_DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(handle),
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
    except Exception:
        log.debug("设置圆角失败", exc_info=True)


def minimize(window: tk.Misc) -> bool:
    """Minimize a frameless window; returns True when Windows accepted it."""
    if not is_windows():
        return False
    handle = hwnd(window)
    if not handle:
        return False
    try:
        return bool(ctypes.windll.user32.ShowWindow(wintypes.HWND(handle), _SW_MINIMIZE))
    except Exception:
        log.debug("最小化窗口失败", exc_info=True)
        return False


def restore(window: tk.Misc) -> None:
    if not is_windows():
        return
    handle = hwnd(window)
    if not handle:
        return
    try:
        ctypes.windll.user32.ShowWindow(wintypes.HWND(handle), _SW_RESTORE)
    except Exception:
        log.debug("还原窗口失败", exc_info=True)


def work_area(window: tk.Misc) -> tuple[int, int, int, int] | None:
    """Return the work area (x, y, width, height) of the window's monitor."""
    if not is_windows():
        return None
    return _work_area_from_handle(hwnd(window))
