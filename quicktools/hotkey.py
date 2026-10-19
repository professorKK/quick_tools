"""Global hotkey registration with pynput."""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable

from .config import HotkeySpec

log = logging.getLogger(__name__)

_MOD_COMBO = {
    "ctrl": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "super": "<cmd>",
}
_SPECIAL_COMBO = {
    "space": "<space>",
    "tab": "<tab>",
    "enter": "<enter>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    "insert": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "pageup": "<page_up>",
    "pagedown": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
}


def is_wayland_session() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland":
        return True
    # XWayland leaves DISPLAY set, but a Wayland session still cannot use the
    # X11 global listener reliably. Prefer the explicit X11 signal.
    return bool(os.environ.get("WAYLAND_DISPLAY")) and session != "x11"


def to_pynput_combo(spec: HotkeySpec) -> str:
    """Convert a HotkeySpec to the syntax accepted by pynput."""
    parts = [_MOD_COMBO[modifier] for modifier in spec.modifiers]
    key = spec.key
    if key in _SPECIAL_COMBO:
        parts.append(_SPECIAL_COMBO[key])
    elif len(key) == 1:
        parts.append(key)
    elif key.startswith("f") and key[1:].isdigit():
        parts.append(f"<{key}>")
    else:
        raise ValueError(f"无法转换快捷键主键：{key}")
    return "+".join(parts)


class HotkeyManager:
    """Owns the pynput listener and keeps Tk calls out of its thread.

    The callback is invoked from pynput's listener thread and must itself be
    thread-safe (QuickTools uses it only to enqueue a Tk command).
    """

    def __init__(self, spec: HotkeySpec, callback: Callable[[], None]) -> None:
        self._spec = spec
        self._callback = callback
        self._listener = None
        self.error = ""
        self.available = False

    @property
    def spec(self) -> HotkeySpec:
        return self._spec

    @property
    def running(self) -> bool:
        return self._listener is not None

    def _fire(self) -> None:
        try:
            self._callback()
        except Exception:
            log.exception("全局快捷键回调失败")

    def _start_listener(self, spec: HotkeySpec) -> None:
        self._stop_listener()
        if is_wayland_session():
            raise RuntimeError(
                "当前 Wayland 会话不支持应用内全局热键；"
                "请将系统快捷键绑定到 quicktools --toggle"
            )
        from pynput import keyboard  # imported lazily so --help works headless

        combo = to_pynput_combo(spec)
        listener = keyboard.GlobalHotKeys({combo: self._fire})
        listener.daemon = True
        listener.start()
        self._listener = listener
        self.available = True
        self.error = ""
        log.info("全局快捷键已注册：%s (%s)", spec.display(), combo)

    def _stop_listener(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                log.debug("停止快捷键监听失败", exc_info=True)
            join = getattr(listener, "join", None)
            if callable(join):
                try:
                    join(timeout=0.5)
                except Exception:
                    pass

    def start(self, spec: HotkeySpec | None = None) -> bool:
        target = spec or self._spec
        try:
            self._start_listener(target)
            self._spec = target
            return True
        except Exception as exc:
            self._stop_listener()
            self.available = False
            self.error = str(exc)
            log.warning("全局快捷键启动失败：%s", exc)
            return False

    def stop(self) -> None:
        self._stop_listener()
        self.available = False

    def suspend(self) -> None:
        self._stop_listener()
        self.available = False

    def resume(self) -> bool:
        return self.start(self._spec)

    def change(self, new_spec: HotkeySpec) -> tuple[bool, str]:
        old_spec = self._spec
        previous_error = self.error
        ok = self.start(new_spec)
        if ok:
            return True, ""
        error = self.error
        # A failed rebind must never leave the user without the old shortcut.
        if self.start(old_spec):
            self.error = error
        else:
            self.error = error or previous_error
        return False, error

    def status_text(self) -> str:
        if self.running:
            return f"全局快捷键 {self._spec.display()} 已启用"
        if is_wayland_session():
            return (
                "Wayland 会话无法应用内监听全局热键。请在系统设置中把快捷键"
                "绑定到 `quicktools --toggle`，或切换到 X11。"
            )
        if self.error:
            return f"全局快捷键未启用：{self.error}"
        return "全局快捷键未启用（仍可用启动器设置或 --toggle 唤出）"
