from __future__ import annotations

import os
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest

from quicktools.ui_theme import pick_fonts
from quicktools.window_frame import RESIZE_INTERVAL_MS, Tooltip, WindowFrame

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


def make_frame(root: tk.Tk, **kwargs) -> tuple[tk.Toplevel, WindowFrame]:
    window = tk.Toplevel(root)
    window.withdraw()
    window.geometry("520x360+120+120")
    kwargs.setdefault("on_settings", lambda: None)
    frame = WindowFrame(
        window,
        title="测试窗口",
        icon="T",
        fonts=pick_fonts(window),
        **kwargs,
    )
    tk.Label(window, text="正文").pack(fill="both", expand=True)
    window.deiconify()
    root.update()
    return window, frame


def test_title_bar_has_expected_buttons(root: tk.Tk) -> None:
    window, frame = make_frame(root)
    try:
        assert frame.title_label.cget("text") == "测试窗口"
        assert frame.settings_button is not None
        assert frame.pin_button is not None
        assert frame.minimize_button is not None
        assert frame.maximize_button is not None
        assert frame.close_button is not None
        assert int(window.overrideredirect()) == 1
    finally:
        window.destroy()


def test_pin_toggles_topmost_and_state(root: tk.Tk) -> None:
    window, frame = make_frame(root)
    try:
        assert frame.pinned is False
        assert frame.pin_button._active is False
        frame.pin_button._on_release()  # not pressed: no action
        assert frame.pinned is False
        frame.toggle_pin()
        root.update()
        assert frame.pinned is True
        assert frame.pin_button._active is True
        frame.toggle_pin()
        root.update()
        assert frame.pinned is False
        assert frame.pin_button._active is False
    finally:
        window.destroy()


def test_maximize_and_restore_round_trip(root: tk.Tk) -> None:
    window, frame = make_frame(root)
    try:
        original = window.geometry()
        assert frame.normal_size() == (520, 360)
        frame.maximize()
        root.update()
        assert frame.maximized is True
        assert frame.maximize_button._kind == "restore"
        # While maximized the window geometry is the work area; the saved
        # normal size must remain the pre-maximize size.
        assert frame.normal_size() == (520, 360)
        frame.restore()
        root.update()
        assert frame.maximized is False
        assert frame.maximize_button._kind == "maximize"
        assert window.geometry() == original
    finally:
        window.destroy()


def test_resize_motion_is_coalesced(root: tk.Tk, monkeypatch) -> None:
    window, frame = make_frame(root)
    try:
        scheduled: dict[str, object] = {}

        def fake_after(delay, callback=None, *args):
            scheduled["delay"] = delay
            scheduled["callback"] = callback
            return "resize-job"

        def fake_cancel(job):
            scheduled["cancelled"] = job

        monkeypatch.setattr(window, "after", fake_after)
        monkeypatch.setattr(window, "after_cancel", fake_cancel)
        geometry_calls: list[str] = []
        monkeypatch.setattr(
            window, "geometry", lambda value: geometry_calls.append(value)
        )

        grips = frame._grips
        assert grips is not None
        start_x = window.winfo_x()
        start_y = window.winfo_y()
        width = window.winfo_width()
        height = window.winfo_height()
        grips._on_press(
            SimpleNamespace(x_root=600, y_root=300), "e"
        )
        grips._on_motion(
            SimpleNamespace(x_root=550, y_root=300)
        )
        assert scheduled["delay"] == RESIZE_INTERVAL_MS
        assert geometry_calls == []

        # More motion before the timer fires must only keep the latest point.
        grips._on_motion(
            SimpleNamespace(x_root=520, y_root=300)
        )
        callback = scheduled["callback"]
        assert callable(callback)
        callback()
        expected_width = max(1, width - 80)
        assert geometry_calls == [
            f"{expected_width}x{height}+{start_x}+{start_y}"
        ]

        # Release applies any not-yet-flushed final position immediately.
        grips._on_motion(
            SimpleNamespace(x_root=500, y_root=300)
        )
        grips._on_release()
        assert scheduled.get("cancelled") == "resize-job"
        assert geometry_calls[-1] == (
            f"{max(1, width - 100)}x{height}+{start_x}+{start_y}"
        )
    finally:
        window.destroy()


def test_close_and_settings_callbacks(root: tk.Tk) -> None:
    settings_calls: list[bool] = []
    close_calls: list[bool] = []
    window, frame = make_frame(
        root,
        on_settings=lambda: settings_calls.append(True),
        on_close=lambda: close_calls.append(True),
    )
    try:
        frame.settings_button._on_release()  # not pressed: no action
        assert settings_calls == []
        frame.settings_button._on_press()
        frame.settings_button._on_release()
        assert settings_calls == [True]
        frame.close_button._on_press()
        frame.close_button._on_release()
        assert close_calls == [True]
    finally:
        window.destroy()


def test_tooltip_container_covers_child_widgets(root: tk.Tk) -> None:
    window = tk.Toplevel(root)
    window.withdraw()
    window.geometry("260x120+140+140")
    container = tk.Frame(window, bg="#ffffff")
    container.pack(fill="both", expand=True)
    title = tk.Label(container, text="容器标题", bg="#ffffff")
    title.pack()
    body = tk.Label(container, text="容器说明", bg="#ffffff")
    body.pack()
    tooltip = Tooltip(container, "悬停提示", container=container)
    try:
        window.deiconify()
        root.update()
        assert tooltip.container is container
        # Every child participates in the same hover target.
        for child in (container, title, body):
            assert child.bind("<Enter>")
            assert child.bind("<Leave>")
        tooltip.show()
        root.update()
        assert tooltip._tip is not None
        assert tooltip._tip.winfo_exists()
        tooltip.hide()
        assert tooltip._tip is None
    finally:
        tooltip.hide()
        window.destroy()


def test_dialog_mode_hides_window_actions(root: tk.Tk) -> None:
    window = tk.Toplevel(root)
    window.withdraw()
    frame = WindowFrame(
        window,
        title="对话框",
        icon="D",
        dialog=True,
        pin=False,
        minimize=False,
        maximize=False,
        on_close=window.destroy,
    )
    try:
        assert frame.settings_button is None
        assert frame.pin_button is None
        assert frame.minimize_button is None
        assert frame.maximize_button is None
        assert frame.close_button is not None
    finally:
        window.destroy()
