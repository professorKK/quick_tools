"""Pillow-only overlap detection and vertical stitching."""

from __future__ import annotations

import logging
from typing import Sequence

from PIL import Image, ImageChops, ImageStat

log = logging.getLogger(__name__)


def _downscale(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image
    height = max(1, int(round(image.height * max_width / image.width)))
    return image.resize((max_width, height), Image.LANCZOS)


def _band_score(
    previous: Image.Image, current: Image.Image, overlap: int
) -> float:
    height = previous.height
    width = previous.width
    if overlap <= 0 or overlap > height:
        return 1e9
    prev_band = previous.crop((0, height - overlap, width, height))
    cur_band = current.crop((0, 0, width, overlap))
    diff = ImageChops.difference(prev_band, cur_band)
    return float(ImageStat.Stat(diff).mean[0])


def find_vertical_overlap(
    previous: Image.Image,
    current: Image.Image,
    *,
    ignore_top: int = 0,
    ignore_bottom: int = 0,
    min_ratio: float = 0.15,
    max_ratio: float = 0.85,
    threshold: float = 6.0,
    max_width: int = 360,
) -> int | None:
    """Return the number of overlapping rows, or None if uncertain.

    ``ignore_top``/``ignore_bottom`` exclude fixed headers and footers from
    matching. The returned value is in full-frame rows; callers appending
    ``current[overlap:]`` get the new content.
    """
    if previous.size != current.size:
        raise ValueError("滚动截图帧尺寸不一致")
    width, height = previous.size
    if width < 10 or height < 10:
        return None
    top = max(0, min(int(ignore_top), height - 2))
    bottom = max(0, min(int(ignore_bottom), height - top - 2))
    prev_cmp = previous.crop((0, top, width, height - bottom)).convert("L")
    cur_cmp = current.crop((0, top, width, height - bottom)).convert("L")
    prev_small = _downscale(prev_cmp, max_width)
    cur_small = _downscale(cur_cmp, max_width)
    small_height = prev_small.height
    small_width = prev_small.width
    if small_height < 12 or small_width < 8:
        return None

    # Identical frames mean the page did not move (bottom reached).
    identical = ImageChops.difference(prev_small, cur_small)
    if float(ImageStat.Stat(identical).mean[0]) < 0.5:
        return height

    left = small_width // 5
    right = max(left + 1, small_width * 4 // 5)
    prev_band = prev_small.crop((left, 0, right, small_height))
    cur_band = cur_small.crop((left, 0, right, small_height))
    min_overlap = max(2, int(small_height * min_ratio))
    max_overlap = min(small_height - 2, int(small_height * max_ratio))
    if max_overlap <= min_overlap:
        return None

    best_overlap = None
    best_score = 1e9
    for overlap in range(max_overlap, min_overlap - 1, -1):
        score = _band_score(prev_band, cur_band, overlap)
        if score < best_score:
            best_score = score
            best_overlap = overlap
    if best_overlap is None:
        return None
    for overlap in range(
        max(min_overlap, best_overlap - 2),
        min(max_overlap, best_overlap + 2) + 1,
    ):
        score = _band_score(prev_band, cur_band, overlap)
        if score < best_score:
            best_score = score
            best_overlap = overlap
    if best_score > threshold:
        return None
    full_overlap = int(round(best_overlap / small_height * prev_cmp.height))
    return min(height, max(0, full_overlap + top))


def stitch_vertical(
    frames: Sequence[Image.Image],
    overlaps: Sequence[int],
    *,
    max_height: int | None = None,
) -> Image.Image:
    """Append ``frame[overlap:]`` for each frame in order."""
    if not frames:
        raise ValueError("没有可拼接的截图帧")
    if len(frames) - 1 != len(overlaps):
        raise ValueError("截图帧与重叠数量不一致")
    width, height = frames[0].size
    mode = frames[0].mode
    total_height = height
    for frame, overlap in zip(frames[1:], overlaps):
        if frame.size != (width, height):
            raise ValueError("滚动截图帧尺寸不一致")
        total_height += max(0, height - max(0, min(height, int(overlap))))
    if max_height is not None:
        total_height = min(total_height, max(1, int(max_height)))
    result = Image.new(mode, (width, total_height))
    result.paste(frames[0], (0, 0))
    cursor = height
    for frame, overlap in zip(frames[1:], overlaps):
        start = max(0, min(height, int(overlap)))
        part = frame.crop((0, start, width, height))
        remaining = total_height - cursor
        if remaining <= 0:
            break
        if part.height > remaining:
            part = part.crop((0, 0, width, remaining))
        result.paste(part, (0, cursor))
        cursor += part.height
    return result
