"""Wayland screenshot backend using xdg-desktop-portal."""

from __future__ import annotations

import io
import logging

from PIL import Image

from ..models import (
    CapturedImage,
    CaptureMode,
    CaptureUnavailable,
    Point,
    ScreenInfo,
    WindowInfo,
)
from .base import CaptureCapabilities, CaptureStatus
from .portal import PortalScreenshotClient

log = logging.getLogger(__name__)


class WaylandBackend:
    name = "wayland"

    def __init__(self) -> None:
        import importlib.util

        if importlib.util.find_spec("jeepney") is None:
            self.status = CaptureStatus(
                False,
                "Wayland（缺少 jeepney）",
                detail="Wayland 截图需要 jeepney",
                install_hint="请重新安装 QuickTools 依赖，或 pip install jeepney",
            )
            self._available = False
        else:
            self.status = CaptureStatus(
                True, "Wayland（系统截图选择器）", "通过 xdg-desktop-portal 截图"
            )
            self._available = True

    def capabilities(self) -> CaptureCapabilities:
        return CaptureCapabilities(
            custom_overlay=False,
            window_enumeration=False,
            freeform=True,
            scrolling=False,
            interactive_portal=True,
        )

    def screens(self) -> list[ScreenInfo]:
        return []

    def cursor_position(self) -> Point | None:
        return None

    def _capture(self, *, interactive: bool) -> CapturedImage:
        if not self._available:
            raise CaptureUnavailable(self.status.detail)
        client = PortalScreenshotClient()
        png = client.capture(interactive=interactive)
        try:
            with Image.open(io.BytesIO(png)) as image:
                image.load()
                copied = image.convert("RGBA")
        except Exception as exc:
            raise CaptureUnavailable("系统截图不是有效图片") from exc
        return CapturedImage(
            image=copied,
            origin=Point(0, 0),
            scale=1.0,
            backend=self.name,
        )

    def grab_screen(self) -> CapturedImage:
        return self._capture(interactive=False)

    def list_windows(self) -> list[WindowInfo]:
        raise CaptureUnavailable("Wayland 不能由应用枚举窗口")

    def capture_interactive(self, mode: CaptureMode) -> CapturedImage:
        normalized = CaptureMode(str(getattr(mode, "value", mode)))
        return self._capture(interactive=normalized is not CaptureMode.FREEFORM)

    def raise_window(self, handle: int) -> bool:
        return False

    def scroll_at(self, point: Point, vertical: int) -> None:
        raise CaptureUnavailable("Wayland 不支持滚动截图")

    def close(self) -> None:
        pass
