from __future__ import annotations

from PIL import Image

from quicktools.plugins.screenshot.geometry import (
    choose_screen,
    crop_global_rect,
    global_to_image_box,
    monitor_at,
    primary_screen,
    screen_image_box,
    screen_local_to_global,
)
from quicktools.plugins.screenshot.models import (
    CapturedImage,
    Point,
    Rect,
    ScreenInfo,
)


def test_rect_from_points_normalizes_negative_drag() -> None:
    rect = Rect.from_points(Point(300, 250), Point(100, 50))
    assert rect == Rect(100, 50, 200, 200)


def test_rect_contains_clamp_and_intersection() -> None:
    rect = Rect(10, 20, 100, 50)
    assert rect.contains(Point(10, 20))
    assert rect.contains(Point(109, 69))
    assert not rect.contains(Point(110, 69))
    assert rect.intersects(Rect(50, 0, 80, 30))
    assert not rect.intersects(Rect(200, 200, 10, 10))
    assert rect.clamp(Rect(0, 0, 50, 50)) == Rect(10, 20, 40, 30)


def test_choose_screen_prefers_pointer_monitor() -> None:
    screens = [
        ScreenInfo("left", Rect(-1920, 0, 1920, 1080), primary=False),
        ScreenInfo("main", Rect(0, 0, 2560, 1600), primary=True),
    ]
    assert choose_screen(screens, Point(-10, 100)).name == "left"
    assert choose_screen(screens, Point(10, 100)).name == "main"
    assert choose_screen(screens, Point(9999, 9999)).name == "main"
    assert monitor_at(screens, Point(5000, 5000)) is None
    assert primary_screen(screens).name == "main"


def test_image_box_handles_virtual_origin_and_scale() -> None:
    captured = CapturedImage(
        image=Image.new("RGB", (400, 300)),
        origin=Point(-100, -50),
        scale=2.0,
    )
    assert global_to_image_box(captured, Rect(-100, -50, 50, 25)) == (
        0,
        0,
        100,
        50,
    )
    assert global_to_image_box(captured, Rect(50, 50, 100, 50)) == (
        300,
        200,
        400,
        300,
    )


def test_screen_box_and_crop_are_clamped() -> None:
    captured = CapturedImage(
        image=Image.new("RGB", (100, 80), (1, 2, 3)),
        origin=Point(0, 0),
    )
    screen = ScreenInfo("s", Rect(0, 0, 200, 200), primary=True)
    assert screen_image_box(captured, screen) == (0, 0, 100, 80)
    crop = crop_global_rect(captured, Rect(10, 10, 20, 20))
    assert crop is not None
    assert crop.size == (20, 20)
    assert screen_local_to_global(screen, Rect(10, 20, 30, 40)) == Rect(
        10, 20, 30, 40
    )


def test_crop_outside_captured_image_returns_none() -> None:
    captured = CapturedImage(
        image=Image.new("RGB", (100, 80)),
        origin=Point(0, 0),
    )
    assert crop_global_rect(captured, Rect(200, 200, 10, 10)) is None
