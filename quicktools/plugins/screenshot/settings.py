"""Persistent settings for the screenshot plugin."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from quicktools.config import HotkeySpec

log = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
IMAGE_FORMATS = ("png", "jpeg", "webp")


def _default_hotkey() -> HotkeySpec:
    return HotkeySpec(("ctrl", "alt"), "x")


def _xdg_pictures_dir() -> Path | None:
    env = os.environ.get("XDG_PICTURES_DIR")
    if env:
        candidate = Path(os.path.expandvars(os.path.expanduser(env)))
        if candidate:
            return candidate
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    user_dirs = base / "user-dirs.dirs"
    try:
        for line in user_dirs.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("XDG_PICTURES_DIR="):
                continue
            raw = line.split("=", 1)[1].strip().strip('"')
            value = os.path.expandvars(raw).replace("$HOME", str(Path.home()))
            return Path(value)
    except OSError:
        pass
    return None


def default_save_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("USERPROFILE", str(Path.home())))
        return base / "Pictures" / "Screenshots"
    pictures = _xdg_pictures_dir() or (Path.home() / "Pictures")
    return pictures / "Screenshots"


@dataclass
class ScreenshotSettings:
    hotkey_enabled: bool = True
    hotkey: HotkeySpec = field(default_factory=_default_hotkey)
    save_dir: str = ""
    image_format: str = "png"
    jpeg_quality: int = 92
    auto_copy: bool = False
    auto_save: bool = False
    # Kept for settings.json compatibility. The file-backed recent list never
    # auto-deletes screenshots, so these limits are no longer enforced.
    recent_limit: int = 100
    recent_max_mb: int = 500
    hide_delay_ms: int = 220
    default_color: str = "#e53935"
    default_width: int = 4
    default_font_size: int = 24
    scroll_notches: int = 3
    scroll_delay_ms: int = 250
    scroll_max_height: int = 20000
    scroll_ignore_top: int = 0
    scroll_ignore_bottom: int = 0
    window_margin_px: int = 0

    def resolved_save_dir(self) -> Path:
        raw = (self.save_dir or "").strip()
        return Path(os.path.expanduser(raw)) if raw else default_save_dir()

    def normalized(self) -> "ScreenshotSettings":
        image_format = (
            self.image_format.lower()
            if self.image_format.lower() in IMAGE_FORMATS
            else "png"
        )
        return replace(
            self,
            hotkey_enabled=bool(self.hotkey_enabled),
            image_format=image_format,
            jpeg_quality=max(50, min(100, int(self.jpeg_quality))),
            auto_copy=bool(self.auto_copy),
            auto_save=bool(self.auto_save),
            recent_limit=max(10, min(5000, int(self.recent_limit))),
            recent_max_mb=max(50, min(5000, int(self.recent_max_mb))),
            hide_delay_ms=max(50, min(2000, int(self.hide_delay_ms))),
            default_width=max(1, min(50, int(self.default_width))),
            default_font_size=max(8, min(200, int(self.default_font_size))),
            scroll_notches=max(1, min(20, int(self.scroll_notches))),
            scroll_delay_ms=max(50, min(3000, int(self.scroll_delay_ms))),
            scroll_max_height=max(1000, min(100000, int(self.scroll_max_height))),
            scroll_ignore_top=max(0, int(self.scroll_ignore_top)),
            scroll_ignore_bottom=max(0, int(self.scroll_ignore_bottom)),
            window_margin_px=max(0, min(500, int(self.window_margin_px))),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "version": 1,
            "hotkey_enabled": self.hotkey_enabled,
            "hotkey": self.hotkey.to_mapping(),
            "save_dir": self.save_dir,
            "image_format": self.image_format,
            "jpeg_quality": self.jpeg_quality,
            "auto_copy": self.auto_copy,
            "auto_save": self.auto_save,
            "recent_limit": self.recent_limit,
            "recent_max_mb": self.recent_max_mb,
            "hide_delay_ms": self.hide_delay_ms,
            "default_color": self.default_color,
            "default_width": self.default_width,
            "default_font_size": self.default_font_size,
            "scroll_notches": self.scroll_notches,
            "scroll_delay_ms": self.scroll_delay_ms,
            "scroll_max_height": self.scroll_max_height,
            "scroll_ignore_top": self.scroll_ignore_top,
            "scroll_ignore_bottom": self.scroll_ignore_bottom,
            "window_margin_px": self.window_margin_px,
        }

    @classmethod
    def from_mapping(cls, data: Any) -> "ScreenshotSettings":
        if not isinstance(data, dict):
            raise ValueError("截图设置根节点必须是对象")
        defaults = cls()
        try:
            hotkey = HotkeySpec.from_mapping(data.get("hotkey"))
        except Exception:
            hotkey = defaults.hotkey
        return cls(
            hotkey_enabled=_bool(data.get("hotkey_enabled"), True),
            hotkey=hotkey,
            save_dir=str(data.get("save_dir") or ""),
            image_format=str(data.get("image_format") or "png"),
            jpeg_quality=_int(data.get("jpeg_quality"), 92),
            auto_copy=_bool(data.get("auto_copy"), False),
            auto_save=_bool(data.get("auto_save"), False),
            recent_limit=_int(data.get("recent_limit"), 100),
            recent_max_mb=_int(data.get("recent_max_mb"), 500),
            hide_delay_ms=_int(data.get("hide_delay_ms"), 220),
            default_color=str(data.get("default_color") or "#e53935"),
            default_width=_int(data.get("default_width"), 4),
            default_font_size=_int(data.get("default_font_size"), 24),
            scroll_notches=_int(data.get("scroll_notches"), 3),
            scroll_delay_ms=_int(data.get("scroll_delay_ms"), 250),
            scroll_max_height=_int(data.get("scroll_max_height"), 20000),
            scroll_ignore_top=_int(data.get("scroll_ignore_top"), 0),
            scroll_ignore_bottom=_int(data.get("scroll_ignore_bottom"), 0),
            window_margin_px=_int(data.get("window_margin_px"), 0),
        ).normalized()


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return fallback
    return bool(value)


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_FILE


def load_settings(data_dir: Path) -> ScreenshotSettings:
    path = settings_path(data_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return ScreenshotSettings.from_mapping(json.load(handle))
    except FileNotFoundError:
        return ScreenshotSettings()
    except Exception as exc:
        log.warning("读取截图设置失败，使用默认值：%s", exc)
        return ScreenshotSettings()


def save_settings(data_dir: Path, settings: ScreenshotSettings) -> ScreenshotSettings:
    normalized = settings.normalized()
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(normalized.to_mapping(), ensure_ascii=False, indent=2) + "\n"
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
    return normalized
