from __future__ import annotations

import io

from PIL import Image

from PIL import ImageChops

from quicktools.plugins.screenshot.editor.annotations import Style, Tool
from quicktools.plugins.screenshot.editor.document import AnnotationDocument
from quicktools.plugins.screenshot.editor.fonts import FontResolver
from quicktools.plugins.screenshot.editor.render import render_annotation_preview
from quicktools.plugins.screenshot.models import Point, Rect


def document(width: int = 240, height: int = 180, color="white") -> AnnotationDocument:
    return AnnotationDocument(Image.new("RGB", (width, height), color), FontResolver())


def red_pixels(image: Image.Image) -> int:
    count = 0
    for red, green, blue, _alpha in image.convert("RGBA").getdata():
        if red > 150 and green < 120 and blue < 120:
            count += 1
    return count


def test_rectangle_and_ellipse_are_hollow() -> None:
    doc = document()
    style = Style(color="#e53935", width=4)
    doc.add_shape(Tool.RECT, Rect(20, 20, 80, 50), style)
    doc.add_shape(Tool.ELLIPSE, Rect(130, 20, 80, 60), style)
    rendered = doc.render()

    assert rendered.convert("RGBA").getpixel((60, 45))[0] > 200  # rect interior
    assert rendered.convert("RGBA").getpixel((170, 50))[0] > 200  # ellipse interior
    assert red_pixels(rendered) > 100
    assert rendered.getpixel((20, 40))[0] > 150


def test_arrow_text_number_and_watermark_render() -> None:
    doc = document()
    style = Style(color="#1e88e5", width=4, font_size=22)
    doc.add_arrow(Point(20, 120), Point(180, 160), style)
    doc.add_text("Hi", Point(20, 150), style)
    doc.add_number(Point(210, 40), style)
    doc.add_watermark("WM", Style(color="#111827", font_size=22, opacity=128))
    rendered = doc.render()

    assert rendered.convert("RGBA").getpixel((210, 40))[3] == 255
    assert any(
        pixel[2] > 150 and pixel[0] < 120
        for pixel in rendered.convert("RGBA").getdata()
    )
    assert len(rendered.getcolors(maxcolors=1_000_000) or []) > 2


def test_brush_stroke_renders_along_path() -> None:
    doc = document(120, 80)
    doc.add_brush(
        [Point(20, 20), Point(60, 20), Point(60, 60)],
        Style(color="#e53935", width=6),
    )
    rendered = doc.render().convert("RGBA")

    horizontal = rendered.getpixel((40, 20))
    vertical = rendered.getpixel((60, 40))
    untouched = rendered.getpixel((100, 70))
    assert horizontal[0] > 180 and horizontal[1] < 120
    assert vertical[0] > 180 and vertical[1] < 120
    assert untouched[0] > 200 and untouched[3] == 255


def test_brush_single_point_renders_dot() -> None:
    doc = document(60, 40)
    doc.add_brush([Point(30, 20)], Style(color="#1e88e5", width=8))
    pixel = doc.render().convert("RGB").getpixel((30, 20))
    assert pixel[2] > 150 and pixel[0] < 120


def test_mosaic_changes_region() -> None:
    base = Image.new("RGB", (120, 80), "white")
    for x in range(0, 120, 2):
        for y in range(0, 80, 2):
            if (x // 2 + y // 2) % 2:
                base.putpixel((x, y), (0, 0, 0))
    doc = AnnotationDocument(base, FontResolver())
    doc.add_shape(Tool.MOSAIC, Rect(20, 20, 60, 40), Style())
    rendered = doc.render().convert("RGB")
    original_pixels = list(base.crop((20, 20, 80, 60)).getdata())
    rendered_pixels = list(rendered.crop((20, 20, 80, 60)).getdata())
    assert original_pixels != rendered_pixels


def test_text_preview_matches_export_and_selection_bounds() -> None:
    base = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    doc = AnnotationDocument(base, FontResolver())
    style = Style(color="#e53935", font_size=24)
    annotation = doc.add_text("123", Point(30, 20), style)
    preview = render_annotation_preview(annotation, doc.fonts)
    assert preview.size == (
        annotation.bounds.width,
        annotation.bounds.height,
    )
    assert preview.getpixel((0, 0))[3] == 0
    assert any(pixel[3] > 0 for pixel in preview.getdata())

    rendered = doc.render()
    region = rendered.crop(
        (
            annotation.bounds.left,
            annotation.bounds.top,
            annotation.bounds.right,
            annotation.bounds.bottom,
        )
    )
    assert ImageChops.difference(region, preview).getbbox() is None


def test_sticker_alpha_is_composited() -> None:
    doc = document()
    sticker = Image.new("RGBA", (20, 20), (0, 200, 0, 255))
    doc.add_sticker(sticker, Point(120, 90), Style())
    rendered = doc.render()
    pixel = rendered.getpixel((120, 90))
    assert pixel[1] > 150
    assert pixel[3] == 255


def test_export_formats() -> None:
    doc = document()
    doc.add_shape(Tool.RECT, Rect(10, 10, 40, 30), Style())

    png = doc.to_export_bytes("png")
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG"
        assert image.size == (240, 180)

    jpeg = doc.to_export_bytes("jpeg", 80)
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"

    webp = doc.to_export_bytes("webp", 80)
    with Image.open(io.BytesIO(webp)) as image:
        assert image.format == "WEBP"


def test_cjk_font_measurement_when_available() -> None:
    fonts = FontResolver()
    width, height = fonts.measure("测试", 20)
    assert width > 0
    assert height > 0
