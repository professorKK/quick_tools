from __future__ import annotations

import os
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest

from quicktools import launcher as launcher_module
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


@pytest.fixture(autouse=True)
def fake_activation(monkeypatch):
    """Never call the real Win32 foreground API from these unit tests."""
    monkeypatch.setattr(launcher_module, "force_foreground", lambda _window: False)
    monkeypatch.setattr(launcher_module, "is_foreground", lambda _window: True)


@pytest.fixture()
def tools(tmp_path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    loader = PluginLoader(user_plugins=user, builtin_plugins=builtin)
    root = tk.Tk()
    root.withdraw()
    launcher = Launcher(FakeApp(loader), root)
    try:
        yield launcher, root
    finally:
        try:
            launcher.hide()
        except tk.TclError:
            pass
        try:
            launcher._set_auto_hide(False)
        except tk.TclError:
            pass
        try:
            launcher.window.destroy()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass


class JobRecorder:
    """Record after()/after_cancel() calls without running real timers."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, object]] = []
        self.cancelled: list[object] = []

    def after(self, delay: int, callback):
        job = f"job-{len(self.scheduled) + 1}"
        self.scheduled.append((delay, callback))
        return job

    def after_cancel(self, job) -> None:
        self.cancelled.append(job)


def arm(launcher: Launcher) -> None:
    launcher._had_focus = True
    launcher._set_auto_hide(True)


def record_hide(launcher: Launcher, monkeypatch) -> list[bool]:
    calls: list[bool] = []

    def fake_hide() -> None:
        launcher._set_auto_hide(False)
        calls.append(True)

    monkeypatch.setattr(launcher, "hide", fake_hide)
    return calls


def test_initial_state_is_disarmed(tools) -> None:
    launcher, _root = tools
    assert launcher._auto_hide is False
    assert launcher._auto_hide_job is None


def test_toplevel_binding_applies_to_child_widgets(tools) -> None:
    launcher, _root = tools
    assert str(launcher.window) in launcher.search_entry.bindtags()


def test_show_arms_only_when_requested(tools) -> None:
    launcher, _root = tools

    launcher.show()
    assert launcher._auto_hide is False

    launcher.show(auto_hide=True)
    assert launcher._auto_hide is True


def test_hide_disarms_and_cancels_pending_job(tools, monkeypatch) -> None:
    launcher, _root = tools
    recorder = JobRecorder()
    monkeypatch.setattr(launcher.window, "after", recorder.after)
    monkeypatch.setattr(launcher.window, "after_cancel", recorder.after_cancel)

    arm(launcher)
    launcher._on_launcher_focus_out()
    job = launcher._auto_hide_job
    assert job == "job-1"

    launcher.hide()
    assert launcher._auto_hide is False
    assert launcher._auto_hide_job is None
    assert recorder.cancelled == [job]


def test_toggle_arms_auto_hide_when_hidden(tools, monkeypatch) -> None:
    launcher, _root = tools
    calls: list[bool] = []

    def fake_show(*, auto_hide: bool = False) -> None:
        calls.append(auto_hide)

    monkeypatch.setattr(launcher, "show", fake_show)
    launcher.toggle()

    assert calls == [True]


def test_toggle_hides_when_visible(tools, monkeypatch) -> None:
    launcher, _root = tools
    monkeypatch.setattr(launcher.window, "winfo_viewable", lambda: True)
    calls = record_hide(launcher, monkeypatch)

    launcher.toggle()

    assert calls == [True]


def test_focus_out_schedules_only_when_armed(tools, monkeypatch) -> None:
    launcher, _root = tools
    recorder = JobRecorder()
    monkeypatch.setattr(launcher.window, "after", recorder.after)
    monkeypatch.setattr(launcher.window, "after_cancel", recorder.after_cancel)

    launcher._on_launcher_focus_out()
    assert recorder.scheduled == []

    arm(launcher)
    launcher._on_launcher_focus_out()
    assert recorder.scheduled == [
        (launcher_module._AUTO_HIDE_DELAY_MS, launcher._hide_if_clicked_outside)
    ]
    assert launcher._auto_hide_job == "job-1"

    # A second FocusOut reschedules instead of stacking jobs.
    launcher._on_launcher_focus_out()
    assert recorder.cancelled == ["job-1"]
    assert launcher._auto_hide_job == "job-2"
    assert len(recorder.scheduled) == 2


def test_focus_out_ignored_before_first_focus(tools, monkeypatch) -> None:
    launcher, _root = tools
    recorder = JobRecorder()
    monkeypatch.setattr(launcher.window, "after", recorder.after)
    launcher._set_auto_hide(True)
    launcher._auto_hide_requested = True

    launcher._on_launcher_focus_out()

    assert launcher._had_focus is False
    assert recorder.scheduled == []
    assert launcher._auto_hide_job is None


def test_outside_check_does_not_hide_before_first_focus(tools, monkeypatch) -> None:
    launcher, _root = tools
    calls = record_hide(launcher, monkeypatch)
    monkeypatch.setattr(launcher.window, "winfo_viewable", lambda: True)
    launcher._set_auto_hide(True)
    launcher._auto_hide_requested = True

    launcher._hide_if_clicked_outside()

    assert calls == []


def test_focus_in_rearms_after_a_failed_activation(tools, monkeypatch) -> None:
    launcher, _root = tools
    launcher._auto_hide_requested = True
    launcher._set_auto_hide(False)
    monkeypatch.setattr(launcher_module, "is_foreground", lambda _w: True)

    launcher._on_launcher_focus_in()

    assert launcher._had_focus is True
    assert launcher._auto_hide is True


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 activation check")
def test_failed_foreground_verification_disarms(tools, monkeypatch) -> None:
    launcher, root = tools
    monkeypatch.setattr(launcher_module, "is_foreground", lambda _w: False)
    launcher.window.deiconify()
    root.update()
    launcher._auto_hide_requested = True
    launcher._set_auto_hide(True)

    launcher._verify_foreground(len(launcher_module._FOCUS_RETRY_DELAYS_MS) - 1)

    assert launcher._had_focus is False
    assert launcher._auto_hide is False


def _focus_widget(widget):
    return lambda: widget


def _focus_none():
    return None


def _focus_raises():
    raise tk.TclError("no focus")


@pytest.mark.parametrize(
    ("armed", "viewable", "focus_factory", "expect_hide"),
    [
        (False, True, _focus_none, False),
        (True, False, _focus_none, False),
        (True, True, None, False),  # focus stays on the launcher's search box
        (True, True, _focus_none, True),
        (True, True, "child", False),
        (True, True, "transient", False),
        (True, True, _focus_raises, False),
    ],
)
def test_hide_if_clicked_outside(
    tools,
    monkeypatch,
    armed: bool,
    viewable: bool,
    focus_factory,
    expect_hide: bool,
) -> None:
    launcher, root = tools
    calls = record_hide(launcher, monkeypatch)
    monkeypatch.setattr(launcher.window, "winfo_viewable", lambda: viewable)

    if focus_factory == "child":
        child = tk.Toplevel(launcher.window)
        child.withdraw()
        factory = _focus_widget(child)
    elif focus_factory == "transient":
        dialog = tk.Toplevel(root)
        dialog.withdraw()
        dialog.transient(launcher.window)
        factory = _focus_widget(dialog)
    elif focus_factory is None:
        factory = _focus_widget(launcher.search_entry)
    else:
        factory = focus_factory
    monkeypatch.setattr(launcher.window, "focus_get", factory)
    if armed:
        arm(launcher)
    else:
        launcher._set_auto_hide(False)

    launcher._hide_if_clicked_outside()

    assert calls == ([True] if expect_hide else [])
    assert launcher._auto_hide_job is None


def test_hide_all_windows_disarms(tools) -> None:
    launcher, root = tools
    launcher.window.deiconify()
    root.update()
    arm(launcher)

    launcher.hide_all_windows()

    assert launcher._auto_hide is False


def test_open_plugin_failure_disarms_before_dialog(tools, monkeypatch) -> None:
    launcher, _root = tools
    shown: list[dict] = []
    monkeypatch.setattr(
        launcher, "_instance_for", lambda _meta: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        launcher_module.messagebox, "showerror", lambda *a, **kw: shown.append(kw)
    )
    arm(launcher)

    launcher.open_plugin(SimpleNamespace(id="broken", name="Broken"))

    assert launcher._auto_hide is False
    assert shown and shown[0]["parent"] is launcher.window
