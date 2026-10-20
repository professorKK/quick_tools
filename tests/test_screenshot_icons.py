from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from quicktools.plugins.screenshot.ui.icons import (
    ICON_NAMES,
    IconSet,
    render_icon,
    render_tile,
)


@pytest.mark.parametrize("name", sorted(ICON_NAMES))
def test_every_icon_renders_non_empty(name: str) -> None:
    image = render_icon(name, 24, "#000000")
    assert image.mode == "RGBA"
    assert image.size == (24, 24)
    assert image.getbbox() is not None


def test_unknown_icon_raises_key_error() -> None:
    with pytest.raises(KeyError):
        render_icon("does-not-exist")


def test_icon_color_changes_pixels() -> None:
    dark = render_icon("camera", 24, "#000000")
    red = render_icon("camera", 24, "#ff0000")
    assert dark.tobytes() != red.tobytes()


def test_tile_has_transparent_corners() -> None:
    tile = render_tile(
        "camera", size=48, bg="#e8f0fe", fg="#2563eb", radius=12
    )
    assert tile.size == (48, 48)
    assert tile.mode == "RGBA"
    assert tile.getpixel((0, 0))[3] == 0
    assert tile.getpixel((24, 24))[3] == 255


@pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)
def test_icon_set_caches_photo_images() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        icons = IconSet(root)
        first = icons.get("home", 18, "#111111")
        second = icons.get("home", 18, "#111111")
        other = icons.get("home", 18, "#ff0000")
        assert first is second
        assert first is not other
        tile = icons.tile("camera", size=40, bg="#eeeeee", fg="#333333")
        assert tile is icons.tile(
            "camera", size=40, bg="#eeeeee", fg="#333333"
        )
        icons.clear()
        assert icons.get("home", 18, "#111111") is not first
    finally:
        root.destroy()
