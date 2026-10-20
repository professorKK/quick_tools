from __future__ import annotations

from PIL import Image

from quicktools.plugins.screenshot.editor.annotations import (
    Annotation,
    Style,
    Tool,
    arrow_bounds,
    brush_bounds,
    distance_to_segment,
    handle_points,
    resize_bounds,
    translate_annotation,
)
from quicktools.plugins.screenshot.editor.document import AnnotationDocument
from quicktools.plugins.screenshot.editor.fonts import FontResolver
from quicktools.plugins.screenshot.models import Point, Rect


def document(width: int = 200, height: int = 150) -> AnnotationDocument:
    return AnnotationDocument(Image.new("RGB", (width, height), "white"), FontResolver())


def test_annotation_clone_is_deep() -> None:
    original = Annotation(
        tool=Tool.RECT,
        bounds=Rect(1, 2, 30, 40),
        style=Style(color="#ff0000", width=3),
        image=Image.new("RGBA", (4, 4), (1, 2, 3, 255)),
    )
    clone = original.clone()
    original.bounds = Rect(99, 99, 1, 1)
    original.style.color = "#000000"
    assert clone.bounds == Rect(1, 2, 30, 40)
    assert clone.style.color == "#ff0000"
    assert clone.image is not original.image


def test_arrow_bounds_contains_endpoints() -> None:
    bounds = arrow_bounds(Point(10, 20), Point(100, 80), 4)
    assert bounds.contains(Point(10, 20))
    assert bounds.contains(Point(100, 80))


def test_handle_points_and_resize() -> None:
    bounds = Rect(10, 20, 100, 60)
    handles = handle_points(bounds)
    assert handles["nw"] == Point(10, 20)
    assert handles["se"] == Point(110, 80)
    assert resize_bounds(bounds, "se", Point(150, 100)) == Rect(10, 20, 140, 80)
    assert resize_bounds(bounds, "nw", Point(0, 0)) == Rect(0, 0, 110, 80)


def test_distance_to_segment() -> None:
    assert distance_to_segment(Point(5, 5), Point(0, 0), Point(10, 0)) == 5
    assert distance_to_segment(Point(0, 10), Point(0, 0), Point(0, 0)) == 10


def test_document_add_undo_redo() -> None:
    doc = document()
    annotation = doc.add_shape(Tool.RECT, Rect(10, 10, 50, 40), Style())
    assert len(doc.annotations) == 1
    assert annotation.id == 1
    assert doc.undo()
    assert doc.annotations == []
    assert doc.redo()
    assert len(doc.annotations) == 1
    assert doc.annotations[0].bounds == Rect(10, 10, 50, 40)


def test_number_increments_and_undo_restores_counter() -> None:
    doc = document()
    first = doc.add_number(Point(20, 20), Style())
    second = doc.add_number(Point(60, 20), Style())
    assert first.number == 1
    assert second.number == 2
    assert doc.undo()
    third = doc.add_number(Point(100, 20), Style())
    assert third.number == 2


def test_hit_test_and_resize() -> None:
    doc = document()
    rect = doc.add_shape(Tool.RECT, Rect(10, 10, 80, 50), Style(width=4))
    assert doc.hit_test(Point(20, 20)) is rect
    assert doc.hit_test(Point(150, 140)) is None
    assert doc.handle_at(rect, Point(10, 10), 3) == "nw"
    doc.begin_interaction()
    doc.resize(rect, "se", Point(120, 90))
    assert rect.bounds == Rect(10, 10, 110, 80)


def test_crop_translates_and_drops_outside() -> None:
    doc = document(300, 200)
    inside = doc.add_shape(Tool.RECT, Rect(80, 60, 50, 40), Style())
    outside = doc.add_shape(Tool.RECT, Rect(250, 150, 20, 20), Style())
    assert doc.crop(Rect(50, 40, 150, 100))
    assert inside.bounds == Rect(30, 20, 50, 40)
    assert outside not in doc.annotations
    assert doc.image_size == (150, 100)


def test_rotate_and_flip_transform_bounds() -> None:
    doc = document(200, 100)
    rect = doc.add_shape(Tool.RECT, Rect(10, 20, 30, 40), Style())
    doc.rotate(True)
    assert doc.image_size == (100, 200)
    assert rect.bounds == Rect(40, 10, 40, 30)
    doc.flip(True)
    assert rect.bounds == Rect(20, 10, 40, 30)


