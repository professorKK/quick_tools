from __future__ import annotations

import json
from pathlib import Path

from quicktools.plugin_api import PluginBase
from quicktools.plugin_loader import PluginLoader
from quicktools.plugins.gp.geometry import (
    Rect,
    ScreenArea,
    Size,
    clamp_into,
    default_position,
    place_dialog,
    position_after_resize,
    resolve_position,
    screen_by_name,
    screen_for_rect,
)
from quicktools.plugins.gp.host import (
    GpFloatingHost,
    helper_command,
    parse_event,
)
from quicktools.plugins.gp.plugin import GpPlugin
from quicktools.plugins.gp.settings import (
    GpSettings,
    load_settings,
    save_settings,
    settings_path,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILTIN_PLUGINS = _REPO_ROOT / "quicktools" / "plugins"

_PRIMARY = ScreenArea("DP-1", 0, 0, 1920, 1080)
_LEFT = ScreenArea("HDMI-1", -1920, 0, 1920, 1080)
_RIGHT = ScreenArea("DP-2", 1920, 0, 1600, 900)
_SCREENS = [_LEFT, _PRIMARY, _RIGHT]


# --------------------------------------------------------------- settings
def test_settings_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)
    assert settings.idle_opacity == 0.5
    assert settings.active_opacity == 1.0
    assert settings.diameter == 120
    assert settings.text == "10vpn"
    assert settings.fill_background is False
    assert settings.x is None
    assert settings.y is None
    assert settings.screen is None


def test_settings_round_trip(tmp_path: Path) -> None:
    save_settings(
        tmp_path,
        GpSettings(
            idle_opacity=0.3,
            active_opacity=0.85,
            diameter=150,
            text="10vpn",
            fill_background=True,
            x=120,
            y=240,
            screen="DP-2",
        ),
    )
    loaded = load_settings(tmp_path)
    assert loaded.idle_opacity == 0.3
    assert loaded.active_opacity == 0.85
    assert loaded.diameter == 150
    assert loaded.fill_background is True
    assert loaded.x == 120
    assert loaded.y == 240
    assert loaded.screen == "DP-2"
    stored = json.loads(settings_path(tmp_path).read_text(encoding="utf-8"))
    assert stored["idle_opacity"] == 0.3
    assert stored["screen"] == "DP-2"
    # 原子写入，不留下临时文件。
    assert not settings_path(tmp_path).with_name("settings.json.tmp").exists()


