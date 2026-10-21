"""Persist plugin window sizes across launches.

Each plugin window is identified by its manifest ``id``.  Only the outer
window size and whether it was maximized are stored; the position is
recomputed when the window opens so a monitor change cannot leave a window
off-screen.  The file is separate from ``settings.json`` so plugin state and
application settings can evolve independently.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

STATE_VERSION = 1
MIN_TRACKED_SIZE = 100
MAX_TRACKED_SIZE = 20000


@dataclass(frozen=True)
class WindowState:
    width: int
    height: int
    maximized: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "maximized": self.maximized,
        }

    @classmethod
    def from_mapping(cls, data: Any) -> "WindowState | None":
        if not isinstance(data, dict):
            return None
        width = data.get("width")
        height = data.get("height")
        if not isinstance(width, int) or isinstance(width, bool):
            return None
        if not isinstance(height, int) or isinstance(height, bool):
            return None
        if not MIN_TRACKED_SIZE <= width <= MAX_TRACKED_SIZE:
            return None
        if not MIN_TRACKED_SIZE <= height <= MAX_TRACKED_SIZE:
            return None
        maximized = data.get("maximized", False)
        if not isinstance(maximized, bool):
            maximized = False
        return cls(width, height, maximized)


class WindowStateStore:
    """Small JSON-backed map of ``plugin id -> WindowState``."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else paths.window_state_file()
        self._states: dict[str, WindowState] = {}
        self._dirty = False
        self._load()

    def get(self, plugin_id: str) -> WindowState | None:
        return self._states.get(plugin_id)

    def set(
        self,
        plugin_id: str,
        width: int,
        height: int,
        *,
        maximized: bool = False,
    ) -> bool:
        """Store a size and return ``True`` when it actually changed."""
        if not plugin_id:
            return False
        state = WindowState.from_mapping(
            {
                "width": width,
                "height": height,
                "maximized": maximized,
            }
        )
        if state is None or self._states.get(plugin_id) == state:
            return False
        self._states[plugin_id] = state
        self._dirty = True
        return True

    def save(self) -> bool:
        """Write pending changes atomically. Failures never break the UI."""
        if not self._dirty:
            return False
        payload = {
            "version": STATE_VERSION,
            "windows": {
                plugin_id: state.to_mapping()
                for plugin_id, state in sorted(self._states.items())
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            )
            temp_path = Path(handle.name)
            with handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except OSError as exc:
            log.warning("保存插件窗口大小失败：%s", exc)
            return False
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        self._dirty = False
        return True

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return
        except Exception as exc:
            log.warning("读取插件窗口大小失败，使用默认值：%s", exc)
            return
        if not isinstance(data, dict):
            log.warning("插件窗口大小配置格式错误，使用默认值")
            return
        windows = data.get("windows")
        if not isinstance(windows, dict):
            log.warning("插件窗口大小配置缺少 windows 节点，使用默认值")
            return
        for plugin_id, raw in windows.items():
            if not isinstance(plugin_id, str) or not plugin_id:
                continue
            state = WindowState.from_mapping(raw)
            if state is not None:
                self._states[plugin_id] = state
