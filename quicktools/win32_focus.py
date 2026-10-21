"""Force a Tk window to the foreground on Windows.

``focus_force()`` only reaches ``SetForegroundWindow``. Windows refuses that
call for a process that does not own the foreground input queue (a background
QuickTools instance woken by a global hotkey or ``--toggle``), so the launcher
would appear without focus until the user clicked it.

There are two ways to obtain the right to activate a window:

* receive ``WM_HOTKEY`` on the GUI thread (the native hotkey backend in
  :mod:`quicktools.win32_hotkey` does this), or
* temporarily attach this thread's input queue to the current foreground
  thread before calling ``SetForegroundWindow`` (the fallback below).

``SetForegroundWindow`` is asynchronous when the target thread belongs to a
different input queue. We nudge the window with ``WM_NULL`` and only report
success after checking ``GetForegroundWindow`` again.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes

from .logging_setup import get_logger

log = get_logger(__name__)

_SW_SHOW = 5
_WM_NULL = 0x0000
_SMTO_ABORTIFHUNG = 0x0002
_APP_USER_MODEL_ID = "KK.QuickTools.Desktop"


def _api():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetActiveWindow.argtypes = [wintypes.HWND]
    user32.SetActiveWindow.restype = wintypes.HWND
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        ctypes.c_uint,
        wintypes.WPARAM,
        wintypes.LPARAM,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    return user32, kernel32


def _hwnd(window: tk.Misc) -> int:
    """Return the top-level Win32 handle behind a Tk widget."""
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    handle = int(window.winfo_id())
    parent = user32.GetParent(handle)
    return int(parent) if parent else handle


def _configure_app_id() -> None:
    """Give the process one AppUserModelID so Windows sees a single app."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _APP_USER_MODEL_ID
        )
    except Exception:
        log.debug("设置 AppUserModelID 失败", exc_info=True)


def is_foreground(window: tk.Misc) -> bool:
    """True when ``window`` is the current foreground window."""
    if sys.platform != "win32":
        return False
    try:
        user32, _kernel32 = _api()
        handle = _hwnd(window)
        if not handle:
            return False
        return int(user32.GetForegroundWindow() or 0) == handle
    except Exception:
        log.debug("读取前台窗口失败", exc_info=True)
        return False


def force_foreground(window: tk.Misc) -> bool:
    """Activate ``window`` and return True when it owns the foreground."""
    if sys.platform != "win32":
        return False
    _configure_app_id()
    user32, kernel32 = _api()
    try:
        handle = _hwnd(window)
        if not handle:
            return False
        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground == handle:
            return True

        # Attach before showing: a shown window whose thread does not own the
        # foreground queue may visibly appear as an inactive window first.
        foreground_thread = (
            user32.GetWindowThreadProcessId(wintypes.HWND(foreground), None)
            if foreground
            else 0
        )
        own_thread = kernel32.GetCurrentThreadId()
        attached = False
        if foreground_thread and foreground_thread != own_thread:
            attached = bool(
                user32.AttachThreadInput(own_thread, foreground_thread, True)
            )
        try:
            user32.ShowWindow(wintypes.HWND(handle), _SW_SHOW)
            user32.BringWindowToTop(wintypes.HWND(handle))
            if int(user32.GetForegroundWindow() or 0) != handle:
                user32.SetForegroundWindow(wintypes.HWND(handle))
                user32.BringWindowToTop(wintypes.HWND(handle))
                user32.SetActiveWindow(wintypes.HWND(handle))
                user32.SetFocus(wintypes.HWND(handle))
            # SetForegroundWindow may be asynchronous across input queues.
            # A synchronous WM_NULL makes the target process the activation
            # notification before we detach from its input queue.
            result = ctypes.c_size_t()
            user32.SendMessageTimeoutW(
                wintypes.HWND(handle),
                _WM_NULL,
                0,
                0,
                _SMTO_ABORTIFHUNG,
                100,
                ctypes.byref(result),
            )
        finally:
            if attached:
                user32.AttachThreadInput(
                    own_thread, foreground_thread, False
                )
        return int(user32.GetForegroundWindow() or 0) == handle
    except Exception:
        log.debug("Win32 前台激活失败", exc_info=True)
        return False
