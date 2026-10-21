from __future__ import annotations

import json
from pathlib import Path

from quicktools.window_state import WindowState, WindowStateStore


def test_store_round_trips_sizes_and_maximized_state(tmp_path: Path) -> None:
    path = tmp_path / "window_state.json"
    store = WindowStateStore(path)

    assert store.get("calculator") is None
    assert store.set("calculator", 720, 840) is True
    assert store.set("clipboard", 1024, 700, maximized=True) is True
    assert store.set("calculator", 720, 840) is False
    assert store.save() is True

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["windows"]["calculator"] == {
        "width": 720,
        "height": 840,
        "maximized": False,
    }
    assert payload["windows"]["clipboard"]["maximized"] is True

    reloaded = WindowStateStore(path)
    assert reloaded.get("calculator") == WindowState(720, 840)
    assert reloaded.get("clipboard") == WindowState(1024, 700, maximized=True)


def test_store_ignores_invalid_entries_but_keeps_valid_ones(
    tmp_path: Path,
) -> None:
    path = tmp_path / "window_state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "windows": {
                    "ok": {"width": 640, "height": 480, "maximized": False},
                    "too_small": {"width": 10, "height": 480},
                    "boolean": {"width": True, "height": 480},
                    "missing": {"height": 480},
                    "": {"width": 640, "height": 480},
                    "bad_node": "not-a-window",
                },
            }
        ),
        encoding="utf-8",
    )

    store = WindowStateStore(path)
    assert store.get("ok") == WindowState(640, 480)
    assert store.get("too_small") is None
    assert store.get("boolean") is None
    assert store.get("missing") is None
    assert store.get("") is None
    assert store.get("bad_node") is None


def test_corrupt_state_file_falls_back_to_empty_store(tmp_path: Path) -> None:
    path = tmp_path / "window_state.json"
    path.write_text("{broken", encoding="utf-8")

    store = WindowStateStore(path)
    assert store.get("calculator") is None
    assert store.set("calculator", 600, 700) is True
    assert store.save() is True
    assert WindowStateStore(path).get("calculator") == WindowState(600, 700)


def test_store_rejects_tiny_windows(tmp_path: Path) -> None:
    store = WindowStateStore(tmp_path / "window_state.json")
    assert store.set("calculator", 1, 700) is False
    assert store.set("calculator", 700, 0) is False
    assert store.save() is False
    assert not (tmp_path / "window_state.json").exists()
