"""Persistent application settings."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

MODIFIER_ORDER = ("ctrl", "alt", "shift", "super")
MODIFIERS = frozenset(MODIFIER_ORDER)
SPECIAL_KEYS = frozenset(
    {
        "space",
        "tab",
        "enter",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "pageup",
        "pagedown",
        "up",
        "down",
        "left",
        "right",
    }
)
_KEY_DISPLAY = {
    "space": "Space",
    "tab": "Tab",
    "enter": "Enter",
    "backspace": "Backspace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}


def is_supported_key(key: str) -> bool:
    if not isinstance(key, str) or not key:
        return False
    lower = key.lower()
    if lower in SPECIAL_KEYS:
        return True
    if len(lower) == 1 and (lower.isascii() and lower.isalnum()):
        return True
    if len(lower) >= 2 and lower[0] == "f":
        try:
            number = int(lower[1:])
        except ValueError:
            return False
        return 1 <= number <= 20
    return False


def display_key(key: str) -> str:
    lower = key.lower()
    if lower in _KEY_DISPLAY:
        return _KEY_DISPLAY[lower]
    if len(lower) >= 2 and lower[0] == "f":
        try:
            int(lower[1:])
            return lower.upper()
        except ValueError:
            pass
    return key.upper() if len(key) == 1 else key


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: tuple[str, ...] = ("ctrl",)
    key: str = "space"

    def __post_init__(self) -> None:
        normalized_mods = tuple(m for m in MODIFIER_ORDER if m in self.modifiers)
        unknown = set(self.modifiers) - MODIFIERS
        key = str(self.key).lower()
        if unknown:
            raise ValueError(f"不支持的修饰键：{', '.join(sorted(unknown))}")
        if not normalized_mods:
            raise ValueError("快捷键至少需要一个修饰键（Ctrl/Alt/Shift/Super）")
        if not is_supported_key(key):
            raise ValueError(f"不支持的快捷键主键：{self.key}")
        object.__setattr__(self, "modifiers", normalized_mods)
        object.__setattr__(self, "key", key)

    @classmethod
    def default(cls, platform: str | None = None) -> "HotkeySpec":
        """Platform default: Linux avoids the common IME Ctrl+Space chord."""
        current = sys.platform if platform is None else platform
        modifiers = ("ctrl",) if current == "win32" else ("ctrl", "alt")
        return cls(modifiers, "space")

    @classmethod
    def from_mapping(cls, data: Any) -> "HotkeySpec":
        if not isinstance(data, dict):
            raise ValueError("快捷键配置必须是对象")
        mods = data.get("modifiers")
        key = data.get("key")
        if not isinstance(mods, list) or not all(isinstance(m, str) for m in mods):
            raise ValueError("快捷键修饰键格式错误")
        if not isinstance(key, str):
            raise ValueError("快捷键主键格式错误")
        return cls(tuple(m.lower() for m in mods), key.lower())

    def to_mapping(self) -> dict[str, Any]:
        return {"modifiers": list(self.modifiers), "key": self.key}

    def display(self) -> str:
        labels = {
            "ctrl": "Ctrl",
            "alt": "Alt",
            "shift": "Shift",
            "super": "Super",
        }
        return "+".join([*(labels[m] for m in self.modifiers), display_key(self.key)])


@dataclass
class AppSettings:
    hotkey: HotkeySpec

    @classmethod
    def default(cls) -> "AppSettings":
        return cls(HotkeySpec.default())

    def to_mapping(self) -> dict[str, Any]:
        return {"version": 1, "hotkey": self.hotkey.to_mapping()}

    @classmethod
    def from_mapping(cls, data: Any) -> "AppSettings":
        if not isinstance(data, dict):
            raise ValueError("配置文件根节点必须是对象")
        return cls(HotkeySpec.from_mapping(data.get("hotkey")))


def load_settings(path: Path | None = None) -> AppSettings:
    path = path or paths.settings_file()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return AppSettings.from_mapping(data)
    except FileNotFoundError:
        return AppSettings.default()
    except Exception as exc:  # corrupted config must not prevent startup
        log.warning("读取设置失败，使用默认值：%s", exc)
        return AppSettings.default()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    path = path or paths.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_mapping(), ensure_ascii=False, indent=2) + "\n"
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
