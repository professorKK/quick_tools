"""X11 screen and window capture using python-xlib."""

from __future__ import annotations

import logging

from PIL import Image
from Xlib import X, display
from Xlib.ext import randr, xtest

from ..models import (
    CapturedImage,
    CaptureMode,
    CaptureUnavailable,
    Point,
    Rect,
    ScreenInfo,
    WindowInfo,
)
from .base import CaptureCapabilities, CaptureStatus

log = logging.getLogger(__name__)

_SKIPPED_WINDOW_TYPES = {
    "_NET_WM_WINDOW_TYPE_DESKTOP",
    "_NET_WM_WINDOW_TYPE_DOCK",
    "_NET_WM_WINDOW_TYPE_TOOLBAR",
    "_NET_WM_WINDOW_TYPE_MENU",
    "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
    "_NET_WM_WINDOW_TYPE_POPUP_MENU",
    "_NET_WM_WINDOW_TYPE_TOOLTIP",
    "_NET_WM_WINDOW_TYPE_NOTIFICATION",
    "_NET_WM_WINDOW_TYPE_COMBO",
    "_NET_WM_WINDOW_TYPE_DND",
    "_NET_WM_WINDOW_TYPE_SPLASH",
}


def _decode_text_property(value, type_name: str) -> str:
    """Decode a WM_NAME/_NET_WM_NAME property value.

    ICCCM ``STRING`` is Latin-1 while ``UTF8_STRING`` is UTF-8.
    ``COMPOUND_TEXT`` may contain escape sequences, so it is only decoded as a
    fallback; callers prefer ``_NET_WM_NAME`` which is always UTF-8.
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    if not isinstance(value, (bytes, bytearray)):
        return ""
    raw = bytes(value)
    if (type_name or "").upper() == "STRING":
        text = raw.decode("latin-1", "replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", "replace")
    return text.replace("\x00", "").strip()


class X11Backend:
    name = "x11"

    def __init__(self) -> None:
        self._display = display.Display()
        self._screen = self._display.screen()
        self._root = self._screen.root
        geometry = self._root.get_geometry()
        self._width = int(geometry.width)
        self._height = int(geometry.height)
        self._depth = int(geometry.depth)
        if self._depth not in (24, 32):
            raise CaptureUnavailable(
                f"当前 X11 显示深度为 {self._depth}，暂不支持截图"
            )
        self._atoms: dict[str, int] = {}
        self.status = CaptureStatus(True, "X11", "原生抓屏")

    # ------------------------------------------------------------ helpers
    def _atom(self, name: str) -> int:
        atom = self._atoms.get(name)
        if atom is None:
            atom = self._display.intern_atom(name)
            self._atoms[name] = atom
        return atom

    def _property(self, window, name: str):
        try:
            return window.get_full_property(self._atom(name), X.AnyPropertyType)
        except Exception:
            return None

    def _atom_name(self, atom: int) -> str:
        try:
            return self._display.get_atom_name(atom)
        except Exception:
            return ""

    def _text_property(self, window, name: str) -> str:
        prop = self._property(window, name)
        if prop is None:
            return ""
        try:
            type_name = self._atom_name(int(prop.property_type))
        except Exception:
            type_name = ""
        return _decode_text_property(prop.value, type_name)

    def _window_title(self, window) -> str:
        # python-xlib 的 get_wm_name() 只解码 STRING；微信、Chrome、Firefox
        # 等使用 UTF8_STRING/COMPOUND_TEXT，会直接返回空标题。
        for name in ("_NET_WM_NAME", "WM_NAME"):
            try:
                title = self._text_property(window, name)
            except Exception:
                title = ""
            if title:
                return title
        return ""

    def _window_class(self, window) -> str:
        try:
            values = window.get_wm_class()
        except Exception:
            return ""
        if not values:
            return ""
        if isinstance(values, (list, tuple)):
            return str(values[-1])
        return str(values)

    # ----------------------------------------------------------- protocol
    def capabilities(self) -> CaptureCapabilities:
        return CaptureCapabilities(
            custom_overlay=True,
            window_enumeration=True,
            freeform=True,
            scrolling=True,
            interactive_portal=False,
        )

    def screens(self) -> list[ScreenInfo]:
        monitors: list[ScreenInfo] = []
        try:
            reply = randr.get_monitors(self._root)
            raw_monitors = list(getattr(reply, "monitors", []) or [])
        except Exception:
            log.debug("XRandR 显示器枚举失败，退化为整个 X screen", exc_info=True)
            raw_monitors = []
        for monitor in raw_monitors:
            try:
                width = int(monitor.width_in_pixels)
                height = int(monitor.height_in_pixels)
                if width <= 0 or height <= 0:
                    continue
                monitors.append(
                    ScreenInfo(
                        name=self._atom_name(int(monitor.name)) or "X11",
                        rect=Rect(
                            int(monitor.x), int(monitor.y), width, height
                        ),
                        scale=1.0,
                        primary=bool(monitor.primary),
                    )
                )
            except Exception:
                log.debug("跳过无法解析的 XRandR 显示器", exc_info=True)
        if not monitors:
            monitors.append(
                ScreenInfo(
                    name="X11",
                    rect=Rect(0, 0, self._width, self._height),
                    scale=1.0,
                    primary=True,
                )
            )
        return monitors

    def cursor_position(self) -> Point | None:
        try:
            pointer = self._root.query_pointer()
            return Point(int(pointer.root_x), int(pointer.root_y))
        except Exception:
            return None

    def grab_screen(self) -> CapturedImage:
        try:
            raw = self._root.get_image(
                0, 0, self._width, self._height, X.ZPixmap, 0xFFFFFFFF
            ).data
        except Exception as exc:
            raise CaptureUnavailable(f"X11 抓屏失败：{exc}") from exc
        expected = self._width * self._height
        if expected <= 0:
            raise CaptureUnavailable("X11 屏幕尺寸无效")
        bytes_per_pixel = len(raw) // expected
        if bytes_per_pixel == 4:
            raw_mode = "BGRX"
        elif bytes_per_pixel == 3:
            raw_mode = "BGR"
        else:
            raise CaptureUnavailable(
                f"不支持的 X11 像素格式（每像素 {bytes_per_pixel} 字节）"
            )
        try:
            image = Image.frombuffer(
                "RGB",
                (self._width, self._height),
                raw,
                "raw",
                raw_mode,
                0,
                1,
            ).copy()
        except Exception as exc:
            raise CaptureUnavailable(f"X11 图像解码失败：{exc}") from exc
        return CapturedImage(
            image=image,
            origin=Point(0, 0),
            scale=1.0,
            backend=self.name,
        )

    def list_windows(self) -> list[WindowInfo]:
        clients = self._property(self._root, "_NET_CLIENT_LIST_STACKING")
        if clients is None:
            clients = self._property(self._root, "_NET_CLIENT_LIST")
        if clients is None:
            return []
        windows: list[WindowInfo] = []
        values = list(getattr(clients, "value", []) or [])
        for index, window_id in enumerate(values):
            try:
                window = self._display.create_resource_object(
                    "window", int(window_id)
                )
                attributes = window.get_attributes()
                if attributes.map_state != X.IsViewable:
                    continue
                if getattr(attributes, "override_redirect", 0):
                    continue
                states = self._property(window, "_NET_WM_STATE")
                if states is not None and (
                    self._atom("_NET_WM_STATE_HIDDEN")
                    in {int(atom) for atom in list(states.value)}
                ):
                    # 最小化或位于其他工作区：冻结画面上看不到，不能参与选区。
                    continue
                title = self._window_title(window)
                app_name = self._window_class(window)
                if not title:
                    title = app_name
                if not title:
                    continue
                window_types = self._property(window, "_NET_WM_WINDOW_TYPE")
                if window_types is not None:
                    type_names = {
                        self._atom_name(int(atom))
                        for atom in list(window_types.value)
                    }
                    if type_names & _SKIPPED_WINDOW_TYPES:
                        continue
                geometry = window.get_geometry()
                if geometry.width <= 1 or geometry.height <= 1:
                    continue
                translated = self._root.translate_coords(window, 0, 0)
                left = int(translated.x)
                top = int(translated.y)
                width = int(geometry.width)
                height = int(geometry.height)
                extents = self._property(window, "_NET_FRAME_EXTENTS")
                if extents is not None and len(extents.value) >= 4:
                    frame_left, frame_right, frame_top, frame_bottom = (
                        int(value) for value in list(extents.value)[:4]
                    )
                    left -= frame_left
                    top -= frame_top
                    width += frame_left + frame_right
                    height += frame_top + frame_bottom
                windows.append(
                    WindowInfo(
                        handle=int(window_id),
                        title=title,
                        app_name=app_name or title,
                        rect=Rect(left, top, width, height),
                        z_order=index,
                    )
                )
            except Exception:
                log.debug("跳过无法读取的 X11 窗口 %s", window_id, exc_info=True)
        return windows

    def capture_interactive(self, mode: CaptureMode) -> CapturedImage:
        raise CaptureUnavailable("X11 使用截图插件的自定义选区覆盖层")

    def raise_window(self, handle: int) -> bool:
        try:
            window = self._display.create_resource_object("window", int(handle))
            window.configure(stack_mode=X.Above)
            self._display.sync()
            return True
        except Exception:
            log.debug("抬升 X11 窗口失败：%s", handle, exc_info=True)
            return False

    def scroll_at(self, point: Point, vertical: int) -> None:
        if vertical == 0:
            return
        try:
            self._root.warp_pointer(int(point.x), int(point.y))
            self._display.sync()
            button = 4 if vertical > 0 else 5
            for _ in range(min(50, max(1, abs(int(vertical))))):
                self._display.xtest_fake_input(X.ButtonPress, button)
                self._display.xtest_fake_input(X.ButtonRelease, button)
            self._display.sync()
        except Exception as exc:
            raise CaptureUnavailable(f"X11 滚轮注入失败：{exc}") from exc

    def close(self) -> None:
        try:
            self._display.close()
        except Exception:
            pass
