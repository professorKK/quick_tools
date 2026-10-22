from __future__ import annotations

import json
from pathlib import Path

import pytest

from quicktools.config import (
    AppSettings,
    HotkeySpec,
    load_settings,
    save_settings,
)


def test_screenshot_save_dir_inside_plugin_root_is_detected(
    tmp_path: Path,
) -> None:
    from quicktools.settings_ui import SettingsWindow

    root = tmp_path / "plugin-root"
    save_dir = root / "screenshot" / "shots"
    save_dir.mkdir(parents=True)
    (root / "screenshot" / "settings.json").write_text(
        json.dumps({"save_dir": str(save_dir)}), encoding="utf-8"
    )
    assert (
        SettingsWindow._screenshot_save_dir_within(root) == save_dir.resolve()
    )
    assert (
        SettingsWindow._screenshot_save_dir_within(tmp_path / "other") is None
    )


def test_default_hotkey_windows() -> None:
    spec = HotkeySpec.default("win32")
    assert spec.modifiers == ("ctrl",)
    assert spec.key == "space"
    assert spec.display() == "Ctrl+Space"


def test_default_hotkey_linux_avoids_ime_chord() -> None:
    spec = HotkeySpec.default("linux")
    assert spec.modifiers == ("ctrl", "alt")
    assert spec.key == "space"
    assert spec.display() == "Ctrl+Alt+Space"


def test_modifier_order_is_normalized() -> None:
    spec = HotkeySpec(("shift", "ctrl", "alt"), "q")
    assert spec.modifiers == ("ctrl", "alt", "shift")
    assert spec.display() == "Ctrl+Alt+Shift+Q"


@pytest.mark.parametrize(
    "modifiers,key",
    [
        ((), "space"),
        (("hyper",), "space"),
        (("ctrl",), "escape"),
        (("ctrl",), "?"),
        (("ctrl",), ""),
        (("ctrl",), "f21"),
    ],
)
def test_invalid_hotkeys(modifiers, key) -> None:
    with pytest.raises(ValueError):
        HotkeySpec(modifiers, key)


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = AppSettings(HotkeySpec(("ctrl", "alt"), "q"))
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded == settings
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["hotkey"]["key"] == "q"


def test_corrupt_settings_fall_back_to_default(tmp_path: Path, caplog) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_settings(path) == AppSettings.default()


def test_missing_settings_uses_default(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "missing.json") == AppSettings.default()


def test_invalid_hotkey_payload_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hotkey": {"modifiers": [], "key": "space"}}))
    assert load_settings(path) == AppSettings.default()


def test_save_leaves_no_temp_file(tmp_path: Path) -> None:
    save_settings(AppSettings.default(), tmp_path / "settings.json")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_plugin_data_root_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = AppSettings(
        HotkeySpec(("ctrl", "alt"), "q"),
        plugin_data_root=str(tmp_path / "plugins"),
    )
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded == settings
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["plugin_data_root"] == str(tmp_path / "plugins")


def test_legacy_settings_default_to_empty_plugin_root(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"version": 1, "hotkey": {"modifiers": ["ctrl"], "key": "space"}}),
        encoding="utf-8",
    )
    assert load_settings(path).plugin_data_root == ""


def test_invalid_plugin_data_root_type_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"hotkey": {"modifiers": ["ctrl"], "key": "space"}, "plugin_data_root": 42}),
        encoding="utf-8",
    )
    assert load_settings(path).plugin_data_root == ""


def test_set_hotkey_preserves_plugin_data_root(monkeypatch) -> None:
    from quicktools import app as app_module

    instance = object.__new__(app_module.QuickToolsApp)
    instance.settings = AppSettings(
        HotkeySpec(("ctrl", "alt"), "space"),
        plugin_data_root="/tmp/custom-plugin-data",
    )

    class _Hotkey:
        def change(self, _spec):
            return True, ""

    instance.hotkey = _Hotkey()
    instance._hotkey_capturing = False
    instance._refresh_status_ui = lambda: None
    saved = {}
    monkeypatch.setattr(
        app_module, "save_settings", lambda value: saved.setdefault("value", value)
    )

    ok, _message = instance.set_hotkey(HotkeySpec(("ctrl", "alt"), "q"))

    assert ok
    assert saved["value"].plugin_data_root == "/tmp/custom-plugin-data"
    assert instance.settings.hotkey == HotkeySpec(("ctrl", "alt"), "q")
