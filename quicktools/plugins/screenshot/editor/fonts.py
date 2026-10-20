"""CJK-capable Pillow font discovery and metrics."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PIL import ImageFont

log = logging.getLogger(__name__)

_LINUX_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_WINDOWS_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\arial.ttf",
)


def _fc_match() -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans CJK SC"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = result.stdout.strip()
    return path if path and Path(path).exists() else None


def find_font_path() -> str | None:
    candidates = _WINDOWS_CANDIDATES if sys.platform == "win32" else _LINUX_CANDIDATES
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return _fc_match()


class FontResolver:
    def __init__(self) -> None:
        self.path = find_font_path()
        self._cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    @property
    def has_cjk_font(self) -> bool:
        return bool(self.path)

    def get(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        size = max(8, int(size))
        cached = self._cache.get(size)
        if cached is not None:
            return cached
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        if self.path:
            try:
                font = ImageFont.truetype(self.path, size)
            except Exception:
                log.exception("加载截图标注字体失败：%s", self.path)
                font = ImageFont.load_default()
        else:
            font = ImageFont.load_default()
        self._cache[size] = font
        return font

    def measure(self, text: str, size: int) -> tuple[int, int]:
        if not text:
            return 0, max(1, int(size))
        font = self.get(size)
        try:
            left, top, right, bottom = font.getbbox(text, anchor="lt")
            return max(1, right - left), max(1, bottom - top)
        except Exception:
            try:
                left, top, right, bottom = font.getbbox(text)
                return max(1, right - left), max(1, bottom - top)
            except Exception:
                return (
                    max(1, len(text) * max(8, int(size)) // 2),
                    max(8, int(size)),
                )
