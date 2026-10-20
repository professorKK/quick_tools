"""Choose the screenshot capture backend for the current platform."""

from __future__ import annotations

import logging
import os
import sys

from .base import CaptureBackend, UnavailableBackend

log = logging.getLogger(__name__)


def is_wayland_session() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland":
        return True
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def create_backend() -> CaptureBackend:
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    if not sys.platform.startswith("linux"):
        return UnavailableBackend("截图仅支持 Linux 和 Windows")
    if is_wayland_session():
        from .wayland import WaylandBackend

        return WaylandBackend()
    if not os.environ.get("DISPLAY"):
        return UnavailableBackend("没有检测到 X11 图形会话，截图不可用")
    try:
        from .x11 import X11Backend

        return X11Backend()
    except Exception as exc:
        log.exception("初始化 X11 截图后端失败")
        message = str(exc) if str(exc) else exc.__class__.__name__
        return UnavailableBackend(f"X11 截图后端初始化失败：{message}")
