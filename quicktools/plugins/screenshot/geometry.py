"""Coordinate helpers for capture, selection and annotation rendering."""

from __future__ import annotations

from typing import Iterable

from .models import CapturedImage, Point, Rect, ScreenInfo


def rect_from_points(start: Point, end: Point) -> Rect:
    return Rect.from_points(start, end)


def monitor_at(screens: Iterable[ScreenInfo], point: Point) -> ScreenInfo | None:
    for screen in screens:
        if screen.rect.contains(point):
            return screen
    return None


def primary_screen(screens: Iterable[ScreenInfo]) -> ScreenInfo | None:
    items = list(screens)
    for screen in items:
        if screen.primary:
            return screen
    return items[0] if items else None


def choose_screen(
    screens: Iterable[ScreenInfo], pointer: Point | None
) -> ScreenInfo | None:
    if pointer is not None:
        match = monitor_at(screens, pointer)
        if match is not None:
            return match
    return primary_screen(screens)


def screen_image_box(
    captured: CapturedImage, screen: ScreenInfo
) -> tuple[int, int, int, int] | None:
    """Return the screen's crop box in captured-image pixels."""
    scale = captured.scale or 1.0
    left = int(round((screen.rect.x - captured.origin.x) * scale))
    top = int(round((screen.rect.y - captured.origin.y) * scale))
    right = int(round((screen.rect.right - captured.origin.x) * scale))
    bottom = int(round((screen.rect.bottom - captured.origin.y) * scale))
    left = max(0, min(left, captured.image.width))
    top = max(0, min(top, captured.image.height))
    right = max(left, min(right, captured.image.width))
    bottom = max(top, min(bottom, captured.image.height))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def crop_screen(captured: CapturedImage, screen: ScreenInfo):
    box = screen_image_box(captured, screen)
    if box is None:
        return None
    return captured.image.crop(box)


def screen_local_to_global(screen: ScreenInfo, local: Rect) -> Rect:
    return Rect(
        screen.rect.x + local.x,
        screen.rect.y + local.y,
        local.width,
        local.height,
    )


def global_to_image_box(
    captured: CapturedImage, rect: Rect
) -> tuple[int, int, int, int]:
    scale = captured.scale or 1.0
    left = int(round((rect.x - captured.origin.x) * scale))
    top = int(round((rect.y - captured.origin.y) * scale))
    right = int(round((rect.right - captured.origin.x) * scale))
    bottom = int(round((rect.bottom - captured.origin.y) * scale))
    left = max(0, min(left, captured.image.width))
    top = max(0, min(top, captured.image.height))
    right = max(left, min(right, captured.image.width))
    bottom = max(top, min(bottom, captured.image.height))
    return left, top, right, bottom


def crop_global_rect(captured: CapturedImage, rect: Rect):
    box = global_to_image_box(captured, rect)
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return captured.image.crop(box)
