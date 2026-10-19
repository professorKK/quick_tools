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
