from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path

import pytest

from quicktools.launcher import Launcher
from quicktools.plugin_loader import PluginLoader
from quicktools.window_state import WindowState, WindowStateStore

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)

PLUGIN_SOURCE = """
import tkinter as tk

from quicktools.plugin_api import PluginBase


class SizedPlugin(PluginBase):
    def create_ui(self, window):
        window.geometry("640x520+200+150")
        window.minsize(420, 360)
        tk.Frame(window, width=120, height=80).pack()
"""


class FakeApp:
    def __init__(self, loader: PluginLoader) -> None:
        self.loader = loader

    def apply_window_icon(self, _window) -> None:
        pass

    def hotkey_status_text(self) -> str:
        return "hotkey running"

    def hotkey_status_warning(self) -> bool:
        return False

    def open_settings(self) -> None:
        pass


def write_plugin(root: Path) -> None:
    folder = root / "sized"
    folder.mkdir()
    (folder / "plugin.json").write_text(
        json.dumps(
            {
                "api_version": 1,
                "id": "sized",
                "name": "尺寸测试插件",
                "description": "window state test",
                "version": "1.0.0",
                "entry": "plugin.py",
                "class": "SizedPlugin",
            }
        ),
        encoding="utf-8",
    )
    (folder / "plugin.py").write_text(PLUGIN_SOURCE, encoding="utf-8")


def open_and_show(launcher: Launcher, meta):
    launcher.open_plugin(meta)
    launcher.root.update()
    window = launcher._plugin_windows[meta.id]
    launcher._show_plugin_window(window)
    launcher.root.update()
    return window


def test_plugin_window_size_survives_close_and_reopen(
    tmp_path: Path,
) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    write_plugin(user)

    state_path = tmp_path / "window_state.json"
    loader = PluginLoader(user_plugins=user, builtin_plugins=builtin)
    root = tk.Tk()
    root.withdraw()
    launcher = Launcher(
        FakeApp(loader),
        root,
        window_states=WindowStateStore(state_path),
    )
    try:
        meta = next(meta for meta in launcher.plugins if meta.id == "sized")
        window = open_and_show(launcher, meta)
        window.geometry("700x580")
        root.update()

        launcher._close_plugin("sized", window)
        root.update()

        assert WindowStateStore(state_path).get("sized") == WindowState(
            700, 580
        )

        reopened = open_and_show(launcher, meta)
        assert reopened.winfo_width() == 700
        assert reopened.winfo_height() == 580

        # The application exit path writes the size without waiting for the
        # window to be closed first.
        reopened.geometry("730x590")
        root.update()
        launcher.flush_window_states()
        assert WindowStateStore(state_path).get("sized") == WindowState(
            730, 590
        )

        # A window closed while maximized reopens maximized, but the saved
        # normal size stays the pre-maximize size.
        reopened.quicktools_frame.maximize()
        root.update()
        assert reopened.quicktools_frame.maximized is True
        launcher._close_plugin("sized", reopened)
        root.update()
        assert WindowStateStore(state_path).get("sized") == WindowState(
            730, 590, maximized=True
        )

        maximized = open_and_show(launcher, meta)
        assert maximized.quicktools_frame.maximized is True
    finally:
        try:
            launcher.stop_background_plugins()
        except Exception:
            pass
        try:
            launcher.window.destroy()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass
