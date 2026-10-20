from __future__ import annotations

from PIL import Image, ImageChops, ImageDraw

from quicktools.plugins.screenshot.scroll.stitcher import (
    find_vertical_overlap,
    stitch_vertical,
)


def tall_source(width: int = 120, height: int = 600) -> Image.Image:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, height, 10):
        draw.rectangle(
            (0, y, width - 1, y + 4),
            fill=((y * 3) % 255, (y * 7) % 255, (y * 11) % 255),
        )
        draw.text((5, y + 1), f"row {y:03d}", fill="black")
    return image


def test_overlap_and_stitch_reconstructs_source() -> None:
    source = tall_source()
    frames = [source.crop((0, y, 120, y + 200)) for y in (0, 80, 160, 240, 320)]
    overlaps = []
    for previous, current in zip(frames, frames[1:]):
        overlap = find_vertical_overlap(previous, current)
        assert overlap == 120
        overlaps.append(overlap)

    stitched = stitch_vertical(frames, overlaps)
    expected = source.crop((0, 0, 120, 520))
    assert stitched.size == expected.size
    assert ImageChops.difference(stitched, expected).getbbox() is None


def test_identical_frames_report_full_overlap() -> None:
    source = tall_source()
    frame = source.crop((0, 0, 120, 200))
    assert find_vertical_overlap(frame, frame) == 200


def test_unrelated_frames_are_rejected() -> None:
    source = tall_source()
    frame = source.crop((0, 0, 120, 200))
    noise = Image.effect_noise((120, 200), 120).convert("RGB")
    assert find_vertical_overlap(frame, noise) is None


def test_stitch_height_cap() -> None:
    source = tall_source()
    frames = [source.crop((0, y, 120, y + 200)) for y in (0, 80, 160)]
    stitched = stitch_vertical(frames, [120, 120], max_height=300)
    assert stitched.size == (120, 300)


def test_ignore_top_band() -> None:
    source = tall_source()
    previous = source.crop((0, 0, 120, 200)).copy()
    current = source.crop((0, 80, 120, 280)).copy()
    for image in (previous, current):
        ImageDraw.Draw(image).rectangle((0, 0, 119, 24), fill="white")
    overlap = find_vertical_overlap(previous, current, ignore_top=30)
    assert overlap is not None
    assert overlap >= 100
