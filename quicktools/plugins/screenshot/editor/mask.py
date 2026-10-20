"""Freeform lasso mask helpers."""

from __future__ import annotations

from typing import Sequence

from PIL import Image, ImageDraw

from ..models import Point, Rect


def freeform_crop(
    image: Image.Image,
    points: Sequence[Point],
    *,
    supersample: int = 4,
) -> Image.Image:
    """Return an RGBA crop of a polygon with an anti-aliased alpha mask."""
    if len(points) < 3:
        raise ValueError("套索至少需要三个点")
    left = max(0, min(int(round(point.x)) for point in points))
    top = max(0, min(int(round(point.y)) for point in points))
    right = min(image.width, max(int(round(point.x)) for point in points))
    bottom = min(image.height, max(int(round(point.y)) for point in points))
    if right - left < 2 or bottom - top < 2:
        raise ValueError("套索区域太小")
    box = Rect(left, top, right - left, bottom - top)
    area = max(1, box.width * box.height)
    # Keep the supersampled mask bounded for very large screenshots.
    max_factor = max(1, int((16_000_000 / area) ** 0.5))
    factor = max(1, min(int(supersample), max_factor))
    mask = Image.new("L", (box.width * factor, box.height * factor), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(
        [
            (
                (point.x - box.x) * factor,
                (point.y - box.y) * factor,
            )
            for point in points
        ],
        fill=255,
    )
    if factor > 1:
        mask = mask.resize((box.width, box.height), Image.LANCZOS)
    crop = image.crop(
        (box.left, box.top, box.right, box.bottom)
    ).convert("RGBA")
    crop.putalpha(mask)
    return crop
