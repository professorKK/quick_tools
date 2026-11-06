"""gp 插件设置，保存在插件数据目录下的 ``settings.json``。

设置界面完全在 Qt helper 进程里，因此这个文件只由 helper 读写；Tk 主进程
不碰它，避免两个进程抢写同一个文件。字段保持与旧版本兼容，只新增可选的
``screen``（显示器名称）。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

SETTINGS_NAME = "settings.json"

DEFAULT_IDLE_OPACITY = 0.5
DEFAULT_ACTIVE_OPACITY = 1.0
DEFAULT_DIAMETER = 120
DEFAULT_TEXT = "10vpn"
DEFAULT_FILL_BACKGROUND = False

MIN_OPACITY = 0.1
MAX_OPACITY = 1.0
# 手动输入范围；滑块只覆盖常用的 10–250。
MIN_DIAMETER = 0
MAX_DIAMETER = 1000
SLIDER_MIN_DIAMETER = 10
SLIDER_MAX_DIAMETER = 250


def clamp_opacity(value: object, default: float = DEFAULT_IDLE_OPACITY) -> float:
    """Return a usable opacity in ``[MIN_OPACITY, MAX_OPACITY]``."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(MIN_OPACITY, min(MAX_OPACITY, number))


def clamp_diameter(value: object, default: int = DEFAULT_DIAMETER) -> int:
    """Return a usable diameter in ``[MIN_DIAMETER, MAX_DIAMETER]``.

    ``MIN_DIAMETER`` is 0 because the settings dialog allows manual input down
    to 0; the widget keeps a small clickable render size so it can still be
    recovered with the context menu (see ``qt_widget.MIN_RENDER_DIAMETER``).
    """
    if isinstance(value, bool):
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(MIN_DIAMETER, min(MAX_DIAMETER, number))


def _clamp_coord(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_TEXT
    text = value.strip()
    return text or DEFAULT_TEXT


def _clean_screen(value: object, x: int | None, y: int | None) -> str | None:
    """Keep a screen name only when it can accompany a saved position."""
    if x is None or y is None or not isinstance(value, str):
        return None
    name = value.strip()
    return name or None


@dataclass(frozen=True)
class GpSettings:
    """Everything the floating widget needs to render and restore itself."""

    idle_opacity: float = DEFAULT_IDLE_OPACITY
    active_opacity: float = DEFAULT_ACTIVE_OPACITY
    diameter: int = DEFAULT_DIAMETER
    text: str = DEFAULT_TEXT
    fill_background: bool = DEFAULT_FILL_BACKGROUND
    x: int | None = None
    y: int | None = None
    screen: str | None = None

    def normalized(self) -> "GpSettings":
        x = _clamp_coord(self.x)
        y = _clamp_coord(self.y)
        return replace(
            self,
            idle_opacity=clamp_opacity(
                self.idle_opacity, DEFAULT_IDLE_OPACITY
            ),
            active_opacity=clamp_opacity(
                self.active_opacity, DEFAULT_ACTIVE_OPACITY
            ),
            diameter=clamp_diameter(self.diameter, DEFAULT_DIAMETER),
            text=_clean_text(self.text),
            fill_background=bool(self.fill_background),
            x=x,
            y=y,
            screen=_clean_screen(self.screen, x, y),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_NAME


def load_settings(data_dir: Path | None) -> GpSettings:
    """Read the settings file; missing or broken files fall back to defaults."""
    if data_dir is None:
        return GpSettings()
    path = settings_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return GpSettings()
    if not isinstance(raw, dict):
        return GpSettings()
    defaults = GpSettings()
    return GpSettings(
        idle_opacity=clamp_opacity(
            raw.get("idle_opacity"), defaults.idle_opacity
        ),
        active_opacity=clamp_opacity(
            raw.get("active_opacity"), defaults.active_opacity
        ),
        diameter=clamp_diameter(raw.get("diameter"), defaults.diameter),
        text=_clean_text(raw.get("text")),
        fill_background=(
            bool(raw.get("fill_background"))
            if isinstance(raw.get("fill_background"), bool)
            else defaults.fill_background
        ),
        x=_clamp_coord(raw.get("x")),
        y=_clamp_coord(raw.get("y")),
        # 旧版本没有 screen，缺失时按 None 处理。
        screen=(
            raw.get("screen")
            if isinstance(raw.get("screen"), str)
            else None
        ),
    ).normalized()


def save_settings(data_dir: Path, settings: GpSettings) -> None:
    """Atomically persist the settings; failures are surfaced to the caller."""
    settings = settings.normalized()
    target = settings_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(settings.to_json())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
