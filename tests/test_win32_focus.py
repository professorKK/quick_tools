from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from quicktools import launcher as launcher_module
from quicktools import win32_focus
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
        return "hotkey running"

    def hotkey_status_warning(self) -> bool:
        return False

    def open_settings(self) -> None:
        pass


@pytest.fixture()
def launcher(tmp_path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    loader = PluginLoader(user_plugins=user, builtin_plugins=builtin)
    root = tk.Tk()
    root.withdraw()
    instance = Launcher(FakeApp(loader), root)
    try:
        yield instance
    finally:
        try:
            instance.window.destroy()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_force_foreground_is_windows_only(monkeypatch) -> None:
    monkeypatch.setattr(win32_focus.sys, "platform", "linux")
    root = tk.Tk()
    root.withdraw()
    window = tk.Toplevel(root)
    try:
        assert win32_focus.force_foreground(window) is False
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 handles only")
def test_force_foreground_finds_the_top_level_handle(launcher) -> None:
    handle = win32_focus._hwnd(launcher.window)
    assert handle > 0

    # Child widgets live below the same top-level window in the Win32
    # parent chain.
    user32 = win32_focus.ctypes.windll.user32
    user32.GetParent.argtypes = [win32_focus.wintypes.HWND]
    user32.GetParent.restype = win32_focus.wintypes.HWND
    current = int(launcher.search_entry.winfo_id())
    chain: list[int] = []
    while current:
        chain.append(current)
        parent = user32.GetParent(current)
        current = int(parent) if parent else 0
    assert handle in chain


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 activation only")
def test_activate_window_survives_activation_failure(launcher, monkeypatch) -> None:
    forced: list[bool] = []

    def boom(_window):
        raise OSError("activation failed")

    monkeypatch.setattr(launcher_module, "force_foreground", boom)
    monkeypatch.setattr(
        launcher.window, "focus_force", lambda: forced.append(True)
    )

    launcher._activate_window()

    assert forced == [True]


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 activation only")
def test_activate_window_delegates_to_win32_helper(launcher, monkeypatch) -> None:
    calls: list[object] = []

    monkeypatch.setattr(
        launcher_module, "force_foreground", lambda window: calls.append(window) or True
    )

    launcher._activate_window()

    assert calls == [launcher.window]
