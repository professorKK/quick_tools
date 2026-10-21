from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from quicktools.settings_widgets import Card, ToggleSwitch

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


@pytest.fixture()
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    window.geometry("420x260+80+80")
    window.update()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


def test_toggle_switch_updates_boolean_variable(root: tk.Tk) -> None:
    variable = tk.BooleanVar(value=False)
    switch = ToggleSwitch(root, variable)
    switch.pack()
    root.update()

    assert switch._value is False
    switch._on_click()
    root.update()
    assert variable.get() is True
    assert switch._value is True

    variable.set(False)
    root.update()
    assert switch._value is False


def test_card_paints_rounded_background_and_shadow(root: tk.Tk) -> None:
    card = Card(root)
    card.pack(fill="x", padx=20, pady=20)
    tk.Label(card.body, text="内容", bg="#ffffff").pack(anchor="w")
    root.update()

    assert card.body.winfo_ismapped()
    # Shadow layers + border + fill are drawn on the decorative canvas.
    assert len(card._canvas.find_all()) >= 3
    width = card.winfo_width()
    assert width > 0
