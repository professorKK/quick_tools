"""Render annotation objects onto a screenshot with Pillow."""

from __future__ import annotations

import math
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw

from ..models import Rect
from .annotations import Annotation, Tool
from .fonts import FontResolver

TEXT_PADDING = 6


def _color(value: str, opacity: int = 255) -> tuple[int, int, int, int]:
    try:
        red, green, blue = ImageColor.getrgb(value)[:3]
    except (ValueError, AttributeError):
        red, green, blue = 229, 57, 53
    return red, green, blue, max(0, min(255, int(opacity)))


def _overlay(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _paste_rgba(
    working: Image.Image, image: Image.Image, position: tuple[int, int]
) -> Image.Image:
    overlay = Image.new("RGBA", working.size, (0, 0, 0, 0))
    overlay.paste(image, position)
    return Image.alpha_composite(working, overlay)


def _draw_shape(
    working: Image.Image, annotation: Annotation
) -> Image.Image:
    overlay = _overlay(working.size)
    draw = ImageDraw.Draw(overlay)
    color = _color(annotation.style.color, annotation.style.opacity)
    fill = color if annotation.style.fill else None
    bounds = annotation.bounds
    box = (
        bounds.left,
        bounds.top,
        max(bounds.left, bounds.right - 1),
        max(bounds.top, bounds.bottom - 1),
    )
    width = max(1, int(annotation.style.width))
    if annotation.tool is Tool.ELLIPSE:
        draw.ellipse(box, outline=color, width=width, fill=fill)
    else:
        draw.rectangle(box, outline=color, width=width, fill=fill)
    return Image.alpha_composite(working, overlay)


def _draw_arrow(working: Image.Image, annotation: Annotation) -> Image.Image:
    start = annotation.start
    end = annotation.end
    if start is None or end is None:
        return working
    color = _color(annotation.style.color, annotation.style.opacity)
    width = max(1, int(annotation.style.width))
    dx = end.x - start.x
    dy = end.y - start.y
    length = math.hypot(dx, dy)
    if length < 1:
        return working
    ux, uy = dx / length, dy / length
    head_length = min(length, max(10, width * 3))
    head_width = max(6, width * 2.4)
    base_x = end.x - ux * head_length
    base_y = end.y - uy * head_length
    perp_x, perp_y = -uy, ux
    overlay = _overlay(working.size)
    draw = ImageDraw.Draw(overlay)
    draw.line((start.x, start.y, base_x, base_y), fill=color, width=width)
    draw.polygon(
        [
            (end.x, end.y),
            (
                base_x + perp_x * head_width / 2,
                base_y + perp_y * head_width / 2,
            ),
            (
                base_x - perp_x * head_width / 2,
                base_y - perp_y * head_width / 2,
            ),
        ],
        fill=color,
    )
    return Image.alpha_composite(working, overlay)


def _draw_brush(working: Image.Image, annotation: Annotation) -> Image.Image:
    points = annotation.points
    if not points:
        return working
    color = _color(annotation.style.color, annotation.style.opacity)
    width = max(1, int(annotation.style.width))
    overlay = _overlay(working.size)
    draw = ImageDraw.Draw(overlay)
    coords = [(float(point.x), float(point.y)) for point in points]
    if len(coords) > 1:
        draw.line(coords, fill=color, width=width, joint="curve")
    radius = max(0.5, width / 2)
    ends = (coords[0], coords[-1]) if len(coords) > 1 else coords
    for x, y in ends:
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=color,
        )
    return Image.alpha_composite(working, overlay)


def _draw_text_run(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    text: str,
    font,
    fill: tuple[int, int, int, int],
) -> None:
    try:
        draw.text((x, y), text, font=font, fill=fill, anchor="lt")
    except Exception:
        draw.text((x, y), text, font=font, fill=fill)


def render_annotation_preview(
    annotation: Annotation, fonts: FontResolver
) -> Image.Image:
    """Render one text/watermark annotation on a transparent background.

    The canvas uses this same image, so the selection border and the exported
    pixels share one set of font metrics.
    """
    width = max(1, annotation.bounds.width)
    height = max(1, annotation.bounds.height)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if not annotation.text:
        return image
    draw = ImageDraw.Draw(image)
    color = _color(annotation.style.color, annotation.style.opacity)
    font = fonts.get(annotation.style.font_size)
    _draw_text_run(
        draw,
        TEXT_PADDING,
        TEXT_PADDING,
        annotation.text,
        font,
        color,
    )
    return image


