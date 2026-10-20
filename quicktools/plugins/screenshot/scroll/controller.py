"""Background scrolling-capture worker with a small control bar."""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from typing import Callable

from PIL import Image

from quicktools.ui_theme import (
    BG,
    FlatButton,
    MUTED,
    TEXT,
    pick_fonts,
)

from ..capture import create_backend
from ..capture.base import CaptureBackend
from ..geometry import crop_global_rect
from ..models import Rect
from ..settings import ScreenshotSettings
from .stitcher import find_vertical_overlap, stitch_vertical

log = logging.getLogger(__name__)

DoneHandler = Callable[[Image.Image, int, str], None]
CancelHandler = Callable[[str], None]


class ScrollController:
    def __init__(
        self,
        root: tk.Misc,
        region: Rect,
        settings: ScreenshotSettings,
        *,
        on_done: DoneHandler,
        on_cancel: CancelHandler,
    ) -> None:
        self.root = root
        self.region = region
        self.settings = settings
        self.on_done = on_done
        self.on_cancel = on_cancel
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._stop = threading.Event()
        self._finish = threading.Event()
        self._closed = False
        self._after_job: str | None = None
        self._thread: threading.Thread | None = None
        self._buttons: list[FlatButton] = []
        self._window = tk.Toplevel(root)
        self._window.title("滚动截图")
        self._window.configure(bg=BG)
        self._window.resizable(False, False)
        self._window.attributes("-topmost", True)
        self._window.protocol("WM_DELETE_WINDOW", self.cancel)
        self._window.bind("<Escape>", lambda _event: self.cancel())
        self._build()
        self._window.deiconify()
        self._window.lift()
        self._window.after(30, self._focus)
        self._thread = threading.Thread(
            target=self._run, name="screenshot-scroll", daemon=True
        )
        self._thread.start()
        self._after_job = self.root.after(80, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        self.fonts = pick_fonts(self._window)
        shell = tk.Frame(self._window, bg=BG, padx=16, pady=12)
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell,
            text="正在滚动截图",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(13, "bold"),
        ).pack(anchor="w")
        self._progress_var = tk.StringVar(value="准备中…")
        tk.Label(
            shell,
            textvariable=self._progress_var,
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(anchor="w", pady=(4, 8))
        buttons = tk.Frame(shell, bg=BG)
        buttons.pack(fill="x")
        finish = FlatButton(
            buttons,
            "完成",
            self.finish,
            fonts=self.fonts,
            accent=True,
            font_size=9,
            padx=12,
            pady=6,
        )
        finish.pack(side="right")
        cancel = FlatButton(
            buttons,
            "取消",
            self.cancel,
            fonts=self.fonts,
            font_size=9,
            padx=12,
            pady=6,
        )
        cancel.pack(side="right", padx=(0, 8))
        self._buttons = [finish, cancel]
        width = 340
        height = 120
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(10, screen_width - width - 20)
        if self.region.top > 170:
            y = 20
        else:
            y = max(20, screen_height - height - 80)
        self._window.geometry(f"{width}x{height}+{x}+{y}")

    def _focus(self) -> None:
        try:
            self._window.focus_force()
        except tk.TclError:
            pass

    # -------------------------------------------------------------- worker
    def _grab(self, backend: CaptureBackend) -> Image.Image | None:
        try:
            captured = backend.grab_screen()
        except Exception:
            log.debug("滚动截图抓屏失败", exc_info=True)
            return None
        return crop_global_rect(captured, self.region)

    def _run(self) -> None:
        backend: CaptureBackend | None = None
        try:
            backend = create_backend()
            capabilities = backend.capabilities()
            if not backend.status.available or not capabilities.scrolling:
                self._queue.put(("error", "当前环境不支持滚动截图"))
                return
            # Let the screen repaint after the selection overlay disappears.
            time.sleep(max(0.15, self.settings.scroll_delay_ms / 1000))
            first = self._grab(backend)
            if first is None:
                self._queue.put(("error", "无法采集滚动区域"))
                return
            frames = [first]
            overlaps: list[int] = []
            previous = first
            total_height = first.height
            max_height = min(
                self.settings.scroll_max_height,
                max(1000, 40_000_000 // max(1, self.region.width)),
            )
            no_move = 0
            reason = ""
            self._queue.put(("progress", 1, total_height))
            while not self._stop.is_set() and not self._finish.is_set():
                backend.scroll_at(
                    self.region.center, -max(1, self.settings.scroll_notches)
                )
                time.sleep(max(0.05, self.settings.scroll_delay_ms / 1000))
                current = self._grab(backend)
                if current is None:
                    reason = "抓屏失败"
                    break
                overlap = find_vertical_overlap(
                    previous,
                    current,
                    ignore_top=self.settings.scroll_ignore_top,
                    ignore_bottom=self.settings.scroll_ignore_bottom,
                )
                if overlap is None:
                    reason = "无法继续检测滚动内容（可能已到达底部或内容变化过快）"
                    break
                if overlap >= int(previous.height * 0.97):
                    no_move += 1
                    previous = current
                    if no_move >= 2:
                        reason = "已到达底部"
                        break
                    continue
                no_move = 0
                overlap = max(0, min(current.height, int(overlap)))
                next_height = total_height + max(0, current.height - overlap)
                if next_height > max_height:
                    reason = "已达到高度上限"
                    break
                frames.append(current)
                overlaps.append(overlap)
                total_height = next_height
                previous = current
                self._queue.put(("progress", len(frames), total_height))
            if self._stop.is_set() and not self._finish.is_set():
                self._queue.put(("cancelled",))
                return
            if len(frames) < 2:
                self._queue.put(
                    ("error", reason or "没有检测到可滚动内容")
                )
                return
            stitched = stitch_vertical(
                frames,
                overlaps,
                max_height=max_height,
            )
            self._queue.put(
                ("done", stitched, len(frames), reason or "已完成")
            )
        except Exception as exc:
            log.exception("滚动截图失败")
            self._queue.put(("error", str(exc) or "滚动截图失败"))
        finally:
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass

    # --------------------------------------------------------------- poll
    def _poll(self) -> None:
        self._after_job = None
        if self._closed:
            return
        try:
            while True:
                event = self._queue.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _kind, frames, height = event
                    self._progress_var.set(
                        f"已捕获 {frames} 帧 · 拼接高度 {height}px"
                    )
                elif kind == "done":
                    _kind, image, frames, reason = event
                    self._close_window()
                    self.on_done(image, frames, reason)
                    return
                elif kind == "error":
                    _kind, message = event
                    self._close_window()
                    self.on_cancel(f"滚动截图失败：{message}")
                    return
                elif kind == "cancelled":
                    self._close_window()
                    self.on_cancel("已取消滚动截图")
                    return
        except queue.Empty:
            pass
        self._after_job = self.root.after(80, self._poll)

    # ------------------------------------------------------------ actions
    def finish(self) -> None:
        if self._closed:
            return
        self._finish.set()
        for button in self._buttons:
            button.set_enabled(False)
        self._progress_var.set("正在完成拼接…")

    def cancel(self) -> None:
        if self._closed:
            return
        self._stop.set()
        for button in self._buttons:
            button.set_enabled(False)
        self._progress_var.set("正在取消…")

    def dispose(self) -> None:
        self._closed = True
        self._stop.set()
        self._finish.set()
        if self._after_job is not None:
            try:
                self.root.after_cancel(self._after_job)
            except tk.TclError:
                pass
            self._after_job = None
        try:
            self._window.destroy()
        except tk.TclError:
            pass

    def _close_window(self) -> None:
        self._closed = True
        if self._after_job is not None:
            try:
                self.root.after_cancel(self._after_job)
            except tk.TclError:
                pass
            self._after_job = None
        try:
            self._window.destroy()
        except tk.TclError:
            pass
