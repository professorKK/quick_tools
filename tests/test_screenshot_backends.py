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