def _draw_text(
    working: Image.Image,
    annotation: Annotation,
    fonts: FontResolver,
) -> Image.Image:
    if not annotation.text:
        return working
    overlay = render_annotation_preview(annotation, fonts)
    return _paste_rgba(
        working, overlay, (annotation.bounds.x, annotation.bounds.y)
    )


def _draw_number(
    working: Image.Image,
    annotation: Annotation,
    fonts: FontResolver,
) -> Image.Image:
    overlay = _overlay(working.size)
    draw = ImageDraw.Draw(overlay)
    color = _color(annotation.style.color, annotation.style.opacity)
    bounds = annotation.bounds
    draw.ellipse(
        (
            bounds.left,
            bounds.top,
            max(bounds.left, bounds.right - 1),
            max(bounds.top, bounds.bottom - 1),
        ),
        fill=color,
    )
    font = fonts.get(max(10, int(annotation.style.font_size * 0.75)))
    label = str(annotation.number)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        text_width = right - left
        text_height = bottom - top
    except Exception:
        text_width, text_height = len(label) * 8, 12
    x = bounds.x + (bounds.width - text_width) / 2
    y = bounds.y + (bounds.height - text_height) / 2 - top
    draw.text((x, y), label, font=font, fill=(255, 255, 255, 255))
    return Image.alpha_composite(working, overlay)


def _draw_mosaic(working: Image.Image, annotation: Annotation) -> Image.Image:
    bounds = annotation.bounds.clamp(Rect(0, 0, working.width, working.height))
    if bounds.width < 2 or bounds.height < 2:
        return working
    block = max(2, int(annotation.block_size))
    region = working.crop(
        (bounds.left, bounds.top, bounds.right, bounds.bottom)
    )
    small = region.resize(
        (
            max(1, bounds.width // block),
            max(1, bounds.height // block),
        ),
        Image.NEAREST,
    )
    pixelated = small.resize((bounds.width, bounds.height), Image.NEAREST)
    result = working.copy()
    result.paste(pixelated, (bounds.left, bounds.top))
    return result


def _draw_sticker(working: Image.Image, annotation: Annotation) -> Image.Image:
    if annotation.image is None:
        return working
    bounds = annotation.bounds
    if bounds.width < 1 or bounds.height < 1:
        return working
    try:
        # Match the editor preview: the sticker fills its annotation bounds,
        # including non-uniform stretches from dragging the selection frame.
        sticker = annotation.image.convert("RGBA").resize(
            (max(1, bounds.width), max(1, bounds.height)), Image.LANCZOS
        )
    except Exception:
        return working
    return _paste_rgba(working, sticker, (bounds.x, bounds.y))


def _draw_watermark(
    working: Image.Image,
    annotation: Annotation,
    fonts: FontResolver,
) -> Image.Image:
    if not annotation.text:
        return working
    overlay = render_annotation_preview(annotation, fonts)
    return _paste_rgba(
        working, overlay, (annotation.bounds.x, annotation.bounds.y)
    )


def render_document(
    base: Image.Image,
    annotations: Iterable[Annotation],
    fonts: FontResolver,
) -> Image.Image:
    """Return a new RGBA image with all annotations composited in order."""
    working = base.convert("RGBA")
    for annotation in annotations:
        if annotation.tool in (Tool.RECT, Tool.ELLIPSE):
            working = _draw_shape(working, annotation)
        elif annotation.tool is Tool.ARROW:
            working = _draw_arrow(working, annotation)
        elif annotation.tool is Tool.BRUSH:
            working = _draw_brush(working, annotation)
        elif annotation.tool is Tool.TEXT:
            working = _draw_text(working, annotation, fonts)
        elif annotation.tool is Tool.NUMBER:
            working = _draw_number(working, annotation, fonts)
        elif annotation.tool is Tool.MOSAIC:
            working = _draw_mosaic(working, annotation)
        elif annotation.tool is Tool.STICKER:
            working = _draw_sticker(working, annotation)
        elif annotation.tool is Tool.WATERMARK:
            working = _draw_watermark(working, annotation, fonts)
    return working
