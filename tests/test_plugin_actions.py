from __future__ import annotations

import json
import os
import queue
import sys
import tkinter as tk
from pathlib import Path

import pytest

from quicktools import launcher as launcher_module
from quicktools.launcher import Launcher
from quicktools.plugin_api import PluginBase, PluginContext
from quicktools.plugin_loader import PluginLoader


class DummyPlugin(PluginBase):
    def create_ui(self, window) -> None:
        pass


def context(tmp_path: Path) -> PluginContext:
    return PluginContext(
        root=None,
        plugin_id="dummy",
        plugin_dir=tmp_path,
        data_dir=tmp_path,
    )


def test_plugin_context_actions_are_optional(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert ctx.actions is None


def test_default_handle_action_is_noop(tmp_path: Path) -> None:
    plugin = DummyPlugin(context(tmp_path))
    assert plugin.handle_action("unknown") is None


pytestmark_display = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)

PLUGIN_SOURCE = """
from pathlib import Path
from quicktools.plugin_api import PluginBase

class ActionPlugin(PluginBase):
    def create_ui(self, window):
        pass

    def _log(self, value):
        path = Path(self.context.data_dir) / "calls.txt"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(value + "\\n")

    def start_service(self):
        self._log("start")

    def stop_service(self):
        self._log("stop")

    def handle_action(self, action):
        self._log("action:" + action)
"""


class FakeSettings:
    class Hotkey:
        def display(self):
            return "Ctrl+Alt+Space"

    hotkey = Hotkey()


class FakeApp:
    def __init__(self, loader: PluginLoader) -> None:
        self.loader = loader
        self.commands: queue.Queue[str] = queue.Queue()
        self.settings = FakeSettings()

    def apply_window_icon(self, _window) -> None:
        pass

    def hotkey_status_text(self) -> str:
        return "hotkey running"

    def hotkey_status_warning(self) -> bool:
        return False

    def open_settings(self) -> None:
        pass

    def hide_for_capture(self):
        return self.launcher.hide_all_windows()


def write_plugin(root: Path, folder: str, *, background: bool) -> Path:
    plugin_dir = root / folder
    plugin_dir.mkdir(parents=True)
    manifest = {
        "api_version": 1,
        "id": folder,
        "name": f"Plugin {folder}",
        "description": "action test",
        "version": "1.0.0",
        "entry": "plugin.py",
        "class": "ActionPlugin",
        "background": background,
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    return plugin_dir


@pytestmark_display
def test_dispatch_action_and_hide_restore(tmp_path: Path, monkeypatch) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    data_root = tmp_path / "plugin_data"
    data_root.mkdir()
    write_plugin(user, "bg", background=True)
    write_plugin(user, "normal", background=False)
    monkeypatch.setattr(
        launcher_module.paths,
        "plugin_data_dir",
        lambda plugin_id: data_root / plugin_id,
    )

    loader = PluginLoader(user_plugins=user, builtin_plugins=builtin)
    root = tk.Tk()
    root.withdraw()
    app = FakeApp(loader)
    launcher = Launcher(app, root)
    app.launcher = launcher
    extra = None
    try:
        calls = data_root / "bg" / "calls.txt"
        assert calls.read_text(encoding="utf-8").splitlines() == ["start"]

        assert launcher.dispatch_plugin_action("bg", "capture_region")
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "start",
            "action:capture_region",
        ]
        assert not launcher.dispatch_plugin_action("normal", "capture_region")
        assert not launcher.dispatch_plugin_action("missing", "capture_region")

        launcher.window.deiconify()
        extra = tk.Toplevel(root)
        extra.deiconify()
        launcher._plugin_windows["dummy"] = extra
        root.update()
        assert launcher.window.state() == "normal"
        assert extra.state() == "normal"

        restore = launcher.hide_all_windows()
        root.update()
        assert launcher.window.state() == "withdrawn"
        assert extra.state() == "withdrawn"

        restore()
        restore()
        root.update()
        assert launcher.window.state() == "normal"
        assert extra.state() == "normal"
    finally:
        if extra is not None:
            try:
                extra.destroy()
            except tk.TclError:
                pass
        try:
            launcher.stop_background_plugins()
        except Exception:
            pass
        try:
            launcher.window.destroy()
        except tk.TclError:
            pass
        root.destroy()

    assert calls.read_text(encoding="utf-8").splitlines() == [
        "start",
        "action:capture_region",
        "stop",
    ]
