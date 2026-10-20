"""Persistent scratchpad rows for the calculator plugin."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from quicktools.plugins.calculator.engine import (
    MAX_EXPRESSION_LENGTH,
    SUPPORTED_BASES,
)
from quicktools.plugins.calculator.settings import (
    atomic_write_json,
    normalize_max_records,
)

log = logging.getLogger(__name__)

SCRATCHPAD_FILE = "scratchpad.json"
SCRATCHPAD_VERSION = 1
DEFAULT_LAST_BASE = 10


@dataclass(frozen=True)
class ScratchEntry:
    expression: str
    base: int = 10


@dataclass(frozen=True)
class ScratchpadState:
    entries: tuple[ScratchEntry, ...] = ()
    last_base: int = 10


def scratchpad_path(data_dir: Path) -> Path:
    return Path(data_dir) / SCRATCHPAD_FILE


def _valid_base(value: object) -> int:
    if isinstance(value, bool):
        return DEFAULT_LAST_BASE
    try:
        base = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LAST_BASE
    return base if base in SUPPORTED_BASES else DEFAULT_LAST_BASE


def _valid_entry(item: object) -> ScratchEntry | None:
    if not isinstance(item, dict):
        return None
    expression = item.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return None
    if len(expression) > MAX_EXPRESSION_LENGTH:
        return None
    return ScratchEntry(expression, _valid_base(item.get("base")))


def _limit_entries(
    entries: list[ScratchEntry], max_records: int
) -> tuple[ScratchEntry, ...]:
    limit = normalize_max_records(max_records)
    return tuple(entries[-limit:])


def load_scratchpad(
    data_dir: Path | None, *, max_records: int
) -> ScratchpadState:
    if data_dir is None:
        return ScratchpadState()
    path = scratchpad_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ScratchpadState()
    except Exception as exc:
        log.warning("读取草稿纸记忆失败，使用空草稿纸：%s", exc)
        return ScratchpadState()
    if not isinstance(raw, dict):
        log.warning("草稿纸记忆根节点不是对象，已忽略")
        return ScratchpadState()

    raw_rows = raw.get("rows")
    if not isinstance(raw_rows, list):
        if raw_rows is not None:
            log.warning("草稿纸记忆 rows 不是列表，已忽略")
        return ScratchpadState(last_base=_valid_base(raw.get("last_base")))

    entries = [
        entry
        for item in raw_rows
        if (entry := _valid_entry(item)) is not None
    ]
    return ScratchpadState(
        entries=_limit_entries(entries, max_records),
        last_base=_valid_base(raw.get("last_base")),
    )


def save_scratchpad(
    data_dir: Path | None,
    state: ScratchpadState,
    *,
    max_records: int,
) -> None:
    if data_dir is None:
        return
    entries: list[ScratchEntry] = []
    for item in state.entries:
        entry = _valid_entry(
            {"expression": item.expression, "base": item.base}
        )
        if entry is not None:
            entries.append(entry)
    entries = list(_limit_entries(entries, max_records))
    payload = {
        "version": SCRATCHPAD_VERSION,
        "last_base": _valid_base(state.last_base),
        "rows": [
            {"expression": entry.expression, "base": entry.base}
            for entry in entries
        ],
    }
    atomic_write_json(scratchpad_path(data_dir), payload)