def test_reset_restores_original_and_can_be_undone() -> None:
    doc = document(200, 150)
    doc.add_shape(Tool.RECT, Rect(10, 10, 40, 30), Style())
    doc.crop(Rect(30, 20, 100, 80))
    assert doc.image_size == (100, 80)
    assert doc.reset()
    assert doc.image_size == (200, 150)
    assert doc.annotations == []
    assert doc.undo()
    assert doc.image_size == (100, 80)
    assert len(doc.annotations) == 1


def test_crop_lasso_and_undo() -> None:
    doc = document(200, 150)
    points = [Point(20, 20), Point(120, 20), Point(70, 120)]
    assert doc.crop_lasso(points)
    assert doc.image_size == (100, 100)
    rendered = doc.render()
    assert rendered.getpixel((50, 30))[3] == 255
    assert rendered.getpixel((90, 90))[3] == 0
    assert doc.undo()
    assert doc.image_size == (200, 150)


def test_text_bounds_and_edit() -> None:
    doc = document()
    annotation = doc.add_text("hello", Point(10, 10), Style(font_size=20))
    assert annotation.bounds.width > 10
    assert annotation.bounds.height > 10
    old_width = annotation.bounds.width
    doc.update_text(annotation.id, "hello world")
    assert annotation.bounds.width > old_width


def test_brush_bounds_translate_and_undo() -> None:
    doc = document()
    stroke = doc.add_brush(
        [Point(20, 20), Point(50, 30), Point(70, 60)],
        Style(color="#e53935", width=6),
    )
    assert stroke.tool is Tool.BRUSH
    assert stroke.points[0] == Point(20, 20)
    assert stroke.bounds == brush_bounds(stroke.points, 6)
    assert stroke.bounds.contains(Point(50, 30))

    original_bounds = stroke.bounds
    translate_annotation(stroke, 5, -4)
    assert stroke.points[0] == Point(25, 16)
    assert stroke.bounds.x == original_bounds.x + 5
    assert stroke.bounds.y == original_bounds.y - 4

    assert doc.undo()
    assert doc.annotations == []
    assert doc.redo()
    assert doc.annotations[0].tool is Tool.BRUSH


def test_brush_points_follow_rotate_and_crop() -> None:
    doc = document()
    doc.add_brush([Point(20, 20), Point(40, 40)], Style(width=4))

    doc.rotate()
    rotated = doc.annotations[0]
    assert rotated.points
    assert all(0 <= point.x <= 150 for point in rotated.points)
    assert all(0 <= point.y <= 200 for point in rotated.points)

    assert doc.undo()
    assert doc.crop(Rect(10, 10, 100, 100))
    cropped = doc.annotations[0]
    assert cropped.points[0] == Point(10, 10)
    assert cropped.points[1] == Point(30, 30)


def test_content_signature_tracks_brush_points() -> None:
    doc = document()
    pristine = doc.content_signature()
    doc.add_brush([Point(10, 10), Point(20, 20)], Style(width=4))
    assert doc.content_signature() != pristine
    assert doc.undo()
    assert doc.content_signature() == pristine


def test_content_signature_tracks_edits_and_undo() -> None:
    doc = document()
    pristine = doc.content_signature()

    # Selection and a mouse-down interaction must not count as edits.
    doc.begin_interaction()
    assert doc.content_signature() == pristine

    annotation = doc.add_shape(Tool.RECT, Rect(10, 10, 50, 40), Style())
    edited = doc.content_signature()
    assert edited != pristine
    doc.select(annotation.id)
    assert doc.content_signature() == edited

    assert doc.undo()
    assert doc.content_signature() == pristine
    assert doc.redo()
    assert doc.content_signature() == edited


def test_content_signature_tracks_base_transforms_and_reset() -> None:
    doc = document()
    pristine = doc.content_signature()

    doc.rotate()
    assert doc.content_signature() != pristine
    assert doc.undo()
    assert doc.content_signature() == pristine

    assert doc.crop(Rect(0, 0, 100, 100))
    assert doc.content_signature() != pristine
    assert doc.undo()
    assert doc.content_signature() == pristine

    doc.add_shape(Tool.RECT, Rect(10, 10, 50, 40), Style())
    assert doc.content_signature() != pristine
    doc.reset()
    assert doc.content_signature() == pristine


def test_content_signature_tracks_style_and_sticker_changes() -> None:
    doc = document()
    annotation = doc.add_shape(Tool.RECT, Rect(10, 10, 50, 40), Style())
    pristine = doc.content_signature()

    doc.update_style(annotation.id, color="#00ff00")
    assert doc.content_signature() != pristine
    doc.undo()
    assert doc.content_signature() == pristine

    doc.add_sticker(
        Image.new("RGBA", (8, 8), (1, 2, 3, 255)),
        Point(50, 50),
        Style(),
    )
    assert doc.content_signature() != pristine
