from __future__ import annotations

from pathlib import Path

from quicktools.plugin_api import PluginMeta


def meta(icon: str, name: str = "示例插件") -> PluginMeta:
    return PluginMeta(
        id="demo",
        name=name,
        description="",
        version="1",
        entry="plugin.py",
        class_name="Demo",
        folder=Path("."),
        icon=icon,
    )


def test_ascii_icon_is_used() -> None:
    assert meta("=").display_icon == "="
    assert meta("H").display_icon == "H"


def test_emoji_icon_falls_back_to_name_initial() -> None:
    assert meta("🧮", "计算器").display_icon == "计"
    assert meta("👋", "Hello").display_icon == "H"


def test_empty_icon_falls_back_to_name_initial() -> None:
    assert meta("", "计算器").display_icon == "计"
