"""Pure data types shared by the screenshot plugin.

This module must not import Tk or platform-specific libraries so capture and
geometry logic can be tested on any supported platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PIL import Image


class CaptureError(Exception):
    """Base error for capture and editor operations."""


class CaptureCancelled(CaptureError):
    """The user cancelled the capture or portal dialog."""


class CaptureUnavailable(CaptureError):
    """The current session cannot provide the requested capture mode."""


@dataclass(frozen=True, order=True)
class Point:
    x: float
    y: float

    def as_int(self) -> tuple[int, int]:
        return int(round(self.x)), int(round(self.y))


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def normalized(self) -> "Rect":
        x1, x2 = sorted((self.x, self.right))
        y1, y2 = sorted((self.y, self.bottom))
        return Rect(x1, y1, max(0, x2 - x1), max(0, y2 - y1))

    def contains(self, point: Point) -> bool:
        return (
            self.x <= point.x < self.right
            and self.y <= point.y < self.bottom
        )

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def clamp(self, bounds: "Rect") -> "Rect":
        left = max(self.x, bounds.x)
        top = max(self.y, bounds.y)
        right = min(self.right, bounds.right)
        bottom = min(self.bottom, bounds.bottom)
        return Rect(left, top, max(0, right - left), max(0, bottom - top))

    @classmethod
    def from_points(cls, start: Point, end: Point) -> "Rect":
        x1, x2 = sorted((start.x, end.x))
        y1, y2 = sorted((start.y, end.y))
        return cls(
            int(round(x1)),
            int(round(y1)),
            max(0, int(round(x2 - x1))),
            max(0, int(round(y2 - y1))),
        )


@dataclass(frozen=True)
class ScreenInfo:
    name: str
    rect: Rect
    scale: float = 1.0
    primary: bool = False


@dataclass(frozen=True)
class CapturedImage:
    image: Image.Image
    origin: Point = Point(0, 0)
    scale: float = 1.0
    backend: str = ""


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    app_name: str
    rect: Rect
    z_order: int = 0


class CaptureMode(str, Enum):
    REGION = "region"
    WINDOW = "window"
    FREEFORM = "freeform"
    SCROLL = "scroll"
    IMPORT = "import"

    @property
    def label(self) -> str:
        return {
            CaptureMode.REGION: "矩形截图",
            CaptureMode.WINDOW: "窗口截图",
            CaptureMode.FREEFORM: "自由截图",
            CaptureMode.SCROLL: "滚动截图",
            CaptureMode.IMPORT: "导入图片",
        }[self]

    @classmethod
    def from_value(cls, value: str) -> "CaptureMode":
        normalized = value.strip().lower()
        for mode in cls:
            if mode.value == normalized:
                return mode
        raise CaptureError(f"未知截图模式：{value}")
