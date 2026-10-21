from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path

import pytest

from quicktools.launcher import Launcher
from quicktools.plugin_loader import PluginLoader

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


class FakeApp:
    def __init__(self, loader: PluginLoader) -> None:
        self.loader = loader

    def apply_window_icon(self, _window) -> None:
        pass

    def hotkey_status_text(self) -> str:
        return "hotkey"

    def hotkey_status_warning(self) -> bool:
        return False

    def open_settings(self) -> None:
        pass


def write_plugin(root: Path, summary: str, description: str) -> None:
    folder = root / "compact"
    folder.mkdir()
    (folder / "plugin.json").write_text(
        json.dumps(
            {
                "api_version": 1,
                "id": "compact",
                "name": "紧凑插件",
                "summary": summary,
                "description": description,
                "version": "1.0.0",
                "entry": "plugin.py",
                "class": "CompactPlugin",
                "icon": "C",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (folder / "plugin.py").write_text(
        "from quicktools.plugin_api import PluginBase\n"
        "class CompactPlugin(PluginBase):\n"
        "    def create_ui(self, window):\n"
        "        pass\n",
        encoding="utf-8",
    )


def card_labels(widget: tk.Misc) -> list[str]:
    labels: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            labels.append(str(child.cget("text")))
        labels.extend(card_labels(child))
    return labels


def test_card_shows_only_summary_not_full_description(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    summary = "一句话概述"
    description = "这是一段很长的详细说明，不应该出现在启动器卡片里。" * 4
    write_plugin(user, summary, description)
    root = tk.Tk()
    root.withdraw()
    try:
        launcher = Launcher(FakeApp(PluginLoader(user, builtin)), root)
        launcher.show()
        root.update()
        assert int(launcher.window.overrideredirect()) == 1
        assert len(launcher._cards) == 1
        labels = card_labels(launcher._cards[0])
        assert "紧凑插件" in labels
        assert summary in labels
        assert all(description not in text for text in labels)
        assert launcher._cards[0].winfo_reqheight() < 90
        assert launcher._scrollbar_visible is False
        launcher.hide()
    finally:
        root.destroy()
