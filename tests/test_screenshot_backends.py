from __future__ import annotations

import os
import sys

import pytest

from quicktools.plugins.screenshot.capture import create_backend, is_wayland_session
from quicktools.plugins.screenshot.models import CaptureUnavailable


@pytest.mark.skipif(sys.platform == "win32", reason="Linux backend selection")
def test_backend_without_display(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    backend = create_backend()
    assert not backend.status.available
    with pytest.raises(CaptureUnavailable):
        backend.grab_screen()


@pytest.mark.skipif(sys.platform == "win32", reason="Linux backend selection")
def test_wayland_backend_reports_portal_limitations(monkeypatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert is_wayland_session()
    backend = create_backend()
    assert backend.name == "wayland"
    capabilities = backend.capabilities()
    assert not capabilities.custom_overlay
    assert capabilities.interactive_portal
    assert capabilities.freeform
    assert not capabilities.scrolling


@pytest.mark.skipif(sys.platform == "win32", reason="X11 text decoding")
def test_x11_text_property_decoding() -> None:
    pytest.importorskip("Xlib")
    from quicktools.plugins.screenshot.capture.x11 import _decode_text_property

    # ICCCM STRING 是 Latin-1，UTF8_STRING 才是 UTF-8。
    assert _decode_text_property(b"images", "STRING") == "images"
    assert _decode_text_property(b"caf\xe9", "STRING") == "café"
    assert _decode_text_property("微信".encode(), "UTF8_STRING") == "微信"
    assert _decode_text_property("微信".encode(), "COMPOUND_TEXT") == "微信"
    assert _decode_text_property(b"  hi\x00 ", "UTF8_STRING") == "hi"
    assert _decode_text_property(b"", "UTF8_STRING") == ""
    assert _decode_text_property(None, "UTF8_STRING") == ""


@pytest.mark.skipif(sys.platform == "win32", reason="X11 text decoding")
def test_x11_window_title_prefers_net_wm_name(monkeypatch) -> None:
    pytest.importorskip("Xlib")
    from quicktools.plugins.screenshot.capture.x11 import X11Backend

    class _Prop:
        def __init__(self, value, property_type: int) -> None:
            self.value = value
            self.property_type = property_type

    backend = object.__new__(X11Backend)
    properties = {
        "_NET_WM_NAME": _Prop("微信".encode(), 1),
        "WM_NAME": _Prop("微信标题".encode(), 1),
    }
    monkeypatch.setattr(
        backend, "_property", lambda _window, name: properties.get(name)
    )
    monkeypatch.setattr(
        backend,
        "_atom_name",
        lambda atom: "UTF8_STRING" if atom == 1 else "COMPOUND_TEXT",
    )
    assert backend._window_title(object()) == "微信"

    # 没有 _NET_WM_NAME 时退回 WM_NAME。
    properties.pop("_NET_WM_NAME")
    assert backend._window_title(object()) == "微信标题"


@pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get("DISPLAY"),
    reason="X11 display required",
)
def test_x11_backend_smoke(monkeypatch) -> None:
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    backend = create_backend()
    try:
        assert backend.name == "x11"
        assert backend.status.available
        assert backend.screens()
        captured = backend.grab_screen()
        assert captured.image.width > 0
        assert captured.image.height > 0
        assert isinstance(backend.list_windows(), list)
        assert backend.cursor_position() is not None
    finally:
        backend.close()