def test_settings_legacy_file_without_screen(tmp_path: Path) -> None:
    settings_path(tmp_path).write_text(
        json.dumps(
            {
                "idle_opacity": 0.4,
                "active_opacity": 0.9,
                "diameter": 140,
                "text": "旧配置",
                "fill_background": True,
                "x": 300,
                "y": 400,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_settings(tmp_path)
    assert loaded.idle_opacity == 0.4
    assert loaded.diameter == 140
    assert loaded.text == "旧配置"
    assert loaded.x == 300
    assert loaded.y == 400
    assert loaded.screen is None


def test_settings_invalid_values_fall_back(tmp_path: Path) -> None:
    settings_path(tmp_path).write_text(
        json.dumps(
            {
                "idle_opacity": "abc",
                "active_opacity": 5,
                "diameter": -5,
                "text": "   ",
                "fill_background": "yes",
                "x": "nope",
                "y": None,
                "screen": "DP-1",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_settings(tmp_path)
    assert loaded.idle_opacity == 0.5
    assert loaded.active_opacity == 1.0
    assert loaded.diameter == 0
    assert loaded.text == "10vpn"
    assert loaded.fill_background is False
    assert loaded.x is None
    assert loaded.y is None
    # 没有有效坐标时，屏幕名没有意义，必须一起丢弃。
    assert loaded.screen is None


def test_settings_broken_file_falls_back(tmp_path: Path) -> None:
    settings_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_settings(tmp_path).diameter == 120


def test_settings_nan_opacity_falls_back() -> None:
    assert GpSettings(idle_opacity=float("nan")).normalized().idle_opacity == 0.5


def test_settings_diameter_bounds() -> None:
    assert GpSettings(diameter=-5).normalized().diameter == 0
    assert GpSettings(diameter=1200).normalized().diameter == 1000
    assert GpSettings(diameter=250).normalized().diameter == 250
    assert GpSettings(diameter=10).normalized().diameter == 10


def test_settings_screen_requires_position() -> None:
    settings = GpSettings(screen="DP-1").normalized()
    assert settings.screen is None
    settings = GpSettings(x=10, y=20, screen="DP-1").normalized()
    assert settings.screen == "DP-1"


# --------------------------------------------------------------- protocol
def test_parse_event_known_lines() -> None:
    assert parse_event("closed") == ("closed", ())
    assert parse_event("position 120 340") == ("position", (120, 340))
    assert parse_event("ready") == ("", ())
    assert parse_event("position x y") == ("", ())
    assert parse_event("") == ("", ())
    assert parse_event("   ") == ("", ())
    assert parse_event("nonsense") == ("", ())


class _FakeHostWindow:
    def __init__(self) -> None:
        self.destroyed = False

    def withdraw(self) -> None:
        pass

    def update_idletasks(self) -> None:
        pass

    def destroy(self) -> None:
        self.destroyed = True


def test_host_dispatches_events(tmp_path: Path) -> None:
    host = GpFloatingHost(None, tmp_path)  # type: ignore[arg-type]
    # 未知事件与已知事件都不能让主线程崩掉。
    host.handle_line("position 10 20")
    host.handle_line("nonsense")


def test_host_exit_event_destroys_proxy(tmp_path: Path) -> None:
    """右键“退出”后代理窗口必须销毁，启动器卡片才会恢复未打开。"""
    window = _FakeHostWindow()
    host = GpFloatingHost(window, tmp_path)  # type: ignore[arg-type]
    host.handle_line("closed")
    assert window.destroyed is True


def test_helper_command_contains_flag(tmp_path: Path) -> None:
    command = helper_command(tmp_path, tmp_path / "plugin")
    assert "--gp-qt-helper" in command
    assert "--data-dir" in command
    assert str(tmp_path) in command
    assert "--plugin-dir" in command


# ---------------------------------------------------------------- manifest
def test_builtin_manifest_is_discoverable(tmp_path: Path) -> None:
    loader = PluginLoader(user_plugins=tmp_path, builtin_plugins=_BUILTIN_PLUGINS)
    plugins = loader.scan()
    metas = [meta for meta in plugins if meta.id == "gp"]
    assert len(metas) == 1
    meta = metas[0]
    assert meta.name == "gp插件"
    assert meta.background is False
    assert meta.class_name == "GpPlugin"
    assert meta.summary
    assert meta.description
    assert meta.version == "0.3.0"


# ------------------------------------------------------------------- 约束
def test_plugin_has_no_tk_settings_page() -> None:
    """gp 插件的界面全部在 Qt 侧，Tk 侧不提供设置页。"""
    assert GpPlugin.create_settings_ui is PluginBase.create_settings_ui


# ---------------------------------------------------------------- geometry
def test_default_position_uses_bottom_right_with_margin() -> None:
    assert default_position(Size(120, 120), _PRIMARY) == (1780, 940)


def test_default_position_supports_negative_coordinates() -> None:
    assert default_position(Size(120, 120), _LEFT) == (-140, 940)


def test_screen_by_name_and_for_rect() -> None:
    assert screen_by_name("DP-2", _SCREENS) is _RIGHT
    assert screen_by_name("", _SCREENS) is None
    assert screen_for_rect(Rect(1900, 100, 120, 120), _SCREENS) is _RIGHT
    assert screen_for_rect(Rect(500, 500, 120, 120), _SCREENS) is _PRIMARY


def test_screen_for_rect_uses_largest_overlap() -> None:
    # 大部分落在右侧副屏，只有一条边压在主屏上。
    assert screen_for_rect(Rect(1850, 100, 200, 100), _SCREENS) is _RIGHT


def test_screen_for_rect_in_gap_uses_nearest_center() -> None:
    gap = Rect(4000, 3000, 120, 120)
    assert screen_for_rect(gap, _SCREENS) is _RIGHT


def test_clamp_into_fully_inside() -> None:
    assert clamp_into(Rect(100, 200, 120, 120), _PRIMARY) == (100, 200)


def test_clamp_into_oversized_rect_anchors_top_left() -> None:
    assert clamp_into(Rect(500, 500, 4000, 3000), _PRIMARY) == (0, 0)


def test_resolve_position_defaults_to_primary() -> None:
    assert resolve_position(
        None, None, None, Size(120, 120), _SCREENS, "DP-1"
    ) == (1780, 940)


def test_resolve_position_restores_saved_screen() -> None:
    # 坐标现在越界，但保存的屏幕仍在：回到该屏幕并夹取到可用区域。
    assert resolve_position(
        5000, 5000, "DP-2", Size(120, 120), _SCREENS, "DP-1"
    ) == (3400, 780)


def test_resolve_position_with_negative_screen() -> None:
    assert resolve_position(
        -500, 100, "HDMI-1", Size(120, 120), _SCREENS, "DP-1"
    ) == (-500, 100)


def test_resolve_position_falls_back_when_screen_is_gone() -> None:
    # 保存的屏幕已断开：显示到最近屏幕，但返回结果不包含屏幕名，调用方
    # 因此不会覆盖保存值。
    assert resolve_position(
        -500, 100, "GONE-1", Size(120, 120), _SCREENS, "DP-1"
    ) == (-500, 100)
    assert resolve_position(
        2500, 100, "GONE-1", Size(120, 120), _SCREENS, "DP-1"
    ) == (2500, 100)


def test_resolve_position_without_screens() -> None:
    assert resolve_position(12, 34, None, Size(120, 120), [], None) == (12, 34)


def test_position_after_resize_keeps_center_and_visible() -> None:
    x, y, screen = position_after_resize(
        Rect(1780, 940, 120, 120), Size(240, 240), _SCREENS
    )
    assert (x, y) == (1680, 840)
    assert screen == "DP-1"
    assert x >= _PRIMARY.x and y >= _PRIMARY.y
    assert x + 240 <= _PRIMARY.right and y + 240 <= _PRIMARY.bottom


def test_position_after_resize_without_screens() -> None:
    assert position_after_resize(
        Rect(10, 20, 120, 120), Size(240, 240), []
    ) == (10, 20, None)


def test_place_dialog_prefers_left_side() -> None:
    # 底部保留 56px 边距，而不是贴着屏幕底边。
    assert place_dialog(
        Rect(1780, 940, 120, 120), Size(400, 500), _PRIMARY
    ) == (1368, 524)


def test_place_dialog_keeps_bottom_margin() -> None:
    x, y = place_dialog(
        Rect(1780, 940, 120, 120), Size(400, 500), _PRIMARY
    )
    assert y + 500 == _PRIMARY.bottom - 56
    assert x + 400 <= _PRIMARY.right


def test_place_dialog_flips_to_right_when_left_is_tight() -> None:
    assert place_dialog(
        Rect(100, 500, 120, 120), Size(400, 300), _PRIMARY
    ) == (232, 410)


def test_place_dialog_clamps_when_neither_side_fits() -> None:
    assert place_dialog(
        Rect(200, 200, 120, 120), Size(400, 300), ScreenArea("S", 0, 0, 500, 500)
    ) == (8, 110)


def test_place_dialog_oversized_dialog_keeps_top_left_reachable() -> None:
    assert place_dialog(
        Rect(100, 100, 120, 120),
        Size(400, 400),
        ScreenArea("S", 0, 0, 300, 300),
    ) == (8, 8)


def test_place_dialog_on_secondary_screen() -> None:
    x, y = place_dialog(
        Rect(3400, 780, 120, 120), Size(400, 300), _RIGHT
    )
    # 左侧放得下，但垂直方向被副屏底边夹住（底部保留 56px）。
    assert x == 3400 - 12 - 400
    assert y == 900 - 56 - 300
