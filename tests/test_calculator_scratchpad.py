from __future__ import annotations

import json
from pathlib import Path

from quicktools.plugins.calculator.engine import MAX_EXPRESSION_LENGTH
from quicktools.plugins.calculator.scratchpad_store import (
    ScratchEntry,
    ScratchpadState,
    load_scratchpad,
    save_scratchpad,
    scratchpad_path,
)


def test_missing_and_disabled_data_dir_return_empty(tmp_path: Path) -> None:
    assert load_scratchpad(None, max_records=200) == ScratchpadState()
    assert load_scratchpad(tmp_path, max_records=200) == ScratchpadState()


def test_roundtrip_entries_bases_and_last_base(tmp_path: Path) -> None:
    state = ScratchpadState(
        entries=(
            ScratchEntry("1+1", 10),
            ScratchEntry("FF+1", 16),
            ScratchEntry("0b101+1", 10),
        ),
        last_base=16,
    )
    save_scratchpad(tmp_path, state, max_records=200)
    assert load_scratchpad(tmp_path, max_records=200) == state

    payload = json.loads(
        scratchpad_path(tmp_path).read_text(encoding="utf-8")
    )
    assert payload["version"] == 1
    assert payload["last_base"] == 16
    assert payload["rows"] == [
        {"expression": "1+1", "base": 10},
        {"expression": "FF+1", "base": 16},
        {"expression": "0b101+1", "base": 10},
    ]


def test_invalid_rows_are_skipped_and_bad_base_falls_back(tmp_path: Path) -> None:
    payload = {
        "version": 1,
        "last_base": 7,
        "rows": [
            {"expression": "1+1", "base": 10},
            {"expression": "   ", "base": 10},
            {"expression": 42, "base": 10},
            {"expression": "2+2", "base": 7},
            "not-a-dict",
            {"expression": "A" * (MAX_EXPRESSION_LENGTH + 1), "base": 16},
            {"expression": "0xFF", "base": 16},
        ],
    }
    scratchpad_path(tmp_path).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    state = load_scratchpad(tmp_path, max_records=200)
    assert state.last_base == 10
    assert [(entry.expression, entry.base) for entry in state.entries] == [
        ("1+1", 10),
        ("2+2", 10),
        ("0xFF", 16),
    ]


def test_limit_keeps_newest_entries_on_save_and_load(tmp_path: Path) -> None:
    entries = tuple(ScratchEntry(f"{index}+1") for index in range(6))
    save_scratchpad(
        tmp_path,
        ScratchpadState(entries=entries, last_base=10),
        max_records=3,
    )
    payload = json.loads(
        scratchpad_path(tmp_path).read_text(encoding="utf-8")
    )
    assert [row["expression"] for row in payload["rows"]] == [
        "3+1",
        "4+1",
        "5+1",
    ]

    assert [
        entry.expression
        for entry in load_scratchpad(tmp_path, max_records=2).entries
    ] == ["4+1", "5+1"]


def test_corrupt_scratchpad_falls_back_to_empty(tmp_path: Path) -> None:
    scratchpad_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert load_scratchpad(tmp_path, max_records=200) == ScratchpadState()

    scratchpad_path(tmp_path).write_text("[1, 2]", encoding="utf-8")
    assert load_scratchpad(tmp_path, max_records=200) == ScratchpadState()

    scratchpad_path(tmp_path).write_text(
        '{"last_base": 16, "rows": "nope"}', encoding="utf-8"
    )
    assert load_scratchpad(tmp_path, max_records=200) == ScratchpadState(
        last_base=16
    )


def test_save_recovers_corrupt_file_and_leaves_no_temp_files(
    tmp_path: Path,
) -> None:
    scratchpad_path(tmp_path).write_text("{not json", encoding="utf-8")
    save_scratchpad(
        tmp_path,
        ScratchpadState((ScratchEntry("1+1"),), last_base=10),
        max_records=200,
    )
    assert load_scratchpad(tmp_path, max_records=200).entries == (
        ScratchEntry("1+1"),
    )
    assert list(tmp_path.glob(".*.tmp")) == []
