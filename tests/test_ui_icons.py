from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from quicktools import icon_font, ui_icons
from quicktools.ui_theme import Fonts, pick_fonts

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
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


def test_symbol_glyphs_use_material_icons_codepoints() -> None:
    assert ui_icons.SYMBOL_GLYPHS == {
        "pin": "\uf10d",  # push_pin
        "settings": "\ue8b8",
        "about": "\ue88f",  # info_outline
    }


@pytest.mark.skipif(
    not (sys.platform == "win32" or sys.platform.startswith("linux")),
    reason="bundled font loader supports Windows/Linux",
)
def test_bundled_icon_font_loads() -> None:
    assert icon_font.font_path().is_file()
    assert icon_font.ensure_loaded() == icon_font.FAMILY


def test_pick_fonts_prefers_bundled_icon_font(root) -> None:
    fonts = pick_fonts(root)
    assert fonts.symbol == icon_font.FAMILY


def test_draw_symbol_renders_material_glyph(root) -> None:
    fonts = pick_fonts(root)
    canvas = tk.Canvas(root, width=30, height=30)
    assert ui_icons.draw_symbol(
        canvas,
        "settings",
        cx=15,
        cy=15,
        size=30,
        fg="#1f2937",
        fonts=fonts,
    )
    items = canvas.find_all()
    assert items
    assert icon_font.FAMILY in canvas.itemcget(items[0], "font")
    assert canvas.itemcget(items[0], "text") == "\ue8b8"


def test_draw_symbol_falls_back_without_font(root) -> None:
    fonts = Fonts(ui="TkDefaultFont", mono="TkFixedFont", symbol="")
    canvas = tk.Canvas(root, width=30, height=30)

    assert not ui_icons.draw_symbol(
        canvas,
        "about",
        cx=15,
        cy=15,
        size=30,
        fg="#1f2937",
        fonts=fonts,
    )
    ui_icons.draw_info(canvas, 30, "#1f2937")
    assert canvas.find_all()
