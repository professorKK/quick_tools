"""X11 原生输入焦点辅助。

启动器和插件窗口使用 ``overrideredirect(True)`` 实现无边框。这样的窗口
不受窗口管理器管理，Tk 的 ``focus_force()`` 只会更新 Tk 内部的焦点模型，
不会真正调用 ``XSetInputFocus``：窗口收不到键盘输入，也永远收不到
``<FocusOut>``，于是“点击外部自动隐藏”和快捷键都会失效。

这里在 Tk 焦点模型之外补一次 X11 原生焦点设置，并提供前台状态查询。
Wayland 下焦点由合成器决定，Tk 通过 XWayland 无法可靠抢焦点；此时
``force_foreground()`` 返回 False，``is_foreground()`` 返回 True 以保持
旧行为（不做前台校验），避免误判后关闭自动隐藏。
"""

from __future__ import annotations

import os
import sys
import tkinter as tk

try:  # Linux 打包环境一定带 python-xlib；其他平台不应导入本模块。
    from Xlib import X, display as xdisplay
except Exception:  # pragma: no cover - 缺少依赖时退化为 no-op
    X = None
    xdisplay = None

from .logging_setup import get_logger

log = get_logger(__name__)

_display = None
_display_failed = False


def supported() -> bool:
    """True when real X11 focus can be managed from this process."""
    if sys.platform != "linux" or xdisplay is None:
        return False
    if os.environ.get("WAYLAND_DISPLAY"):
        return False
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return False
    return bool(os.environ.get("DISPLAY"))


def _get_display():
    global _display, _display_failed
    if not supported() or _display_failed:
        return None
    if _display is None:
        try:
            _display = xdisplay.Display()
        except Exception:
            _display_failed = True
            log.debug("连接 X11 显示失败，跳过原生焦点设置", exc_info=True)
            return None
    return _display


def _is_frameless(window: tk.Misc) -> bool:
    try:
        return bool(window.overrideredirect())
    except (AttributeError, tk.TclError):
        return False


def _top_level_id(display, inner_id: int) -> int:
    """Return the root child that wraps ``inner_id``.

    Tk wraps a Toplevel in an outer window once it is mapped. Key events and
    focus events for the whole toplevel are delivered to that wrapper, not to
    ``winfo_id()`` (the inner content window). Focusing the inner window works
    for keystrokes but Tk never sees the matching ``<FocusOut>``.
    """
    try:
        root_id = display.screen().root.id
        current = display.create_resource_object("window", inner_id)
        current_id = inner_id
        for _ in range(16):
            parent = current.query_tree().parent
            parent_id = getattr(parent, "id", parent)
            if not isinstance(parent_id, int) or parent_id in (0, 1):
                return current_id
            if parent_id == root_id:
                return current_id
            current = parent
            current_id = parent_id
    except Exception:
        log.debug("读取 X11 窗口层级失败", exc_info=True)
    return inner_id


def _window_id(window: tk.Misc) -> int | None:
    """Return the X window that carries input focus for ``window``."""
    try:
        if not window.winfo_viewable():
            return None
        inner_id = int(window.winfo_id())
    except (AttributeError, tk.TclError, ValueError):
        return None
    display = _get_display()
    if display is None:
        return inner_id
    return _top_level_id(display, inner_id)


def _same_window(display, focus, window_id: int, depth: int = 8) -> bool:
    """True when ``focus`` is ``window_id`` or one of its descendants."""
    focus_id = getattr(focus, "id", focus)
    if not isinstance(focus_id, int):
        return False
    if focus_id == window_id:
        return True
    try:
        current = display.create_resource_object("window", focus_id)
        for _ in range(depth):
            parent = current.query_tree().parent
            parent_id = getattr(parent, "id", parent)
            if parent_id == window_id:
                return True
            if not isinstance(parent_id, int) or parent_id in (0, 1):
                return False
            current = parent
    except Exception:
        return False
    return False


def is_foreground(window: tk.Misc) -> bool:
    """True when ``window`` (or one of its child windows) owns X input focus.

    Returns True when the platform cannot be checked, so callers keep their
    previous behaviour instead of disabling features on Wayland or because of a
    transient Xlib error.
    """
    if not supported():
        return True
    window_id = _window_id(window)
    if window_id is None:
        return False
    display = _get_display()
    if display is None:
        return True
    try:
        focus = display.get_input_focus().focus
        display.sync()
    except Exception:
        log.debug("读取 X11 输入焦点失败", exc_info=True)
        return True
    return _same_window(display, focus, window_id)


def force_foreground(window: tk.Misc) -> bool:
    """Give a frameless ``window`` the real X11 input focus.

    Call ``window.focus_force()`` first so Tk's internal focus points at the
    widget that should receive keystrokes; this function then makes the X
    server route those keystrokes to the window.

    Returns True only when the focus request was delivered and verified.
    """
    if not supported() or not _is_frameless(window):
        return False
    window_id = _window_id(window)
    if window_id is None:
        return False
    display = _get_display()
    if display is None:
        return False
    try:
        target = display.create_resource_object("window", window_id)
        target.set_input_focus(X.RevertToParent, X.CurrentTime)
        display.sync()
    except Exception:
        log.debug("设置 X11 输入焦点失败", exc_info=True)
        return False
    return is_foreground(window)


def input_focus_id() -> int | None:
    """Return the current X11 input focus window id, if it can be read."""
    if not supported():
        return None
    display = _get_display()
    if display is None:
        return None
    try:
        focus = display.get_input_focus().focus
        display.sync()
    except Exception:
        log.debug("读取 X11 输入焦点失败", exc_info=True)
        return None
    focus_id = getattr(focus, "id", focus)
    return focus_id if isinstance(focus_id, int) else None


def is_foreground_id(window_id: int) -> bool:
    """True when ``window_id`` or one of its descendants owns input focus."""
    if not supported():
        return True
    display = _get_display()
    if display is None:
        return True
    try:
        focus = display.get_input_focus().focus
        display.sync()
    except Exception:
        log.debug("读取 X11 输入焦点失败", exc_info=True)
        return True
    return _same_window(display, focus, _top_level_id(display, window_id))


def force_foreground_id(window_id: int) -> bool:
    """Give the X11 window carrying ``window_id`` real input focus.

    Used for Tk dialogs created in Tcl (``tk_messageBox`` / ``tk_getOpenFile``)
    which are not registered as Python widgets and therefore cannot be passed
    to :func:`force_foreground`.
    """
    if not supported():
        return False
    display = _get_display()
    if display is None:
        return False
    target_id = _top_level_id(display, window_id)
    try:
        target = display.create_resource_object("window", target_id)
        target.set_input_focus(X.RevertToParent, X.CurrentTime)
        display.sync()
    except Exception:
        log.debug("设置 X11 输入焦点失败", exc_info=True)
        return False
    return is_foreground_id(window_id)
