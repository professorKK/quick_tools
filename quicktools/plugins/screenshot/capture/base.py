"""Capture backend contract shared by X11, Windows and Wayland."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import (
    CapturedImage,
    CaptureMode,
    CaptureUnavailable,
    Point,
    ScreenInfo,
    WindowInfo,
)


@dataclass(frozen=True)
class CaptureStatus:
    available: bool
    mode: str
    detail: str = ""
    install_hint: str = ""


@dataclass(frozen=True)
class CaptureCapabilities:
    custom_overlay: bool
    window_enumeration: bool
    freeform: bool
    scrolling: bool
    interactive_portal: bool


class CaptureBackend(Protocol):
    name: str
    status: CaptureStatus

    def capabilities(self) -> CaptureCapabilities: ...

    def screens(self) -> list[ScreenInfo]: ...

    def cursor_position(self) -> Point | None: ...

    def grab_screen(self) -> CapturedImage: ...

    def list_windows(self) -> list[WindowInfo]: ...

    def capture_interactive(self, mode: CaptureMode) -> CapturedImage: ...

    def raise_window(self, handle: int) -> bool: ...

    def scroll_at(self, point: Point, vertical: int) -> None: ...

    def close(self) -> None: ...


class UnavailableBackend:
    name = "unavailable"

    def __init__(
        self,
        reason: str,
        *,
        mode: str = "截图不可用",
        install_hint: str = "",
    ) -> None:
        self.status = CaptureStatus(
            False, mode, detail=reason, install_hint=install_hint
        )
        self.reason = reason

    def capabilities(self) -> CaptureCapabilities:
        return CaptureCapabilities(False, False, False, False, False)

    def screens(self) -> list[ScreenInfo]:
        return []

    def cursor_position(self) -> Point | None:
        return None

    def grab_screen(self) -> CapturedImage:
        raise CaptureUnavailable(self.reason)

    def list_windows(self) -> list[WindowInfo]:
        raise CaptureUnavailable(self.reason)

    def capture_interactive(self, mode: CaptureMode) -> CapturedImage:
        raise CaptureUnavailable(self.reason)

    def raise_window(self, handle: int) -> bool:
        return False

    def scroll_at(self, point: Point, vertical: int) -> None:
        raise CaptureUnavailable(self.reason)

    def close(self) -> None:
        pass
