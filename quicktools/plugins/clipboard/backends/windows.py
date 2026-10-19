"""Native Windows clipboard backend implemented with ctypes.

Monitoring uses ``AddClipboardFormatListener`` on a message-only window, so it
does not poll. No pywin32 dependency is required.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from typing import Sequence

from ..models import BackendStatus, ClipboardContent, ClipboardError, ClipboardKind
from .base import BaseBackend
from .win_formats import dib_to_png, encode_hdrop, png_to_dib

log = logging.getLogger(__name__)

CF_TEXT = 1
CF_OEMTEXT = 7
CF_DIB = 8
CF_UNICODETEXT = 13
CF_HDROP = 15
CF_DIBV5 = 17

GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_CLIPBOARDUPDATE = 0x031D
HWND_MESSAGE = ctypes.c_void_p(-3)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_CLASS_ALREADY_EXISTS = 1410


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", _POINT),
        ("lPrivate", ctypes.c_uint),
    ]


if sys.platform == "win32":
    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    )
else:  # Allows importing this module for pure tests on Linux.
    _WNDPROC = ctypes.CFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    )


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]


class _ClipboardData:
    def __init__(self) -> None:
        self.text: str | None = None
        self.image_png: bytes | None = None
        self.files: list[str] | None = None
        self.source: str | None = None


class WindowsBackend(BaseBackend):
    name = "windows"

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: str | None = None
        self._hwnd: int | None = None
        self._thread_id: int | None = None
        self._class_name: str | None = None
        self._wndproc = None
        self._client_running = threading.Event()
        self._last_update = 0.0
        self._user32 = None
        self._kernel32 = None
        self._shell32 = None
        if sys.platform == "win32":
            self.status = BackendStatus(True, "Windows (原生监听)")
        else:
            self.status = BackendStatus(
                False, "Windows", "当前系统不是 Windows，Windows 后端不可用。"
            )

    # ------------------------------------------------------------ lifecycle
    def start(self, on_change) -> None:
        self._on_change = on_change
        if sys.platform != "win32":
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._run, name="clipboard-win32", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(2.0):
            self.status = BackendStatus(
                False, "Windows", "Windows 剪贴板监听启动超时。"
            )
            return
        if self._start_error:
            self.status = BackendStatus(
                False, "Windows", f"Windows 剪贴板监听启动失败：{self._start_error}"
            )

    def stop(self) -> None:
        if sys.platform != "win32":
            return
        hwnd = self._hwnd
        if hwnd and self._user32 is not None:
            try:
                self._user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
            if thread.is_alive():
                log.warning("Windows 剪贴板监听线程未能及时退出")
        self._thread = None
        self._hwnd = None

    def _run(self) -> None:
        user32 = kernel32 = shell32 = None
        hwnd = None
        registered = False
        try:
            user32, kernel32, shell32 = self._load_libraries()
            self._user32, self._kernel32, self._shell32 = (
                user32,
                kernel32,
                shell32,
            )
            self._wndproc = _WNDPROC(self._window_proc)
            class_name = f"QuickToolsClipboard_{os.getpid()}_{id(self)}"
            instance = kernel32.GetModuleHandleW(None)
            window_class = _WNDCLASSW()
            window_class.style = 0
            window_class.lpfnWndProc = self._wndproc
            window_class.cbClsExtra = 0
            window_class.cbWndExtra = 0
            window_class.hInstance = instance
            window_class.hIcon = None
            window_class.hCursor = None
            window_class.hbrBackground = None
            window_class.lpszMenuName = None
            window_class.lpszClassName = class_name
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                error = ctypes.get_last_error()
                if error != ERROR_CLASS_ALREADY_EXISTS:
                    raise ClipboardError(f"RegisterClassW 失败 ({error})")
            registered = True
            hwnd = user32.CreateWindowExW(
                0,
                class_name,
                "QuickTools Clipboard Listener",
                0,
                0,
                0,
                0,
                0,
                HWND_MESSAGE,
                None,
                instance,
                None,
            )
            if not hwnd:
                raise ClipboardError(
                    f"CreateWindowExW 失败 ({ctypes.get_last_error()})"
                )
            self._hwnd = int(hwnd)
            self._thread_id = kernel32.GetCurrentThreadId()
            self._class_name = class_name
            if not user32.AddClipboardFormatListener(hwnd):
                raise ClipboardError(
                    f"AddClipboardFormatListener 失败 ({ctypes.get_last_error()})"
                )
            self.status = BackendStatus(True, "Windows (原生监听)")
            self._client_running.set()
        except Exception as exc:
            self._start_error = str(exc) or exc.__class__.__name__
            log.exception("初始化 Windows 剪贴板监听失败")
            if user32 is not None and hwnd:
                try:
                    user32.DestroyWindow(hwnd)
                except Exception:
                    pass
            if user32 is not None and registered and self._class_name:
                try:
                    user32.UnregisterClassW(self._class_name, instance)
                except Exception:
                    pass
            self._ready.set()
            return

        self._ready.set()
        message = _MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self._client_running.clear()
            try:
                user32.RemoveClipboardFormatListener(hwnd)
            except Exception:
                pass
            try:
                user32.DestroyWindow(hwnd)
            except Exception:
                pass
            if registered and self._class_name:
                try:
                    user32.UnregisterClassW(self._class_name, instance)
                except Exception:
                    pass
            self._hwnd = None

    @staticmethod
    def _load_libraries():
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        user32.RegisterClassW.restype = ctypes.c_ushort
        user32.UnregisterClassW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        user32.UnregisterClassW.restype = ctypes.c_int
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DefWindowProcW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.AddClipboardFormatListener.argtypes = [ctypes.c_void_p]
        user32.AddClipboardFormatListener.restype = ctypes.c_int
        user32.RemoveClipboardFormatListener.argtypes = [ctypes.c_void_p]
        user32.RemoveClipboardFormatListener.restype = ctypes.c_int
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(_MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.PostMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_int
        user32.CloseClipboard.restype = ctypes.c_int
        user32.EmptyClipboard.restype = ctypes.c_int
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
        user32.IsClipboardFormatAvailable.restype = ctypes.c_int
        user32.GetClipboardOwner.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_int
        kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        shell32.DragQueryFileW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_uint,
        ]
        shell32.DragQueryFileW.restype = ctypes.c_uint
        return user32, kernel32, shell32

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_CLIPBOARDUPDATE:
                self._handle_update()
                return 0
            if message in (WM_CLOSE, WM_DESTROY):
                self._user32.PostQuitMessage(0)
                return 0
            return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)
        except Exception:
            log.exception("Windows 剪贴板窗口过程异常")
            return 0

    def _handle_update(self) -> None:
        now = time.monotonic()
        if now - self._last_update < 0.08:
            return
        self._last_update = now
        # Give delayed-rendering applications a moment to publish data.
        time.sleep(0.08)
        try:
            content = self.snapshot()
        except Exception:
            log.exception("读取 Windows 剪贴板失败")
            return
        if content is not None and self._on_change is not None:
            self._on_change(content)

    # ---------------------------------------------------------------- read
    def _open_clipboard(self) -> bool:
        if self._user32 is None:
            return False
        for _ in range(6):
            if self._user32.OpenClipboard(self._hwnd):
                return True
            time.sleep(0.04)
        return False

    def _close_clipboard(self) -> None:
        if self._user32 is not None:
            try:
                self._user32.CloseClipboard()
            except Exception:
                pass

    def _available(self, *formats: int) -> bool:
        if self._user32 is None:
            return False
        return any(
            self._user32.IsClipboardFormatAvailable(fmt) for fmt in formats
        )

    def _read_preferred(self, kind: str | None = None) -> _ClipboardData:
        data = _ClipboardData()
        if self._user32 is None:
            return data
        if not self._open_clipboard():
            raise ClipboardError("无法访问剪贴板（可能被其他程序占用）")
        try:
            if kind in (None, "files") and self._available(CF_HDROP):
                data.files = self._read_files_locked()
            if kind in (None, "image") and self._available(CF_DIBV5, CF_DIB):
                data.image_png = self._read_image_locked()
            if kind in (None, "text") and self._available(
                CF_UNICODETEXT, CF_TEXT, CF_OEMTEXT
            ):
                data.text = self._read_text_locked()
        finally:
            self._close_clipboard()
        data.source = self._source_name()
        return data

    def _read_files_locked(self) -> list[str] | None:
        handle = self._user32.GetClipboardData(CF_HDROP)
        if not handle:
            return None
        count = self._shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
        paths: list[str] = []
        for index in range(count):
            length = self._shell32.DragQueryFileW(handle, index, None, 0)
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._shell32.DragQueryFileW(handle, index, buffer, length + 1)
            paths.append(buffer.value)
        return paths or None

    def _read_image_locked(self) -> bytes | None:
        for fmt in (CF_DIBV5, CF_DIB):
            if not self._available(fmt):
                continue
            handle = self._user32.GetClipboardData(fmt)
            if not handle:
                continue
            size = self._kernel32.GlobalSize(handle)
            pointer = self._kernel32.GlobalLock(handle)
            if not pointer or not size:
                if pointer:
                    self._kernel32.GlobalUnlock(handle)
                continue
            try:
                raw = ctypes.string_at(pointer, size)
            finally:
                self._kernel32.GlobalUnlock(handle)
            try:
                return dib_to_png(raw)
            except Exception:
                log.debug("无法转换 CF_%s 图片", fmt, exc_info=True)
        return None

    def _read_text_locked(self) -> str | None:
        if self._available(CF_UNICODETEXT):
            handle = self._user32.GetClipboardData(CF_UNICODETEXT)
            if handle:
                pointer = self._kernel32.GlobalLock(handle)
                if pointer:
                    try:
                        text = ctypes.wstring_at(pointer)
                    finally:
                        self._kernel32.GlobalUnlock(handle)
                    return text.rstrip("\x00") or None
        if self._available(CF_TEXT, CF_OEMTEXT):
            fmt = CF_TEXT if self._available(CF_TEXT) else CF_OEMTEXT
            handle = self._user32.GetClipboardData(fmt)
            if handle:
                pointer = self._kernel32.GlobalLock(handle)
                if pointer:
                    try:
                        raw = ctypes.string_at(pointer)
                    finally:
                        self._kernel32.GlobalUnlock(handle)
                    encoding = "mbcs" if sys.platform == "win32" else "latin-1"
                    try:
                        return raw.decode(encoding, "replace").rstrip("\x00") or None
                    except LookupError:
                        return raw.decode("latin-1", "replace").rstrip("\x00") or None
        return None

    def _source_name(self) -> str | None:
        if self._user32 is None or self._kernel32 is None:
            return None
        try:
            owner = self._user32.GetClipboardOwner()
            if not owner:
                return None
            pid = ctypes.c_ulong()
            self._user32.GetWindowThreadProcessId(owner, ctypes.byref(pid))
            if not pid.value:
                return None
            process = self._kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
            )
            if not process:
                return None
            try:
                buffer = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_ulong(len(buffer))
                if self._kernel32.QueryFullProcessImageNameW(
                    process, 0, buffer, ctypes.byref(size)
                ):
                    return os.path.basename(buffer.value)
            finally:
                self._kernel32.CloseHandle(process)
        except Exception:
            log.debug("无法获取 Windows 剪贴板来源", exc_info=True)
        return None

    def read_text(self) -> str | None:
        try:
            return self._read_preferred("text").text
        except Exception:
            log.debug("Windows 读取文本失败", exc_info=True)
            return None

    def read_image(self) -> bytes | None:
        try:
            return self._read_preferred("image").image_png
        except Exception:
            log.debug("Windows 读取图片失败", exc_info=True)
            return None

    def read_files(self) -> list[str] | None:
        try:
            return self._read_preferred("files").files
        except Exception:
            log.debug("Windows 读取文件列表失败", exc_info=True)
            return None

    def snapshot(self) -> ClipboardContent | None:
        data = self._read_preferred()
        if data.files:
            return ClipboardContent(
                kind=ClipboardKind.FILES,
                paths=tuple(data.files),
                source=data.source,
            )
        if data.image_png:
            return ClipboardContent(
                kind=ClipboardKind.IMAGE,
                image_png=data.image_png,
                source=data.source,
            )
        if data.text and data.text.strip():
            return ClipboardContent(
                kind=ClipboardKind.TEXT,
                text=data.text,
                source=data.source,
            )
        return None

    # --------------------------------------------------------------- write
    def _with_clipboard(self, callback) -> None:
        if self._user32 is None or self._kernel32 is None:
            raise ClipboardError("Windows 剪贴板后端尚未启动")
        if not self._open_clipboard():
            raise ClipboardError("无法写入剪贴板（可能被其他程序占用）")
        try:
            if not self._user32.EmptyClipboard():
                raise ClipboardError(
                    f"清空剪贴板失败 ({ctypes.get_last_error()})"
                )
            callback()
        finally:
            self._close_clipboard()

    def _set_data(self, fmt: int, payload: bytes) -> None:
        handle = self._kernel32.GlobalAlloc(
            GMEM_MOVEABLE | GMEM_ZEROINIT, len(payload)
        )
        if not handle:
            raise ClipboardError(
                f"分配剪贴板内存失败 ({ctypes.get_last_error()})"
            )
        pointer = self._kernel32.GlobalLock(handle)
        if not pointer:
            self._kernel32.GlobalFree(handle)
            raise ClipboardError("锁定剪贴板内存失败")
        try:
            ctypes.memmove(pointer, payload, len(payload))
        finally:
            self._kernel32.GlobalUnlock(handle)
        if not self._user32.SetClipboardData(fmt, handle):
            self._kernel32.GlobalFree(handle)
            raise ClipboardError(
                f"SetClipboardData 失败 ({ctypes.get_last_error()})"
            )

    def write_text(self, text: str) -> None:
        payload = text.encode("utf-16le") + b"\x00\x00"

        def write() -> None:
            self._set_data(CF_UNICODETEXT, payload)

        self._with_clipboard(write)

    def write_image(self, png: bytes) -> None:
        dib = png_to_dib(png)

        def write() -> None:
            self._set_data(CF_DIB, dib)

        self._with_clipboard(write)

    def write_files(self, paths: Sequence[str]) -> None:
        payload = encode_hdrop(paths)

        def write() -> None:
            self._set_data(CF_HDROP, payload)

        self._with_clipboard(write)
