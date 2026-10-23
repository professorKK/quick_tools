from __future__ import annotations

import os
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest

from quicktools import PROJECT_URL, paths
from quicktools.config import HotkeySpec
from quicktools.settings_ui import SettingsWindow

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


class FakeApp:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            hotkey=HotkeySpec.default(), first_run_seen=True
        )

    def hotkey_status_text(self) -> str:
        return "全局快捷键已启用"

    def hotkey_status_warning(self) -> bool:
        return False

    def current_plugin_data_root(self):
        return paths.default_plugin_data_root()

    def reload_plugins(self):
        return 3, []

    def set_hotkey(self, _spec):
        return True, ""

    def begin_hotkey_capture(self) -> None:
        pass

    def cancel_hotkey_capture(self) -> None:
        pass

    def settings_closed(self, _window) -> None:
        pass

    def quit(self) -> None:
        pass


def test_footer_stays_visible_and_content_scrolls() -> None:
    root = tk.Tk()
    root.withdraw()
    window = SettingsWindow(FakeApp(), root)
    try:
        window.update()
        assert window._quit_button.winfo_ismapped()
        canvas = window._settings_scroll.canvas
        bbox = canvas.bbox("all")
        assert bbox is not None
        assert bbox[3] > canvas.winfo_height()

        # The old fixed 700x780 layout clipped the footer on small screens;
        # shrinking to the minimum size must still keep it reachable.
        window.geometry("620x560")
        window.update()
        assert window._quit_button.winfo_ismapped()
        assert not window._copy_plugin_errors_button._enabled
    finally:
        window.destroy()
        root.destroy()


def test_footer_project_link_is_visible_and_clickable(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        "quicktools.settings_ui.open_url",
        lambda url: opened.append(url) or True,
    )
    root = tk.Tk()
    root.withdraw()
    window = SettingsWindow(FakeApp(), root)
    try:
        window.update()
        assert window.project_link.cget("text") == PROJECT_URL
        assert window.project_link.cget("cursor") == "hand2"
        assert window.project_link.winfo_ismapped()

        # The link must remain reachable at the minimum window size.
        window.geometry("620x560")
        window.update()
        assert window.project_link.winfo_ismapped()
        assert window.project_link.winfo_width() > 100
        assert window._quit_button.winfo_ismapped()

        window.project_link.invoke()
        assert opened == [PROJECT_URL]

        # A real click (press + release) must open the link as well.
        window.project_link.event_generate("<Button-1>")
        window.project_link.event_generate("<ButtonRelease-1>")
        window.update()
        assert opened == [PROJECT_URL, PROJECT_URL]

        # Hovering shows the underline affordance.
        window.project_link.event_generate("<Enter>")
        window.update()
        assert "underline" in str(window.project_link.cget("font"))
    finally:
        window.destroy()
        root.destroy()


def test_project_link_falls_back_to_manual_hint(monkeypatch) -> None:
    monkeypatch.setattr(
        "quicktools.settings_ui.open_url", lambda _url: False
    )
    root = tk.Tk()
    root.withdraw()
    window = SettingsWindow(FakeApp(), root)
    shown: list[tuple[str, str]] = []
    try:
        monkeypatch.setattr(
            window,
            "_show_error",
            lambda title, message: shown.append((title, message)),
        )
        window.project_link.invoke()
        assert shown
        assert PROJECT_URL in shown[0][1]
    finally:
        window.destroy()
        root.destroy()
