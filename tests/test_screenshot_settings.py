from __future__ import annotations

import json
from pathlib import Path

from quicktools.config import HotkeySpec
from quicktools.plugins.screenshot.settings import (
    ScreenshotSettings,
    default_save_dir,
    load_settings,
    save_settings,
    settings_path,
)


def test_defaults_and_hotkey() -> None:
    settings = ScreenshotSettings()
    assert settings.image_format == "png"
    assert settings.window_margin_px == 0
    assert settings.hotkey.display() == "Ctrl+Alt+X"
    assert settings.resolved_save_dir() == default_save_dir()


def test_normalized_clamps_values() -> None:
    settings = ScreenshotSettings(
        image_format="gif",
        jpeg_quality=999,
        recent_limit=1,
        recent_max_mb=1,
        hide_delay_ms=1,
        default_width=0,
        default_font_size=1,
        scroll_notches=0,
        scroll_delay_ms=1,
        scroll_max_height=1,
        scroll_ignore_top=-5,
        scroll_ignore_bottom=-7,
        window_margin_px=-10,
    ).normalized()
    assert settings.image_format == "png"
    assert settings.jpeg_quality == 100
    assert settings.recent_limit == 10
    assert settings.recent_max_mb == 50
    assert settings.hide_delay_ms == 50
    assert settings.default_width == 1
    assert settings.default_font_size == 8
    assert settings.scroll_notches == 1
    assert settings.scroll_delay_ms == 50
    assert settings.scroll_max_height == 1000
    assert settings.scroll_ignore_top == 0
    assert settings.scroll_ignore_bottom == 0
    assert settings.window_margin_px == 0
    assert (
        ScreenshotSettings(window_margin_px=9999).normalized().window_margin_px
        == 500
    )


def test_roundtrip_and_corruption(tmp_path: Path) -> None:
    settings = ScreenshotSettings(
        hotkey=HotkeySpec(("ctrl", "shift"), "a"),
        save_dir=str(tmp_path / "shots"),
        image_format="jpeg",
        jpeg_quality=80,
        recent_limit=42,
        window_margin_px=37,
    )
    saved = save_settings(tmp_path, settings)
    loaded = load_settings(tmp_path)
    assert loaded == saved
    assert loaded.window_margin_px == 37
    assert loaded.hotkey.display() == "Ctrl+Shift+A"

    path = settings_path(tmp_path)
    path.write_text("{not json", encoding="utf-8")
    fallback = load_settings(tmp_path)
    assert fallback.image_format == "png"

    path.write_text(json.dumps({"hotkey": {"modifiers": ["ctrl"], "key": "x"}}), encoding="utf-8")
    partial = load_settings(tmp_path)
    assert partial.hotkey.display() == "Ctrl+X"
