from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from quicktools import x11_focus

pytestmark = pytest.mark.skipif(
    not (
        sys.platform.startswith("linux")
        and os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
    ),
    reason="X11 display required",
)


@pytest.fixture()
def root():
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


@pytest.fixture()
def restore_focus():
    """Put the X input focus back where the user had it."""
    try:
        from Xlib import display as xdisplay
    except Exception:
        pytest.skip("python-xlib unavailable")
    display = xdisplay.Display()
    previous = display.get_input_focus().focus
    try:
        yield
    finally:
        try:
            previous.set_input_focus(2, 0)
            display.sync()
        except Exception:
            pass
        display.close()


def _frameless(root: tk.Tk, x: int) -> tk.Toplevel:
    window = tk.Toplevel(root)
    window.overrideredirect(True)
    window.geometry(f"200x100+{x}+100")
    window.deiconify()
    return window


def test_force_foreground_moves_real_x11_focus(root, restore_focus) -> None:
    first = _frameless(root, 100)
    second = _frameless(root, 400)
    root.update()

    assert x11_focus.force_foreground(first) is True
    assert x11_focus.is_foreground(first) is True
    assert x11_focus.is_foreground(second) is False

    assert x11_focus.force_foreground(second) is True
    assert x11_focus.is_foreground(second) is True
    assert x11_focus.is_foreground(first) is False


def test_force_foreground_id_moves_real_x11_focus(root, restore_focus) -> None:
    first = _frameless(root, 100)
    second = _frameless(root, 400)
    root.update()

    assert x11_focus.force_foreground_id(first.winfo_id()) is True
    assert x11_focus.is_foreground_id(first.winfo_id()) is True
    assert x11_focus.is_foreground_id(second.winfo_id()) is False
    assert x11_focus.input_focus_id() is not None

    assert x11_focus.force_foreground_id(second.winfo_id()) is True
    assert x11_focus.is_foreground_id(second.winfo_id()) is True
    assert x11_focus.is_foreground_id(first.winfo_id()) is False


def test_managed_window_is_left_to_tk(root) -> None:
    window = tk.Toplevel(root)
    window.geometry("200x100+100+100")
    window.deiconify()
    root.update()

    assert x11_focus.force_foreground(window) is False


def test_wayland_disables_native_focus(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")

    assert x11_focus.supported() is False
    assert x11_focus.force_foreground(None) is False
    # Unverifiable: callers must keep their previous (pre-check) behaviour.
    assert x11_focus.is_foreground(None) is True
