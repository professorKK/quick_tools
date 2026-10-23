from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from quicktools.config import HotkeySpec
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


class FirstRunApp(FakeApp):
    def __init__(self, loader: PluginLoader) -> None:
        super().__init__(loader)
        self.settings = SimpleNamespace(
            hotkey=HotkeySpec(("alt",), "space"), first_run_seen=False
        )
        self.marked = 0

    def mark_first_run_seen(self) -> None:
        self.settings.first_run_seen = True
        self.marked += 1


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


def _meta(plugin_id: str, name: str, folder: Path) -> "PluginMeta":
    from quicktools.plugin_api import PluginMeta

    return PluginMeta(
        id=plugin_id,
        name=name,
        description="支持图片与截图",
        summary="图片与截图工具",
        version="1.0.0",
        entry="plugin.py",
        class_name="P",
        folder=folder,
    )


def test_keyboard_selection_and_enter_open_the_highlighted_card(
    tmp_path: Path,
) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    root = tk.Tk()
    root.withdraw()
    try:
        launcher = Launcher(FakeApp(PluginLoader(user, builtin)), root)
        launcher.plugins = [
            _meta("one", "图片一", tmp_path),
            _meta("two", "图片二", tmp_path),
        ]
        launcher.search_var.set("图")
        launcher._refresh_cards()
        root.update()
        assert launcher._selected_card_index == 0

        opened: list[str] = []
        launcher.open_plugin = lambda meta: opened.append(meta.id)
        launcher._on_search_enter()
        assert opened == ["one"]

        launcher._move_selection(1)
        launcher._on_search_enter()
        assert opened == ["one", "two"]
        launcher.hide()
    finally:
        root.destroy()


def test_escape_clears_search_before_hiding(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    root = tk.Tk()
    root.withdraw()
    try:
        launcher = Launcher(FakeApp(PluginLoader(user, builtin)), root)
        launcher.plugins = [_meta("one", "图片一", tmp_path)]
        launcher.search_var.set("图")
        launcher._refresh_cards()
        hidden: list[bool] = []
        launcher.hide = lambda: hidden.append(True)

        launcher._on_escape()
        assert launcher.search_var.get() == ""
        assert hidden == []

        launcher._on_escape()
        assert hidden == [True]
    finally:
        root.destroy()


def test_first_run_hint_is_shown_once(tmp_path: Path) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    root = tk.Tk()
    root.withdraw()
    try:
        app = FirstRunApp(PluginLoader(user, builtin))
        launcher = Launcher(app, root)
        launcher.show()
        root.update()
        assert launcher._first_run_hint is not None
        assert "Alt+Space" in " ".join(
            child.cget("text")
            for child in launcher._first_run_hint.winfo_children()
            if isinstance(child, tk.Label)
        )

        launcher._dismiss_first_run_hint()
        root.update()
        assert launcher._first_run_hint is None
        assert app.marked == 1
        assert app.settings.first_run_seen is True

        launcher.show()
        root.update()
        assert launcher._first_run_hint is None
        launcher.hide()
    finally:
        root.destroy()
