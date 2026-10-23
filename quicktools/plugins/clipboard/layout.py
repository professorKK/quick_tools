"""Persist the clipboard window's three-pane widths between openings.

This is UI state rather than user settings: if the file is missing, corrupted
or cannot be written, the view must still open with sensible defaults instead
of surfacing an error.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

LAYOUT_NAME = "layout.json"
LAYOUT_VERSION = 1

DEFAULT_SIDEBAR_WIDTH = 232
DEFAULT_LIST_WIDTH = 500
DEFAULT_DETAIL_WIDTH = 430
MIN_SIDEBAR_WIDTH = 220
MIN_LIST_WIDTH = 340
MIN_DETAIL_WIDTH = 320
MAX_PANE_WIDTH = 10000


@dataclass(frozen=True)
class ClipboardLayout:
    """Saved widths of the sidebar, history list and detail panes."""

    sidebar_width: int = DEFAULT_SIDEBAR_WIDTH
    list_width: int = DEFAULT_LIST_WIDTH
    detail_width: int = DEFAULT_DETAIL_WIDTH

    def to_mapping(self) -> dict[str, int]:
        return {
            "sidebar_width": self.sidebar_width,
            "list_width": self.list_width,
            "detail_width": self.detail_width,
        }


def layout_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / LAYOUT_NAME


def _clamp_width(value: object, minimum: int, default: int) -> int:
    """Return a usable pane width, falling back to ``default`` for junk."""
    if isinstance(value, bool):
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(MAX_PANE_WIDTH, number))


def load_layout(data_dir: Path | str) -> ClipboardLayout:
    """Load saved pane widths; missing/corrupt data returns the defaults."""
    try:
        raw = json.loads(layout_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ClipboardLayout()
    if not isinstance(raw, dict):
        return ClipboardLayout()
    return ClipboardLayout(
        sidebar_width=_clamp_width(
            raw.get("sidebar_width"),
            MIN_SIDEBAR_WIDTH,
            DEFAULT_SIDEBAR_WIDTH,
        ),
        list_width=_clamp_width(
            raw.get("list_width"),
            MIN_LIST_WIDTH,
            DEFAULT_LIST_WIDTH,
        ),
        detail_width=_clamp_width(
            raw.get("detail_width"),
            MIN_DETAIL_WIDTH,
            DEFAULT_DETAIL_WIDTH,
        ),
    )


def save_layout(data_dir: Path | str, layout: ClipboardLayout) -> bool:
    """Atomically persist pane widths; return False on write failure."""
    normalized = ClipboardLayout(
        sidebar_width=_clamp_width(
            layout.sidebar_width,
            MIN_SIDEBAR_WIDTH,
            DEFAULT_SIDEBAR_WIDTH,
        ),
        list_width=_clamp_width(
            layout.list_width,
            MIN_LIST_WIDTH,
            DEFAULT_LIST_WIDTH,
        ),
        detail_width=_clamp_width(
            layout.detail_width,
            MIN_DETAIL_WIDTH,
            DEFAULT_DETAIL_WIDTH,
        ),
    )
    target = layout_path(data_dir)
    temp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(
                {"version": LAYOUT_VERSION, **normalized.to_mapping()},
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        return True
    except OSError:
        log.exception("保存剪贴板三栏布局失败：%s", target)
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
