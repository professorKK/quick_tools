from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from quicktools.ui_theme import pick_fonts
from quicktools.window_pin import PinButton

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
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


def test_pin_toggles_topmost(root: tk.Tk) -> None:
    window = tk.Toplevel(root)
    window.withdraw()
    pin = PinButton(window, window, pick_fonts(window))
    pin.pack()

    assert pin.pinned is False
    pin.toggle()
    root.update()
    assert pin.pinned is True
    assert int(window.attributes("-topmost")) == 1

    pin.toggle()
    root.update()
    assert pin.pinned is False
    assert int(window.attributes("-topmost")) == 0


def test_refresh_reads_external_topmost_change(root: tk.Tk) -> None:
    window = tk.Toplevel(root)
    window.withdraw()
    pin = PinButton(window, window, pick_fonts(window))
    pin.pack()

    window.attributes("-topmost", True)
    pin.refresh()
    assert pin.pinned is True
    assert pin._active is True
