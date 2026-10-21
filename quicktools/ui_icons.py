"""Small vector icons used by window chrome and settings pages.

Windows ships the Segoe Fluent/MDL2 icon fonts, which give crisp pin and gear
glyphs that tint with the title bar button state.  Other platforms fall back
to the Canvas primitives below; both paths use the same 30 px logical grid.
"""

from __future__ import annotations

import math
import tkinter as tk

from .ui_theme import Fonts

# Private-use code points shared by Segoe MDL2 Assets and Segoe Fluent Icons.
SYMBOL_GLYPHS = {
    "pin": "\uE840",
    "settings": "\uE713",
    "about": "\uE946",
}


def draw_symbol(
    canvas: tk.Canvas,
    kind: str,
    *,
    cx: float,
    cy: float,
    size: float,
    fg: str,
    fonts: Fonts,
) -> bool:
    """Draw a Segoe symbol glyph; return False when no symbol font exists."""
    glyph = SYMBOL_GLYPHS.get(kind)
    if not glyph or not fonts.symbol:
        return False
    canvas.create_text(
        cx,
        cy,
        text=glyph,
        fill=fg,
        font=(fonts.symbol, max(8, int(size * 0.43))),
    )
    return True


def draw_gear(
    canvas: tk.Canvas,
    size: float,
    fg: str,
    bg: str,
    *,
    cx: float | None = None,
    cy: float | None = None,
) -> None:
    """Solid gear silhouette with a background-coloured centre hole."""
    cx = size / 2 if cx is None else cx
    cy = size / 2 if cy is None else cy
    r_tip = size * 0.36
    r_root = size * 0.27
    teeth = 8
    points: list[float] = []
    for index in range(teeth):
        base = 2 * math.pi * index / teeth - math.pi / 2
        step = 2 * math.pi / teeth
        for angle, radius in (
            (base - step * 0.32, r_root),
            (base - step * 0.18, r_tip),
            (base + step * 0.18, r_tip),
            (base + step * 0.32, r_root),
        ):
            points.extend(
                (
                    cx + math.cos(angle) * radius,
                    cy + math.sin(angle) * radius,
                )
            )
    canvas.create_polygon(points, fill=fg, outline="")
    hole = size * 0.105
    canvas.create_oval(
        cx - hole,
        cy - hole,
        cx + hole,
        cy + hole,
        fill=bg,
        outline="",
    )


def draw_pin(canvas: tk.Canvas, size: float, fg: str) -> None:
    """Fallback pushpin for platforms without the Segoe icon fonts."""
    line = max(1.4, size / 20)
    # Head and tapered body.
    canvas.create_oval(
        size * 0.36,
        size * 0.20,
        size * 0.64,
        size * 0.40,
        outline=fg,
        width=line,
    )
    canvas.create_polygon(
        size * 0.43,
        size * 0.40,
        size * 0.57,
        size * 0.40,
        size * 0.61,
        size * 0.55,
        size * 0.39,
        size * 0.55,
        fill="",
        outline=fg,
        width=line,
    )
    # Collar and needle.
    canvas.create_line(
        size * 0.32,
        size * 0.57,
        size * 0.68,
        size * 0.57,
        fill=fg,
        width=line * 1.5,
        capstyle="round",
    )
    canvas.create_line(
        size * 0.5,
        size * 0.58,
        size * 0.5,
        size * 0.79,
        fill=fg,
        width=line,
    )


def draw_info(canvas: tk.Canvas, size: float, fg: str) -> None:
    """Fallback information glyph for the settings sidebar."""
    line = max(1.2, size / 20)
    canvas.create_oval(
        size * 0.16,
        size * 0.16,
        size * 0.84,
        size * 0.84,
        outline=fg,
        width=line,
    )
    canvas.create_line(
        size * 0.5,
        size * 0.44,
        size * 0.5,
        size * 0.68,
        fill=fg,
        width=line * 1.4,
        capstyle="round",
    )
    dot = max(1.2, size * 0.055)
    canvas.create_oval(
        size * 0.5 - dot,
        size * 0.31 - dot,
        size * 0.5 + dot,
        size * 0.31 + dot,
        fill=fg,
        outline="",
    )
