"""Pillow-drawn line icons for the screenshot plugin.

Tk has no vector icon support.  Icons are drawn on a 24x24 logical grid at a
supersampled resolution and downscaled with LANCZOS, then wrapped in
``ImageTk.PhotoImage`` by :class:`IconSet`.  PhotoImage objects must be kept
alive; the set owns them for the lifetime of its widget tree.
"""

from __future__ import annotations

import math
import tkinter as tk
from functools import lru_cache

from PIL import Image, ImageDraw, ImageTk

LOGICAL = 24
SUPERSAMPLE = 4
DEFAULT_STROKE = 1.9


class _Pen:
    """Draws in the 24x24 logical coordinate system."""

    def __init__(
        self,
        draw: ImageDraw.ImageDraw,
        scale: float,
        color: str,
        stroke: float,
    ) -> None:
        self.draw = draw
        self.scale = scale
        self.color = color
        self.width = max(1, int(round(stroke * scale)))

    def _pt(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale, y * self.scale)

    def _box(
        self, x0: float, y0: float, x1: float, y1: float
    ) -> tuple[float, float, float, float]:
        return (
            x0 * self.scale,
            y0 * self.scale,
            x1 * self.scale,
            y1 * self.scale,
        )

    def line(self, points, *, close: bool = False) -> None:
        coords = [self._pt(x, y) for x, y in points]
        if close:
            coords.append(coords[0])
        self.draw.line(
            coords, fill=self.color, width=self.width, joint="curve"
        )

    def polygon(self, points, *, fill: bool = False) -> None:
        coords = [self._pt(x, y) for x, y in points]
        if fill:
            self.draw.polygon(coords, fill=self.color)
        else:
            self.draw.line(
                coords + [coords[0]],
                fill=self.color,
                width=self.width,
                joint="curve",
            )

    def rect(
        self, x0: float, y0: float, x1: float, y1: float, *, fill=False
    ) -> None:
        box = self._box(x0, y0, x1, y1)
        if fill:
            self.draw.rectangle(box, fill=self.color)
        else:
            self.draw.rectangle(box, outline=self.color, width=self.width)

    def rounded_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        radius: float = 2.0,
        *,
        fill: bool = False,
    ) -> None:
        box = self._box(x0, y0, x1, y1)
        radius_px = radius * self.scale
        if fill:
            self.draw.rounded_rectangle(
                box, radius=radius_px, fill=self.color
            )
        else:
            self.draw.rounded_rectangle(
                box,
                radius=radius_px,
                outline=self.color,
                width=self.width,
            )

    def circle(self, cx: float, cy: float, r: float, *, fill=False) -> None:
        box = self._box(cx - r, cy - r, cx + r, cy + r)
        if fill:
            self.draw.ellipse(box, fill=self.color)
        else:
            self.draw.ellipse(box, outline=self.color, width=self.width)

    def dot(self, cx: float, cy: float, r: float) -> None:
        self.circle(cx, cy, r, fill=True)

    def arc(self, cx: float, cy: float, r: float, start: float, end: float) -> None:
        box = self._box(cx - r, cy - r, cx + r, cy + r)
        self.draw.arc(box, start=start, end=end, fill=self.color, width=self.width)


def _line_arrow(
    ctx: _Pen,
    tip: tuple[float, float],
    barbs: tuple[tuple[float, float], tuple[float, float]],
) -> None:
    ctx.line([barbs[0], tip, barbs[1]])


