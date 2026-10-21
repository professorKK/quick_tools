"""Native Windows global hotkeys based on ``RegisterHotKey``.

Why not pynput on Windows: a low-level keyboard hook only observes input.
The thread that runs the hook callback does not own the foreground input
queue, so a window shown from it (or from the Tk thread it forwards to)
cannot call ``SetForegroundWindow``. ``RegisterHotKey`` instead delivers
``WM_HOTKEY`` to the registering thread, which Windows treats as the thread
that received the user's input; that thread may bring its own window to the
foreground. This is the same mechanism uTools/Electron/PowerToys-style
launchers use.

The hidden window is created on the calling thread (QuickTools creates it on
the Tk main thread), so Tk's own message loop dispatches ``WM_HOTKEY`` to
:meth:`Win32Hotkey._on_message`. The callback therefore runs on the Tk main
thread and may enqueue a command directly.
"""

from __future__ import annotations

import ctypes
import itertools
import sys
import threading
from ctypes import wintypes
from typing import Callable

from .config import HotkeySpec
from .logging_setup import get_logger

log = get_logger(__name__)

_WM_HOTKEY = 0x0312
_WM_DESTROY = 0x0002
_HWND_MESSAGE = -3
_HOTKEY_ID = 1

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000

_MODIFIERS = {
    "ctrl": _MOD_CONTROL,
    "alt": _MOD_ALT,
    "shift": _MOD_SHIFT,
    "super": _MOD_WIN,
}

_SPECIAL_VK = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT,
    wintypes.HWND,
    ctypes.c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def to_win32_combo(spec: HotkeySpec) -> tuple[int, int]:
    """Return ``(modifiers, virtual_key)`` for ``RegisterHotKey``."""
    modifiers = 0
    for name in spec.modifiers:
        modifiers |= _MODIFIERS[name]
    key = spec.key
    if key in _SPECIAL_VK:
        vk = _SPECIAL_VK[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit():
        number = int(key[1:])
        if not 1 <= number <= 20:
            raise ValueError(f"不支持的快捷键主键：{spec.key}")
        vk = 0x70 + number - 1
    else:
        raise ValueError(f"不支持的快捷键主键：{spec.key}")
    return modifiers, vk


def _user32():
    if sys.platform != "win32":
        raise RuntimeError("Win32 全局热键仅支持 Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        ctypes.c_uint,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = _LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    return user32


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    return kernel32


class Win32Hotkey:
    """One registered hotkey backed by a hidden message-only window."""

    _ids = itertools.count(1)

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._user32 = _user32()
        self._kernel32 = _kernel32()
        self._wndproc = _WNDPROC(self._on_message)
        self._class_name = f"QuickToolsHotkey_{next(self._ids)}"
        self._instance = None
        self._hwnd: int | None = None
        self._atom = 0
        self._registered = False

    @property
    def running(self) -> bool:
        return self._registered

    def _create_window(self) -> None:
        instance = self._kernel32.GetModuleHandleW(None)
        self._instance = instance
        window_class = _WNDCLASSW()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.lpszClassName = self._class_name
        atom = self._user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            error = ctypes.get_last_error()
            raise OSError(error, f"注册热键窗口类失败（错误 {error}）")
        self._atom = int(atom)
        hwnd = self._user32.CreateWindowExW(
            0,
            self._class_name,
            "",
            0,
            0,
            0,
            0,
            0,
            wintypes.HWND(_HWND_MESSAGE),
            None,
            instance,
            None,
        )
        if not hwnd:
            error = ctypes.get_last_error()
            self._destroy_class()
            raise OSError(error, f"创建热键消息窗口失败（错误 {error}）")
        self._hwnd = int(hwnd)

    def _destroy_class(self) -> None:
        if self._atom:
            self._user32.UnregisterClassW(self._class_name, self._instance)
            self._atom = 0

    def start(self, spec: HotkeySpec) -> None:
        """Register ``spec``. Call on the thread that runs the GUI loop."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Win32 全局热键只能在主线程注册")
        if sys.platform != "win32":
            raise RuntimeError("Win32 全局热键仅支持 Windows")
        if self._registered:
            self.stop()
        if self._hwnd is None:
            self._create_window()
        modifiers, vk = to_win32_combo(spec)
        if not self._user32.RegisterHotKey(
            wintypes.HWND(self._hwnd),
            _HOTKEY_ID,
            modifiers | _MOD_NOREPEAT,
            vk,
        ):
            error = ctypes.get_last_error()
            raise OSError(
                error,
                f"无法注册全局快捷键 {spec.display()}（错误 {error}）",
            )
        self._registered = True

    def stop(self) -> None:
        if self._registered and self._hwnd is not None:
            self._user32.UnregisterHotKey(wintypes.HWND(self._hwnd), _HOTKEY_ID)
        self._registered = False

    def close(self) -> None:
        self.stop()
        if self._hwnd is not None:
            self._user32.DestroyWindow(wintypes.HWND(self._hwnd))
            self._hwnd = None
        self._destroy_class()

    def _on_message(self, hwnd, message, wparam, lparam):
        if message == _WM_HOTKEY:
            try:
                self._callback()
            except Exception:
                log.exception("全局快捷键回调失败")
            return 0
        if message == _WM_DESTROY:
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)
