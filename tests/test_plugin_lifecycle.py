from __future__ import annotations

import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path

import pytest

from quicktools import launcher as launcher_module
from quicktools.launcher import Launcher
from quicktools.plugin_loader import PluginLoader
from quicktools.window_state import WindowStateStore

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


PLUGIN_SOURCE = """
from pathlib import Path
from quicktools.plugin_api import PluginBase

class BgPlugin(PluginBase):
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

    def on_window_shown(self, window):
        path = Path(self.context.data_dir) / "shown.txt"
        with path.open("a", encoding="utf-8") as handle:
            handle.write("shown\\n")
"""


def write_plugin(root: Path, folder: str, *, background: bool) -> Path:
    plugin_dir = root / folder
    plugin_dir.mkdir(parents=True)
    manifest = {
        "api_version": 1,
        "id": folder,
        "name": f"Plugin {folder}",
        "description": "lifecycle test",
        "version": "1.0.0",
        "entry": "plugin.py",
        "class": "BgPlugin",
        "background": background,
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (plugin_dir / "plugin.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    return plugin_dir


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


def test_background_plugin_starts_once_and_stops(
    tmp_path: Path, monkeypatch
) -> None:
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
    launcher = Launcher(
        FakeApp(loader),
        root,
        window_states=WindowStateStore(tmp_path / "window_state.json"),
    )
    try:
        calls = data_root / "bg" / "calls.txt"
        assert calls.read_text(encoding="utf-8").splitlines() == ["start"]
        assert not (data_root / "normal").exists()

        # Rescanning must not start a second background instance.
        launcher.reload_plugins()
        launcher.reload_plugins()
        assert calls.read_text(encoding="utf-8").splitlines() == ["start"]

        # Opening the window reuses the background instance and does not
        # start the service again.
        meta = next(meta for meta in launcher.plugins if meta.id == "bg")
        launcher.open_plugin(meta)
        root.update()
        assert "bg" in launcher._plugin_windows
        plugin_window = launcher._plugin_windows["bg"]
        assert int(plugin_window.overrideredirect()) == 1
        assert getattr(plugin_window, "quicktools_frame", None) is not None
        assert plugin_window.quicktools_frame.settings_button is not None
        launcher.open_plugin(meta)
        root.update()
        assert calls.read_text(encoding="utf-8").splitlines() == ["start"]
        # Both the first presentation and the re-focus of the existing window
        # run the optional on_window_shown hook.
        time.sleep(0.05)
        root.update()
        shown = data_root / "bg" / "shown.txt"
        assert shown.read_text(encoding="utf-8").splitlines() == [
            "shown",
            "shown",
        ]
        launcher._close_plugin("bg", launcher._plugin_windows.pop("bg"))
        root.update()

        launcher.stop_background_plugins()
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "start",
            "stop",
        ]

        # Stop is idempotent.
        launcher.stop_background_plugins()
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "start",
            "stop",
        ]
    finally:
        try:
            launcher.stop_background_plugins()
        except Exception:
            pass
        try:
            launcher.window.destroy()
        except tk.TclError:
            pass
        root.destroy()


def test_explicit_plugin_data_root_and_suspend(
    tmp_path: Path, monkeypatch
) -> None:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    write_plugin(user, "bg", background=True)
    loader = PluginLoader(user_plugins=user, builtin_plugins=builtin)
    root = tk.Tk()
    root.withdraw()
    custom_root = tmp_path / "custom-root"
    launcher = Launcher(
        FakeApp(loader),
        root,
        window_states=WindowStateStore(tmp_path / "window_state.json"),
        plugin_data_root=custom_root,
    )
    try:
        calls = custom_root / "bg" / "calls.txt"
        assert calls.read_text(encoding="utf-8").splitlines() == ["start"]

        launcher.suspend_plugins_for_data_root_change()
        assert launcher.plugin_window_count() == 0
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "start",
            "stop",
        ]

        # Hotkey/tray activity during a migration must not restart services
        # inside the old data root.
        launcher.reload_plugins()
        meta = next(meta for meta in launcher.plugins if meta.id == "bg")
        assert launcher.dispatch_plugin_action("bg", "noop") is False
        launcher.open_plugin(meta)
        root.update()
        assert launcher.plugin_window_count() == 0
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "start",
            "stop",
        ]

        next_root = tmp_path / "next-root"
        launcher.set_plugin_data_root(next_root)
        launcher.resume_plugins()
        launcher.reload_plugins()
        next_calls = next_root / "bg" / "calls.txt"
        assert next_calls.read_text(encoding="utf-8").splitlines() == ["start"]
    finally:
        try:
            launcher.stop_background_plugins()
        except Exception:
            pass
        try:
            launcher.window.destroy()
        except tk.TclError:
            pass
        root.destroy()
