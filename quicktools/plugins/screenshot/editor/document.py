"""Editable annotation document with undo/redo and image transforms."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image

from ..models import Point, Rect
from .annotations import (
    RESIZABLE_TOOLS,
    Annotation,
    Style,
    Tool,
    arrow_bounds,
    brush_bounds,
    coerce_tool,
    distance_to_segment,
    handle_at as hit_handle,
    resize_bounds,
    translate_annotation,
)
from .fonts import FontResolver
from .mask import freeform_crop
from .render import TEXT_PADDING, render_document


@dataclass
class _Snapshot:
    base: Image.Image | None
    annotations: list[Annotation]
    next_number: int
    base_changed: bool


class AnnotationDocument:
    def __init__(self, base: Image.Image, fonts: FontResolver) -> None:
        self.base = base.copy()
        self._original_base = self.base.copy()
        self.fonts = fonts
        self.annotations: list[Annotation] = []
        self.selected_id: int | None = None
        self._next_id = 1
        self._next_number = 1
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []

    # --------------------------------------------------------------- state
    @property
    def image_size(self) -> tuple[int, int]:
        return self.base.width, self.base.height

    def selected(self) -> Annotation | None:
        if self.selected_id is None:
            return None
        return next(
            (item for item in self.annotations if item.id == self.selected_id),
            None,
        )

    def select(self, annotation_id: int | None) -> None:
        self.selected_id = annotation_id

    def content_signature(self) -> tuple:
        """Fingerprint exportable content, ignoring selection and history.

        Used to detect unsaved visual changes: undoing back to the pristine
        state produces the same signature again.
        """
        return (
            self.base.size,
            self.base.mode,
            hashlib.blake2b(self.base.tobytes(), digest_size=8).digest(),
            tuple(
                self._annotation_signature(item)
                for item in self.annotations
            ),
        )

    @staticmethod
    def _annotation_signature(annotation: Annotation) -> tuple:
        style = annotation.style
        image = annotation.image
        if image is None:
            image_signature = None
        else:
            try:
                image_signature = (
                    image.size,
                    hashlib.blake2b(
                        image.tobytes(), digest_size=8
                    ).digest(),
                )
            except Exception:
                image_signature = repr(image)
        return (
            annotation.id,
            annotation.tool.value,
            (
                annotation.bounds.x,
                annotation.bounds.y,
                annotation.bounds.width,
                annotation.bounds.height,
            ),
            (
                style.color,
                style.width,
                style.font_size,
                style.opacity,
                style.fill,
            ),
            annotation.text,
            (
                (annotation.start.x, annotation.start.y)
                if annotation.start is not None
                else None
            ),
            (
                (annotation.end.x, annotation.end.y)
                if annotation.end is not None
                else None
            ),
            tuple(
                (point.x, point.y) for point in annotation.points
            ),
            annotation.number,
            annotation.block_size,
            image_signature,
        )

    # ------------------------------------------------------------- history
    def _push_undo(self, *, base_changed: bool = False) -> None:
        self._undo.append(
            _Snapshot(
                base=self.base.copy() if base_changed else None,
                annotations=[item.clone() for item in self.annotations],
                next_number=self._next_number,
                base_changed=base_changed,
            )
        )
        self._redo.clear()

    def begin_interaction(self) -> None:
        self._push_undo()

    def reset(self) -> bool:
        """Restore the original image and remove all annotations."""
        self._push_undo(base_changed=True)
        self.base = self._original_base.copy()
        self.annotations = []
        self.selected_id = None
        self._next_number = 1
        return True

    def undo(self) -> bool:
        if not self._undo:
            return False
        snapshot = self._undo.pop()
        self._redo.append(
            _Snapshot(
                base=self.base.copy() if snapshot.base_changed else None,
                annotations=[item.clone() for item in self.annotations],
                next_number=self._next_number,
                base_changed=snapshot.base_changed,
            )
        )
        self._restore(snapshot)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        snapshot = self._redo.pop()
        self._undo.append(
            _Snapshot(
                base=self.base.copy() if snapshot.base_changed else None,
                annotations=[item.clone() for item in self.annotations],
                next_number=self._next_number,
                base_changed=snapshot.base_changed,
            )
        )
        self._restore(snapshot)
        return True

    def _restore(self, snapshot: _Snapshot) -> None:
        if snapshot.base_changed and snapshot.base is not None:
            self.base = snapshot.base.copy()
        self.annotations = [item.clone() for item in snapshot.annotations]
        self._next_number = snapshot.next_number
        if self.selected_id not in {item.id for item in self.annotations}:
            self.selected_id = None

    # -------------------------------------------------------------- mutate
    def add(self, annotation: Annotation) -> Annotation:
        self._push_undo()
        annotation.id = self._next_id
        self._next_id += 1
        if annotation.tool is Tool.NUMBER:
            if annotation.number <= 0:
                annotation.number = self._next_number
            self._next_number = max(self._next_number, annotation.number + 1)
        self.annotations.append(annotation)
        self.selected_id = annotation.id
        return annotation

    def remove(self, annotation_id: int) -> bool:
        for index, item in enumerate(self.annotations):
            if item.id == annotation_id:
                self._push_undo()
                self.annotations.pop(index)
                if self.selected_id == annotation_id:
                    self.selected_id = None
                return True
        return False

    def update_style(self, annotation_id: int, **changes: Any) -> None:
        annotation = next(
            (item for item in self.annotations if item.id == annotation_id),
            None,
        )
        if annotation is None:
            return
        self._push_undo()
        for key, value in changes.items():
            if hasattr(annotation.style, key):
                setattr(annotation.style, key, value)
        if annotation.tool in (Tool.TEXT, Tool.WATERMARK):
            width, height = self.fonts.measure(
                annotation.text, annotation.style.font_size
            )
            annotation.bounds = Rect(
                annotation.bounds.x,
                annotation.bounds.y,
                max(1, width + TEXT_PADDING * 2),
                max(1, height + TEXT_PADDING * 2),
            )
        elif (
            annotation.tool is Tool.ARROW
            and annotation.start is not None
            and annotation.end is not None
        ):
            annotation.bounds = arrow_bounds(
                annotation.start, annotation.end, annotation.style.width
            )
        elif annotation.tool is Tool.BRUSH and annotation.points:
            annotation.bounds = brush_bounds(
                annotation.points, annotation.style.width
            )
        elif annotation.tool is Tool.NUMBER:
            size = max(24, int(annotation.style.font_size * 1.7))
            center = annotation.bounds.center
            annotation.bounds = Rect(
                int(round(center.x - size / 2)),
                int(round(center.y - size / 2)),
                size,
                size,
            )

    def update_text(self, annotation_id: int, text: str) -> None:
        annotation = next(
            (item for item in self.annotations if item.id == annotation_id),
            None,
        )
        if annotation is None:
            return
        if annotation.tool not in (Tool.TEXT, Tool.WATERMARK):
            return
        self._push_undo()
        annotation.text = text
        width, height = self.fonts.measure(text, annotation.style.font_size)
        annotation.bounds = Rect(
            annotation.bounds.x,
            annotation.bounds.y,
            max(1, width + TEXT_PADDING * 2),
            max(1, height + TEXT_PADDING * 2),
        )

    # --------------------------------------------------------- add helpers
    def add_shape(self, tool: Tool, bounds: Rect, style: Style) -> Annotation:
        return self.add(
            Annotation(
                tool=coerce_tool(tool),
                bounds=bounds.normalized(),
                style=style.copy(),
            )
        )

    def add_arrow(self, start: Point, end: Point, style: Style) -> Annotation:
        return self.add(
            Annotation(
                tool=Tool.ARROW,
                bounds=arrow_bounds(start, end, style.width),
                style=style.copy(),
                start=Point(start.x, start.y),
                end=Point(end.x, end.y),
            )
        )

    def add_brush(self, points: list[Point], style: Style) -> Annotation:
        clean = [Point(point.x, point.y) for point in points]
        return self.add(
            Annotation(
                tool=Tool.BRUSH,
                bounds=brush_bounds(clean, style.width),
                style=style.copy(),
                points=clean,
            )
        )

    def add_text(self, text: str, point: Point, style: Style) -> Annotation:
        width, height = self.fonts.measure(text, style.font_size)
        return self.add(
            Annotation(
                tool=Tool.TEXT,
                bounds=Rect(
                    int(round(point.x)),
                    int(round(point.y)),
                    max(1, width + TEXT_PADDING * 2),
                    max(1, height + TEXT_PADDING * 2),
                ),
                style=style.copy(),
                text=text,
            )
        )

    def add_number(self, point: Point, style: Style) -> Annotation:
        size = max(24, int(style.font_size * 1.7))
        return self.add(
            Annotation(
                tool=Tool.NUMBER,
                bounds=Rect(
                    int(round(point.x - size / 2)),
                    int(round(point.y - size / 2)),
                    size,
                    size,
                ),
                style=style.copy(),
            )
        )

    def add_sticker(self, image: Image.Image, center: Point, style: Style) -> Annotation:
        max_side = max(48, min(240, min(self.base.size) // 3))
        sticker = image.convert("RGBA")
        sticker.thumbnail((max_side, max_side), Image.LANCZOS)
        return self.add(
            Annotation(
                tool=Tool.STICKER,
                bounds=Rect(
                    int(round(center.x - sticker.width / 2)),
                    int(round(center.y - sticker.height / 2)),
                    sticker.width,
                    sticker.height,
                ),
                style=style.copy(),
                image=sticker,
            )
        )

    def add_watermark(self, text: str, style: Style) -> Annotation:
        width, height = self.fonts.measure(text, style.font_size)
        margin = 16
        return self.add(
            Annotation(
                tool=Tool.WATERMARK,
                bounds=Rect(
                    max(0, self.base.width - width - margin),
                    max(0, self.base.height - height - margin),
                    max(1, width + TEXT_PADDING * 2),
                    max(1, height + TEXT_PADDING * 2),
                ),
                style=style.copy(),
                text=text,
            )
        )

    # ------------------------------------------------------------- hit test
    def hit_test(self, point: Point) -> Annotation | None:
        for annotation in reversed(self.annotations):
            if annotation.tool is Tool.ARROW and annotation.start and annotation.end:
                tolerance = max(8, annotation.style.width + 4)
                if (
                    distance_to_segment(
                        point, annotation.start, annotation.end
                    )
                    <= tolerance
                ):
                    return annotation
                continue
            if annotation.bounds.contains(point):
                return annotation
        return None

    def handle_at(
        self, annotation: Annotation, point: Point, tolerance: float
    ) -> str | None:
        if annotation.tool not in RESIZABLE_TOOLS:
            return None
        return hit_handle(annotation.bounds, point, tolerance)

    def resize(
        self, annotation: Annotation, handle: str, point: Point
    ) -> None:
        if annotation.tool in RESIZABLE_TOOLS:
            annotation.bounds = resize_bounds(annotation.bounds, handle, point)

    # ------------------------------------------------------------- transforms
    def crop(self, rect: Rect) -> bool:
        rect = rect.clamp(Rect(0, 0, self.base.width, self.base.height))
        if rect.width < 2 or rect.height < 2:
            return False
        self._push_undo(base_changed=True)
        self.base = self.base.crop(
            (rect.left, rect.top, rect.right, rect.bottom)
        )
        for annotation in self.annotations:
            translate_annotation(annotation, -rect.left, -rect.top)
            if (
                annotation.tool is Tool.ARROW
                and annotation.start is not None
                and annotation.end is not None
            ):
                annotation.bounds = arrow_bounds(
                    annotation.start, annotation.end, annotation.style.width
                )
        image_rect = Rect(0, 0, self.base.width, self.base.height)
        self.annotations = [
            item for item in self.annotations if item.bounds.intersects(image_rect)
        ]
        if self.selected_id not in {item.id for item in self.annotations}:
            self.selected_id = None
        return True

    def crop_lasso(
        self, points, *, drop_annotations: bool = True
    ) -> bool:
        if not drop_annotations and self.annotations:
            return False
        try:
            cropped = freeform_crop(self.base, points)
        except ValueError:
            return False
        self._push_undo(base_changed=True)
        self.base = cropped
        if drop_annotations:
            self.annotations = []
            self.selected_id = None
        return True

    def rotate(self, clockwise: bool = True) -> None:
        old_width, old_height = self.base.size

        def transform(point: Point) -> Point:
            if clockwise:
                return Point(old_height - point.y, point.x)
            return Point(point.y, old_width - point.x)

        self._push_undo(base_changed=True)
        self.base = self.base.rotate(-90 if clockwise else 90, expand=True)
        self._transform_annotations(transform)

    def flip(self, horizontal: bool = True) -> None:
        width, height = self.base.size

        def transform(point: Point) -> Point:
            if horizontal:
                return Point(width - point.x, point.y)
            return Point(point.x, height - point.y)

        self._push_undo(base_changed=True)
        self.base = (
            self.base.transpose(Image.FLIP_LEFT_RIGHT)
            if horizontal
            else self.base.transpose(Image.FLIP_TOP_BOTTOM)
        )
        self._transform_annotations(transform)

    def _transform_annotations(self, transform) -> None:
        for annotation in self.annotations:
            rect = _transform_rect(annotation.bounds, transform)
            annotation.bounds = rect
            if annotation.start is not None:
                annotation.start = transform(annotation.start)
            if annotation.end is not None:
                annotation.end = transform(annotation.end)
            if (
                annotation.tool is Tool.ARROW
                and annotation.start is not None
                and annotation.end is not None
            ):
                annotation.bounds = arrow_bounds(
                    annotation.start, annotation.end, annotation.style.width
                )
            if annotation.points:
                annotation.points = [
                    transform(point) for point in annotation.points
                ]
                if annotation.tool is Tool.BRUSH:
                    annotation.bounds = brush_bounds(
                        annotation.points, annotation.style.width
                    )

    # --------------------------------------------------------------- output
    def render(self) -> Image.Image:
        return render_document(self.base, self.annotations, self.fonts)

    def to_png_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.render().save(buffer, format="PNG")
        return buffer.getvalue()

    def to_export_bytes(self, image_format: str, quality: int = 92) -> bytes:
        image = self.render()
        buffer = io.BytesIO()
        if image_format == "jpeg":
            image.convert("RGB").save(
                buffer, format="JPEG", quality=max(50, min(100, quality))
            )
        elif image_format == "webp":
            image.save(
                buffer,
                format="WEBP",
                quality=max(50, min(100, quality)),
            )
        else:
            image.save(buffer, format="PNG")
        return buffer.getvalue()


def _transform_rect(rect: Rect, transform) -> Rect:
    first = transform(Point(rect.left, rect.top))
    second = transform(Point(rect.right, rect.bottom))
    x1, x2 = sorted((first.x, second.x))
    y1, y2 = sorted((first.y, second.y))
    return Rect(
        int(round(x1)),
        int(round(y1)),
        max(0, int(round(x2 - x1))),
        max(0, int(round(y2 - y1))),
    )