def _star_points(
    cx: float, cy: float, outer: float, inner: float
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.radians(-90 + index * 36)
        points.append(
            (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        )
    return points


# ------------------------------------------------------------------ drawers
def _home(ctx: _Pen) -> None:
    ctx.line([(3, 11), (12, 3), (21, 11)])
    ctx.line([(5, 10), (5, 20), (19, 20), (19, 10)])
    ctx.line([(10, 20), (10, 14), (14, 14), (14, 20)])


def _info(ctx: _Pen) -> None:
    ctx.circle(12, 12, 9)
    ctx.line([(12, 11), (12, 17)])
    ctx.dot(12, 7.5, 1.2)


def _gear(ctx: _Pen) -> None:
    ctx.circle(12, 12, 7.3)
    ctx.circle(12, 12, 3.0)
    for index in range(8):
        angle = math.radians(index * 45)
        inner_x = 12 + 8.2 * math.cos(angle)
        inner_y = 12 + 8.2 * math.sin(angle)
        outer_x = 12 + 10.6 * math.cos(angle)
        outer_y = 12 + 10.6 * math.sin(angle)
        ctx.line([(inner_x, inner_y), (outer_x, outer_y)])


def _folder(ctx: _Pen) -> None:
    ctx.line(
        [(3, 7), (9, 7), (11, 9), (21, 9), (21, 19), (3, 19)], close=True
    )
    ctx.line([(3, 9), (21, 9)])


def _search(ctx: _Pen) -> None:
    ctx.circle(10.5, 10.5, 6)
    ctx.line([(15, 15), (20.5, 20.5)])


def _filter(ctx: _Pen) -> None:
    ctx.polygon([(3, 5), (21, 5), (14, 12.5), (14, 19), (10, 21), (10, 12.5)])


def _open(ctx: _Pen) -> None:
    ctx.rounded_rect(4, 9, 13, 20, 2)
    ctx.line([(11, 13), (20, 4)])
    _line_arrow(ctx, (20, 4), ((14.5, 4.5), (19.5, 9.5)))


def _copy(ctx: _Pen) -> None:
    ctx.rounded_rect(4, 4, 15, 15, 2)
    ctx.rounded_rect(9, 9, 20, 20, 2)


def _trash(ctx: _Pen) -> None:
    ctx.line([(4, 7), (20, 7)])
    ctx.line([(9, 7), (9, 4), (15, 4), (15, 7)])
    ctx.line([(6, 7), (7, 20), (17, 20), (18, 7)])
    ctx.line([(10, 10), (10.5, 17)])
    ctx.line([(14, 10), (13.5, 17)])


def _star(ctx: _Pen) -> None:
    ctx.polygon(_star_points(12, 12.5, 9, 4.1))


def _star_filled(ctx: _Pen) -> None:
    ctx.polygon(_star_points(12, 12.5, 9, 4.1), fill=True)


def _chevron_right(ctx: _Pen) -> None:
    ctx.line([(9, 5), (16, 12), (9, 19)])


def _chevron_down(ctx: _Pen) -> None:
    ctx.line([(5, 9), (12, 16), (19, 9)])


def _check(ctx: _Pen) -> None:
    ctx.line([(4, 12), (10, 18), (20, 6)])


def _warning(ctx: _Pen) -> None:
    ctx.polygon([(12, 3), (22, 20), (2, 20)])
    ctx.line([(12, 9), (12, 14)])
    ctx.dot(12, 17.4, 1.2)


def _camera(ctx: _Pen) -> None:
    ctx.rounded_rect(3, 7, 21, 19, 2.5)
    ctx.line([(9, 7), (10, 4), (14, 4), (15, 7)])
    ctx.circle(12, 13, 3.6)


def _rect(ctx: _Pen) -> None:
    ctx.rounded_rect(3, 5, 21, 19, 2)


def _window(ctx: _Pen) -> None:
    ctx.rounded_rect(3, 4, 21, 20, 2)
    ctx.line([(3, 8.5), (21, 8.5)])
    ctx.dot(6, 6.3, 0.9)
    ctx.dot(9, 6.3, 0.9)


def _ellipse(ctx: _Pen) -> None:
    ctx.circle(12, 12, 8)


def _arrow(ctx: _Pen) -> None:
    ctx.line([(4, 20), (19, 5)])
    _line_arrow(ctx, (19, 5), ((12.5, 5.5), (18.5, 11.5)))


def _brush(ctx: _Pen) -> None:
    ctx.line([(16, 3), (21, 8), (10, 19)])
    ctx.polygon([(10, 19), (4, 21), (7, 15)], fill=True)
    ctx.arc(5, 21, 2.4, 190, 350)


def _text(ctx: _Pen) -> None:
    ctx.line([(5, 5), (19, 5)])
    ctx.line([(12, 5), (12, 19)])
    ctx.line([(8.5, 19), (15.5, 19)])


def _number(ctx: _Pen) -> None:
    ctx.circle(12, 12, 9)
    ctx.line([(10, 8), (12, 6.5), (12, 18)])
    ctx.line([(9, 18), (15, 18)])


def _mosaic(ctx: _Pen) -> None:
    cells = [(4, 4), (9.5, 4), (15, 4), (4, 9.5), (9.5, 9.5), (15, 9.5),
             (4, 15), (9.5, 15), (15, 15)]
    for index, (x, y) in enumerate(cells):
        ctx.rect(x, y, x + 4.5, y + 4.5, fill=index in (0, 4, 8, 2, 6))


def _sticker(ctx: _Pen) -> None:
    ctx.circle(12, 12, 9)
    ctx.dot(9, 9.5, 1.1)
    ctx.dot(15, 9.5, 1.1)
    ctx.arc(12, 12, 5, 25, 155)


def _watermark(ctx: _Pen) -> None:
    ctx.rounded_rect(4, 5, 20, 19, 2)
    ctx.line([(7, 16), (17, 8)])
    ctx.circle(9, 9, 1.5)


def _crop(ctx: _Pen) -> None:
    ctx.line([(7, 3), (7, 17), (21, 17)])
    ctx.line([(3, 7), (17, 7), (17, 21)])


def _lasso(ctx: _Pen) -> None:
    ctx.arc(11.5, 9.5, 7.2, 0, 360)
    ctx.line([(7.5, 14.5), (5, 19)])
    ctx.dot(5, 20, 1.1)


def _scroll(ctx: _Pen) -> None:
    ctx.rounded_rect(7, 3, 17, 20, 5)
    ctx.line([(12, 6), (12, 10)])
    ctx.line([(9, 14.5), (12, 17.5), (15, 14.5)])


def _select(ctx: _Pen) -> None:
    ctx.polygon(
        [(5, 3), (19, 11), (12, 12), (16, 20), (13, 21.5), (9, 13.5), (5, 17.5)],
        fill=True,
    )


def _undo(ctx: _Pen) -> None:
    ctx.arc(12, 13, 7.5, 180, 360)
    _line_arrow(ctx, (4.5, 13), ((1.8, 9.7), (7.6, 10.2)))


def _redo(ctx: _Pen) -> None:
    ctx.arc(12, 13, 7.5, 180, 360)
    _line_arrow(ctx, (19.5, 13), ((16.4, 10.2), (22.2, 9.7)))


def _reset(ctx: _Pen) -> None:
    ctx.arc(12, 12, 8, 40, 330)
    _line_arrow(ctx, (18.1, 17.1), ((13.9, 17.4), (18.4, 13.1)))
    ctx.dot(12, 12, 1.3)


def _rotate_left(ctx: _Pen) -> None:
    ctx.rounded_rect(9, 9, 15, 15, 1.5)
    ctx.arc(12, 12, 8, 40, 320)
    _line_arrow(ctx, (5.5, 9.6), ((9.6, 8.6), (6.1, 13.4)))


def _rotate_right(ctx: _Pen) -> None:
    ctx.rounded_rect(9, 9, 15, 15, 1.5)
    ctx.arc(12, 12, 8, 40, 320)
    _line_arrow(ctx, (18.5, 9.6), ((17.9, 13.4), (14.4, 8.6)))


def _flip(ctx: _Pen) -> None:
    for y0, y1 in ((3, 7), (9.5, 14.5), (17, 21)):
        ctx.line([(12, y0), (12, y1)])
    ctx.polygon([(3, 8), (3, 16), (9.5, 12)])
    ctx.polygon([(21, 8), (21, 16), (14.5, 12)])


def _fit(ctx: _Pen) -> None:
    ctx.line([(3, 8), (3, 3), (8, 3)])
    ctx.line([(16, 3), (21, 3), (21, 8)])
    ctx.line([(3, 16), (3, 21), (8, 21)])
    ctx.line([(16, 21), (21, 21), (21, 16)])
    ctx.rect(8, 8, 16, 16)


def _one_to_one(ctx: _Pen) -> None:
    ctx.line([(6, 7), (6, 17)])
    ctx.line([(3.5, 17), (8.5, 17)])
    ctx.dot(11.5, 10, 1.0)
    ctx.dot(11.5, 15, 1.0)
    ctx.line([(16, 7), (16, 17)])
    ctx.line([(13.5, 17), (18.5, 17)])


def _save(ctx: _Pen) -> None:
    ctx.line([(4, 4), (16, 4), (20, 8), (20, 20), (4, 20)], close=True)
    ctx.rect(8, 4, 16, 10)
    ctx.rect(7, 14, 17, 20)


def _save_as(ctx: _Pen) -> None:
    ctx.line([(3, 3), (14, 3), (17, 6), (17, 17), (3, 17)], close=True)
    ctx.rect(6.5, 3, 13.5, 8)
    ctx.rect(5.5, 12, 14.5, 17)
    ctx.line([(14, 21), (21, 14)])
    _line_arrow(ctx, (21, 14), ((16.5, 14.5), (20.5, 18.5)))


def _close(ctx: _Pen) -> None:
    ctx.line([(5, 5), (19, 19)])
    ctx.line([(19, 5), (5, 19)])


_DRAWERS = {
    "home": _home,
    "info": _info,
    "gear": _gear,
    "folder": _folder,
    "search": _search,
    "filter": _filter,
    "open": _open,
    "copy": _copy,
    "trash": _trash,
    "star": _star,
    "star-filled": _star_filled,
    "chevron-right": _chevron_right,
    "chevron-down": _chevron_down,
    "check": _check,
    "warning": _warning,
    "camera": _camera,
    "rect": _rect,
    "window": _window,
    "ellipse": _ellipse,
    "arrow": _arrow,
    "brush": _brush,
    "text": _text,
    "number": _number,
    "mosaic": _mosaic,
    "sticker": _sticker,
    "watermark": _watermark,
    "crop": _crop,
    "lasso": _lasso,
    "scroll": _scroll,
    "select": _select,
    "undo": _undo,
    "redo": _redo,
    "reset": _reset,
    "rotate-left": _rotate_left,
    "rotate-right": _rotate_right,
    "flip": _flip,
    "fit": _fit,
    "one-to-one": _one_to_one,
    "save": _save,
    "save-as": _save_as,
    "close": _close,
}

ICON_NAMES = frozenset(_DRAWERS)


@lru_cache(maxsize=1024)
def render_icon(
    name: str,
    size: int = 18,
    color: str = "#6b7280",
    stroke: float = DEFAULT_STROKE,
) -> Image.Image:
    """Return an RGBA icon image; unknown names raise ``KeyError``."""

    drawer = _DRAWERS[name]
    final_size = max(1, int(size))
    pixel_size = final_size * SUPERSAMPLE
    scale = pixel_size / LOGICAL
    image = Image.new("RGBA", (pixel_size, pixel_size), (0, 0, 0, 0))
    pen = _Pen(ImageDraw.Draw(image), scale, color, stroke)
    drawer(pen)
    return image.resize((final_size, final_size), Image.LANCZOS)


def render_tile(
    icon: str,
    *,
    size: int = 48,
    bg: str = "#e8f0fe",
    fg: str = "#2563eb",
    radius: int = 12,
    icon_size: int | None = None,
) -> Image.Image:
    """Return a rounded tinted tile with ``icon`` centered on it."""

    final_size = max(4, int(size))
    pixel_size = final_size * 2
    canvas = Image.new("RGBA", (pixel_size, pixel_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (0, 0, pixel_size - 1, pixel_size - 1),
        radius=radius * 2,
        fill=bg,
    )
    inner = icon_size or max(10, int(round(final_size * 0.52)))
    glyph = render_icon(icon, inner * 2, fg)
    offset = (pixel_size - glyph.width) // 2
    canvas.alpha_composite(glyph, (offset, offset))
    return canvas.resize((final_size, final_size), Image.LANCZOS)


class IconSet:
    """Caches ``PhotoImage`` icons for one widget tree."""

    def __init__(self, master: tk.Misc) -> None:
        self.master = master
        self._cache: dict[tuple, ImageTk.PhotoImage] = {}
        try:
            dpi = float(master.winfo_fpixels("1i")) / 96.0
        except Exception:
            dpi = 1.0
        self.scale = min(2.5, max(1.0, dpi))
        master.bind("<Destroy>", self._on_destroy, add="+")

    def _pixel_size(self, size: int) -> int:
        return max(1, int(round(int(size) * self.scale)))

    def get(
        self,
        name: str,
        size: int = 18,
        color: str = "#6b7280",
        stroke: float = DEFAULT_STROKE,
    ) -> ImageTk.PhotoImage:
        pixel_size = self._pixel_size(size)
        key = ("icon", name, pixel_size, color, stroke)
        cached = self._cache.get(key)
        if cached is None:
            source = render_icon(name, pixel_size, color, stroke)
            cached = ImageTk.PhotoImage(source, master=self.master)
            self._cache[key] = cached
        return cached

    def tile(
        self,
        icon: str,
        *,
        size: int = 48,
        bg: str = "#e8f0fe",
        fg: str = "#2563eb",
        radius: int = 12,
    ) -> ImageTk.PhotoImage:
        pixel_size = self._pixel_size(size)
        key = ("tile", icon, pixel_size, bg, fg, radius)
        cached = self._cache.get(key)
        if cached is None:
            source = render_tile(
                icon,
                size=pixel_size,
                bg=bg,
                fg=fg,
                radius=max(2, int(round(radius * self.scale))),
            )
            cached = ImageTk.PhotoImage(source, master=self.master)
            self._cache[key] = cached
        return cached

    def clear(self) -> None:
        self._cache.clear()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.master:
            self.clear()
