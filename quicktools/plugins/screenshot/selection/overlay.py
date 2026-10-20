"""Frozen-screen selection overlay for region, window and freeform capture."""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk

from quicktools.ui_theme import ACCENT

from ..editor.mask import freeform_crop
from ..geometry import crop_global_rect, crop_screen, screen_local_to_global
from ..models import CapturedImage, CaptureMode, Point, Rect, ScreenInfo, WindowInfo
from .placement import place_overlay

log = logging.getLogger(__name__)

_HINTS = {
    CaptureMode.REGION: "拖拽选择区域 · Esc / 右键取消",
    CaptureMode.WINDOW: "点击选择窗口 · Esc / 右键取消",
    CaptureMode.FREEFORM: "按住拖拽画套索 · Esc / 右键取消",
    CaptureMode.SCROLL: "拖拽选择滚动区域 · Esc / 右键取消",
}


class CaptureOverlay:
    """Show a frozen monitor image and let the user select a capture area."""

    def __init__(
        self,
        root: tk.Misc,
        captured: CapturedImage,
        screen: ScreenInfo,
        mode: CaptureMode,
        windows: list[WindowInfo],
        on_selected: Callable[[Image.Image], None],
        on_cancel: Callable[[], None],
        *,
        on_window_selected: Callable[[WindowInfo], None] | None = None,
        on_region_selected: Callable[[Image.Image, Rect, ScreenInfo], None]
        | None = None,
    ) -> None:
        self._root = root
        self._captured = captured
        self._screen = screen
        self._mode = CaptureMode(str(getattr(mode, "value", mode)))
        self._windows = windows
        self._on_selected = on_selected
        self._on_cancel = on_cancel
        self._on_window_selected = on_window_selected
        self._on_region_selected = on_region_selected
        self._start: Point | None = None
        self._selection: Rect | None = None
        self._freeform_points: list[Point] = []
        self._freeform_item: int | None = None
        self._destroyed = False
        self._grab_job: str | None = None
        self._top = tk.Toplevel(root)
        self._top.withdraw()
        self._top.overrideredirect(True)
        self._top.configure(bg="black")
        try:
            self._top.attributes("-topmost", True)
        except tk.TclError:
            pass
        place_overlay(self._top, screen.rect)
        self._top.bind("<Escape>", lambda _event: self._cancel())
        self._top.bind("<Button-3>", lambda _event: self._cancel())

        cursor = "hand2" if mode is CaptureMode.WINDOW else "crosshair"
        self._canvas = tk.Canvas(
            self._top,
            bg="black",
            highlightthickness=0,
            bd=0,
            cursor=cursor,
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Button-3>", lambda _event: self._cancel())

        monitor_image = crop_screen(captured, screen)
        if monitor_image is None:
            self.destroy()
            self._on_cancel()
            return
        self._monitor_image = monitor_image
        self._photo = ImageTk.PhotoImage(monitor_image, master=self._top)
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

        self._dim = [
            self._canvas.create_rectangle(
                0, 0, 0, 0, fill="black", outline="", stipple="gray50"
            )
            for _ in range(4)
        ]
        self._selection_item = self._canvas.create_rectangle(
            0, 0, 0, 0, outline=ACCENT, width=2, dash=(5, 3)
        )
        self._window_rects = self._build_window_rects(windows)
        self._hint = tk.Label(
            self._top,
            text=_HINTS.get(mode, "选择截图区域 · Esc / 右键取消"),
            bg="#111827",
            fg="white",
            padx=10,
            pady=5,
            font=("TkDefaultFont", 10),
        )
        self._hint.place(x=12, y=12)
        self._size_var = tk.StringVar(value="")
        self._size = tk.Label(
            self._top,
            textvariable=self._size_var,
            bg="#111827",
            fg="white",
            padx=8,
            pady=3,
            font=("TkDefaultFont", 10),
        )

        self._top.deiconify()
        self._top.lift()
        try:
            self._top.focus_force()
        except tk.TclError:
            pass
        self._grab_job = self._top.after(30, self._grab)

    def _build_window_rects(
        self, windows: list[WindowInfo]
    ) -> list[tuple[WindowInfo, Rect]]:
        bounds = Rect(0, 0, self._screen.rect.width, self._screen.rect.height)
        result: list[tuple[WindowInfo, Rect]] = []
        for window in windows:
            local = Rect(
                window.rect.x - self._screen.rect.x,
                window.rect.y - self._screen.rect.y,
                window.rect.width,
                window.rect.height,
            ).clamp(bounds)
            if local.width > 1 and local.height > 1:
                result.append((window, local))
        return result

    def _grab(self) -> None:
        self._grab_job = None
        if self._destroyed:
            return
        try:
            self._top.grab_set()
            self._top.focus_force()
        except tk.TclError:
            pass

    # -------------------------------------------------------------- events
    def _canvas_point(self, event: tk.Event) -> Point:
        x = max(0, min(int(event.x), self._screen.rect.width))
        y = max(0, min(int(event.y), self._screen.rect.height))
        return Point(x, y)

    def _on_press(self, event: tk.Event) -> None:
        point = self._canvas_point(event)
        if self._mode is CaptureMode.WINDOW:
            window, local = self._window_at(point)
            if window is None or local is None:
                return
            self._show_window_highlight(local, window.title)
            self._top.update_idletasks()
            self.destroy()
            if self._on_window_selected is not None:
                self._on_window_selected(window)
            else:
                self._on_selected(self._crop_monitor(local))
            return
        if self._mode is CaptureMode.FREEFORM:
            self._freeform_points = [point]
            self._freeform_item = self._canvas.create_line(
                point.x,
                point.y,
                point.x,
                point.y,
                fill=ACCENT,
                width=2,
                smooth=True,
                splinesteps=12,
                tags="freeform",
            )
            return
        if self._mode not in (CaptureMode.REGION, CaptureMode.SCROLL):
            return
        self._start = point
        self._selection = Rect(int(point.x), int(point.y), 0, 0)
        self._update_selection()

    def _on_motion(self, event: tk.Event) -> None:
        point = self._canvas_point(event)
        if self._mode is CaptureMode.WINDOW:
            window, local = self._window_at(point)
            if window is not None and local is not None:
                self._show_window_highlight(local, window.title)
            else:
                self._clear_highlight()
            return
        if self._mode is CaptureMode.FREEFORM:
            if not self._freeform_points:
                return
            last = self._freeform_points[-1]
            if abs(point.x - last.x) + abs(point.y - last.y) < 2:
                return
            self._freeform_points.append(point)
            if self._freeform_item is not None:
                coords: list[float] = []
                for item in self._freeform_points:
                    coords.extend((item.x, item.y))
                self._canvas.coords(self._freeform_item, *coords)
            return
        if self._start is None or self._mode not in (
            CaptureMode.REGION,
            CaptureMode.SCROLL,
        ):
            return
        self._selection = Rect.from_points(self._start, point)
        self._update_selection()

    def _on_release(self, event: tk.Event) -> None:
        point = self._canvas_point(event)
        if self._mode is CaptureMode.FREEFORM:
            points = self._freeform_points
            self._freeform_points = []
            if self._freeform_item is not None:
                self._canvas.delete(self._freeform_item)
                self._freeform_item = None
            if not points or (
                abs(point.x - points[-1].x) + abs(point.y - points[-1].y) >= 2
            ):
                points.append(point)
            if len(points) < 3:
                return
            try:
                image = freeform_crop(self._monitor_image, points)
            except ValueError:
                return
            self.destroy()
            self._on_selected(image)
            return
        if self._mode not in (CaptureMode.REGION, CaptureMode.SCROLL):
            return
        if self._start is None or self._selection is None:
            return
        selection = self._selection
        self._start = None
        if selection.width < 4 or selection.height < 4:
            self._selection = None
            self._update_selection()
            return
        global_rect = screen_local_to_global(self._screen, selection)
        image = crop_global_rect(self._captured, global_rect)
        if image is None:
            self._cancel()
            return
        self.destroy()
        if self._on_region_selected is not None:
            self._on_region_selected(image, global_rect, self._screen)
        else:
            self._on_selected(image)

    # -------------------------------------------------------------- window
    def _window_at(self, point: Point) -> tuple[WindowInfo | None, Rect | None]:
        best: tuple[WindowInfo, Rect] | None = None
        for window, local in self._window_rects:
            if not local.contains(point):
                continue
            if best is None or window.z_order > best[0].z_order:
                best = (window, local)
        if best is None:
            return None, None
        return best

    def _show_window_highlight(self, local: Rect, title: str) -> None:
        self._selection = local
        self._update_selection()
        self._size_var.set((title or "窗口")[:60])
        x = min(max(8, local.left), max(8, self._screen.rect.width - 220))
        y = min(max(8, local.top - 32), max(8, self._screen.rect.height - 32))
        self._size.place(x=x, y=y)

    def _clear_highlight(self) -> None:
        self._selection = None
        self._update_selection()
        self._size.place_forget()

    def _crop_monitor(self, local: Rect) -> Image.Image:
        return self._monitor_image.crop(
            (local.left, local.top, local.right, local.bottom)
        )

    # ------------------------------------------------------------- region
    def _update_selection(self) -> None:
        selection = self._selection
        width = self._screen.rect.width
        height = self._screen.rect.height
        if selection is None:
            coords = (
                (0, 0, width, 0),
                (0, height, width, height),
                (0, 0, 0, height),
                (width, 0, width, height),
            )
            for item, box in zip(self._dim, coords):
                self._canvas.coords(item, *box)
            self._canvas.coords(self._selection_item, 0, 0, 0, 0)
            self._size.place_forget()
            return
        left, top = selection.left, selection.top
        right, bottom = selection.right, selection.bottom
        boxes = (
            (0, 0, width, top),
            (0, bottom, width, height),
            (0, top, left, bottom),
            (right, top, width, bottom),
        )
        for item, box in zip(self._dim, boxes):
            self._canvas.coords(item, *box)
        self._canvas.coords(
            self._selection_item, left, top, right, bottom
        )
        self._size_var.set(f"{selection.width} × {selection.height}")
        x = min(max(8, left), max(8, width - 120))
        y = min(max(8, top - 32), max(8, height - 32))
        self._size.place(x=x, y=y)

    # ------------------------------------------------------------ lifecycle
    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self._grab_job is not None:
            try:
                self._top.after_cancel(self._grab_job)
            except tk.TclError:
                pass
            self._grab_job = None
        try:
            self._top.grab_release()
        except tk.TclError:
            pass
        try:
            self._top.destroy()
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        self.destroy()
        self._on_cancel()
