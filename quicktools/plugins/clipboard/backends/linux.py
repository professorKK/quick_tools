"""Linux backend selection between Wayland and X11."""

from __future__ import annotations

import os

from .base import ClipboardBackend, UnavailableBackend


def is_wayland_session() -> bool:
    if (os.environ.get("XDG_SESSION_TYPE") or "").lower() == "wayland":
        return True
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def create_linux_backend() -> ClipboardBackend:
    if is_wayland_session():
        # Never silently fall back to X11 on Wayland: an X11 connection would
        # only see XWayland clients and silently miss native applications.
        from .wayland import WaylandBackend

        return WaylandBackend()
    if not os.environ.get("DISPLAY"):
        return UnavailableBackend(
            "没有检测到 X11 或 Wayland 图形会话，剪贴板监听不可用。",
            mode="监听不可用",
        )
    try:
        from .x11 import X11Backend

        return X11Backend()
    except Exception as exc:  # pragma: no cover - depends on system Xlib
        return UnavailableBackend(
            f"X11 后端初始化失败：{exc}",
            mode="监听不可用",
        )
