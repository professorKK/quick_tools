from __future__ import annotations

import sys

import pytest

from quicktools.plugins.gp.input_mode import (
    UnsupportedInputMode,
    WindowsInputMode,
    X11InputMode,
    _is_wayland_session,
    create_input_mode,
)


def test_factory_offscreen_is_unsupported() -> None:
    assert isinstance(create_input_mode("offscreen"), UnsupportedInputMode)


def test_factory_wayland_is_unsupported(monkeypatch) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    mode = create_input_mode("wayland")
    assert isinstance(mode, UnsupportedInputMode)


def test_factory_x11_selects_x11_mode(monkeypatch) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("X11 模式只在 Linux 上选择")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    assert isinstance(create_input_mode("xcb"), X11InputMode)


def test_factory_xwayland_is_unsupported(monkeypatch) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("XWayland 判定只在 Linux 上有意义")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert isinstance(create_input_mode("xcb"), UnsupportedInputMode)


def test_factory_windows_selects_windows_mode(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(create_input_mode("windows"), WindowsInputMode)


def test_factory_without_display_is_unsupported(monkeypatch) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("DISPLAY 检查只在 Linux 上有意义")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    assert isinstance(create_input_mode("xcb"), UnsupportedInputMode)


def test_wayland_session_detection(monkeypatch) -> None:
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert _is_wayland_session() is False

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert _is_wayland_session() is True

    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert _is_wayland_session() is True


def test_unsupported_mode_is_safe() -> None:
    mode = UnsupportedInputMode()
    assert mode.supported() is False
    assert mode.shift_down() is False
    # 不支持时没有原生状态可应用，no-op 视为成功。
    assert mode.set_click_through(None, True) is True
    mode.close()
    mode.close()


def test_windows_mode_is_unsupported_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows 上会加载 user32")
    assert WindowsInputMode().supported() is False
