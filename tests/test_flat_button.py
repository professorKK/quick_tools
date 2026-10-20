from __future__ import annotations

import os
import tkinter as tk

import pytest

from quicktools.ui_theme import FlatButton, pick_fonts

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="Tkinter UI test needs a display"
)


@pytest.fixture()
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    window.withdraw()
    yield window
    window.destroy()


def test_release_without_press_does_not_fire(root) -> None:
    calls: list[int] = []
    button = FlatButton(
        root,
        "+",
        lambda: calls.append(1),
        fonts=pick_fonts(root),
    )
    # A launcher card opens a window on ButtonPress; the matching release can
    # land on a button in the new window without a preceding press there.
    button._on_release()
    assert calls == []

    button._on_click()
    button._on_release()
    assert calls == [1]


def test_leave_cancels_a_pending_press(root) -> None:
    calls: list[int] = []
    button = FlatButton(
        root,
        "+",
        lambda: calls.append(1),
        fonts=pick_fonts(root),
    )
    button._on_click()
    button._on_leave()
    button._on_release()
    assert calls == []


def test_set_idle_colors_updates_idle_and_hover(root) -> None:
    button = FlatButton(
        root,
        "×",
        lambda: None,
        fonts=pick_fonts(root),
        bg="#111111",
        hover_bg="#222222",
    )
    button.set_idle_colors(
        bg="#333333",
        fg="#555555",
        hover_bg="#444444",
        press_bg="#666666",
    )
    assert button.cget("bg").lower() == "#333333"
    assert button.cget("fg").lower() == "#555555"

    button._on_enter()
    assert button.cget("bg").lower() == "#444444"
    button._on_leave()
    assert button.cget("bg").lower() == "#333333"
