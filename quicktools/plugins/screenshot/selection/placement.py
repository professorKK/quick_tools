"""Place a full-monitor Tk window, including negative virtual coordinates."""

from __future__ import annotations

import ctypes
import logging
import sys
import tkinter as tk

from ..models import Rect

log = logging.getLogger(__name__)

_HWND_TOPMOST = -1
_SWP_NOACTIVATE = 0x0010


def geometry_string(rect: Rect) -> str:
    return f"{rect.width}x{rect.height}+{rect.x}+{rect.y}"


def place_overlay(window: tk.Toplevel, rect: Rect) -> None:
    """Position a monitor overlay.

    Tk's geometry syntax interprets negative offsets as distance from the
    right/bottom edge, which is wrong for monitors left of or above the
    primary display. On Windows we use SetWindowPos for that case.
    """
    if sys.platform == "win32" and (rect.x < 0 or rect.y < 0):
        try:
            window.update_idletasks()
            user32 = ctypes.windll.user32
            user32.SetWindowPos(
                ctypes.c_void_p(window.winfo_id()),
                ctypes.c_void_p(_HWND_TOPMOST),
                int(rect.x),
                int(rect.y),
                int(rect.width),
                int(rect.height),
                _SWP_NOACTIVATE,
            )
            return
        except Exception:
            log.exception("使用 Win32 定位截图覆盖层失败，回退到 Tk geometry")
    window.geometry(geometry_string(rect))
