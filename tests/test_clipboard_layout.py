from __future__ import annotations

import json
from pathlib import Path

from quicktools.plugins.clipboard import layout
from quicktools.plugins.clipboard.layout import (
    DEFAULT_DETAIL_WIDTH,
    MAX_PANE_WIDTH,
    MIN_DETAIL_WIDTH,
    MIN_LIST_WIDTH,
    MIN_SIDEBAR_WIDTH,
    ClipboardLayout,
    layout_path,
    load_layout,
    save_layout,
)


def test_missing_layout_uses_defaults(tmp_path: Path) -> None:
    assert load_layout(tmp_path) == ClipboardLayout()


def test_layout_round_trip(tmp_path: Path) -> None:
    saved = ClipboardLayout(260, 640, 500)
    assert save_layout(tmp_path, saved) is True
    assert load_layout(tmp_path) == saved
    raw = json.loads(layout_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["sidebar_width"] == 260


def test_corrupt_or_non_mapping_layout_uses_defaults(tmp_path: Path) -> None:
    layout_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_layout(tmp_path) == ClipboardLayout()

    layout_path(tmp_path).write_text("[]", encoding="utf-8")
    assert load_layout(tmp_path) == ClipboardLayout()


def test_invalid_widths_are_clamped_or_defaulted(tmp_path: Path) -> None:
    layout_path(tmp_path).write_text(
        json.dumps(
            {
                "sidebar_width": 10,
                "list_width": 999999,
                "detail_width": True,
            }
        ),
        encoding="utf-8",
    )
    assert load_layout(tmp_path) == ClipboardLayout(
        sidebar_width=MIN_SIDEBAR_WIDTH,
        list_width=MAX_PANE_WIDTH,
        detail_width=DEFAULT_DETAIL_WIDTH,
    )


def test_save_normalizes_widths(tmp_path: Path) -> None:
    assert save_layout(tmp_path, ClipboardLayout(1, -20, 999999)) is True
    assert load_layout(tmp_path) == ClipboardLayout(
        sidebar_width=MIN_SIDEBAR_WIDTH,
        list_width=MIN_LIST_WIDTH,
        detail_width=MAX_PANE_WIDTH,
    )


def test_save_failure_returns_false_and_cleans_temp(
    tmp_path: Path, monkeypatch
) -> None:
    def fail_replace(_source, _target) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(layout.os, "replace", fail_replace)
    assert save_layout(tmp_path, ClipboardLayout(250, 520, 450)) is False
    assert not (tmp_path / "layout.json.tmp").exists()
