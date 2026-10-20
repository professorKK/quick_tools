"""Annotation data model and geometry helpers.

Annotations are editable objects. They are rendered to pixels only when the
user copies or saves the screenshot. There is deliberately no freehand brush
tool: the supported markup is outline shapes, arrows, text, numbers, mosaic,
stickers and watermarks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from ..models import Point, Rect


class Tool(str, Enum):
    SELECT = "select"
    RECT = "rect"
    ELLIPSE = "ellipse"
    ARROW = "arrow"
    BRUSH = "brush"
    TEXT = "text"
    NUMBER = "number"
    MOSAIC = "mosaic"
    STICKER = "sticker"
    WATERMARK = "watermark"
    CROP = "crop"
    LASSO = "lasso"


@dataclass
class Style:
    color: str = "#e53935"
    width: int = 4
    font_size: int = 24
    opacity: int = 255
    fill: bool = False

    def copy(self) -> "Style":
        return replace(self)


def coerce_tool(value: Any) -> Tool:
    """Normalize a tool value from a duplicate plugin module tree."""
    if isinstance(value, Tool):
        return value
    raw = getattr(value, "value", value)
    return Tool(str(raw))


@dataclass
class Annotation:
    id: int = 0
    tool: Tool = Tool.RECT
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    style: Style = field(default_factory=Style)
    text: str = ""
    start: Point | None = None
    end: Point | None = None
    points: list[Point] = field(default_factory=list)
    number: int = 0
    block_size: int = 12
    image: Any = None

    def __post_init__(self) -> None:
        self.tool = coerce_tool(self.tool)

    def clone(self) -> "Annotation":
        image = self.image.copy() if self.image is not None else None
        return Annotation(
            id=self.id,
            tool=self.tool,
            bounds=Rect(
                self.bounds.x,
                self.bounds.y,
                self.bounds.width,
                self.bounds.height,
            ),
            style=self.style.copy(),
            text=self.text,
            start=Point(self.start.x, self.start.y) if self.start else None,
            end=Point(self.end.x, self.end.y) if self.end else None,
            points=[Point(point.x, point.y) for point in self.points],
            number=self.number,
            block_size=self.block_size,
            image=image,
        )


RESIZABLE_TOOLS = frozenset(
    {
        Tool.RECT,
        Tool.ELLIPSE,
        Tool.MOSAIC,
        Tool.STICKER,
        Tool.WATERMARK,
    }
)
SHAPE_TOOLS = frozenset({Tool.RECT, Tool.ELLIPSE})
DRAW_TOOLS = frozenset(
    {Tool.RECT, Tool.ELLIPSE, Tool.ARROW, Tool.BRUSH, Tool.MOSAIC, Tool.CROP}
)


def arrow_bounds(start: Point, end: Point, width: int) -> Rect:
    padding = max(8, int(width) * 3)
    x1, x2 = sorted((start.x, end.x))
    y1, y2 = sorted((start.y, end.y))
    return Rect(
        int(round(x1)) - padding,
        int(round(y1)) - padding,
        int(round(x2 - x1)) + padding * 2,
        int(round(y2 - y1)) + padding * 2,
    )


def brush_bounds(points: list[Point], width: float) -> Rect:
    """Bounding box that includes the stroke width around a freehand path."""
    if not points:
        return Rect(0, 0, 0, 0)
    padding = max(3, int(math.ceil(float(width) / 2)) + 1)
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    left = int(math.floor(min(xs))) - padding
    top = int(math.floor(min(ys))) - padding
    right = int(math.ceil(max(xs))) + padding
    bottom = int(math.ceil(max(ys))) + padding
    return Rect(left, top, max(1, right - left), max(1, bottom - top))


def translate_annotation(annotation: Annotation, dx: float, dy: float) -> None:
    if dx == 0 and dy == 0:
        return
    annotation.bounds = Rect(
        int(round(annotation.bounds.x + dx)),
        int(round(annotation.bounds.y + dy)),
        annotation.bounds.width,
        annotation.bounds.height,
    )
    if annotation.start is not None:
        annotation.start = Point(annotation.start.x + dx, annotation.start.y + dy)
    if annotation.end is not None:
        annotation.end = Point(annotation.end.x + dx, annotation.end.y + dy)
    if annotation.points:
        annotation.points = [
            Point(point.x + dx, point.y + dy)
            for point in annotation.points
        ]


def handle_points(bounds: Rect) -> dict[str, Point]:
    left, top = bounds.left, bounds.top
    right, bottom = bounds.right, bounds.bottom
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    return {
        "nw": Point(left, top),
        "n": Point(cx, top),
        "ne": Point(right, top),
        "e": Point(right, cy),
        "se": Point(right, bottom),
        "s": Point(cx, bottom),
        "sw": Point(left, bottom),
        "w": Point(left, cy),
    }


def handle_at(bounds: Rect, point: Point, tolerance: float) -> str | None:
    for name, handle in handle_points(bounds).items():
        if abs(handle.x - point.x) <= tolerance and abs(handle.y - point.y) <= tolerance:
            return name
    return None


def resize_bounds(
    original: Rect, handle: str, point: Point, *, minimum: int = 8
) -> Rect:
    left, top, right, bottom = (
        original.left,
        original.top,
        original.right,
        original.bottom,
    )
    x = point.x
    y = point.y
    if "w" in handle:
        left = x
    if "e" in handle:
        right = x
    if "n" in handle:
        top = y
    if "s" in handle:
        bottom = y
    x1, x2 = sorted((int(round(left)), int(round(right))))
    y1, y2 = sorted((int(round(top)), int(round(bottom))))
    if x2 - x1 < minimum:
        if "w" in handle:
            x1 = x2 - minimum
        else:
            x2 = x1 + minimum
    if y2 - y1 < minimum:
        if "n" in handle:
            y1 = y2 - minimum
        else:
            y2 = y1 + minimum
    return Rect(x1, y1, x2 - x1, y2 - y1)


def distance_to_segment(point: Point, start: Point, end: Point) -> float:
    px, py = point.x, point.y
    x1, y1 = start.x, start.y
    x2, y2 = end.x, end.y
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return math.hypot(px - closest_x, py - closest_y)
