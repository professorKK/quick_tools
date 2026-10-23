"""Interactive Tk canvas for screenshot annotations."""

from __future__ import annotations

import logging
import math
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable

from PIL import Image, ImageTk

from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    FlatButton,
    Fonts,
    MUTED,
    PANEL,
    TEXT,
    center_on_screen,
)

from quicktools.modal_dialogs import (
    open_native_file_dialog,
    run_modal_dialog,
)

from ..models import Point, Rect
from .annotations import (
    RESIZABLE_TOOLS,
    Annotation,
    Style,
    Tool,
    arrow_bounds,
    brush_bounds,
    coerce_tool,
    handle_points,
    resize_bounds,
    translate_annotation,
)
from .document import AnnotationDocument
from .render import render_annotation_preview

log = logging.getLogger(__name__)

CANVAS_BG = "#d8d5cf"

_TOOL_NAMES = {
    Tool.SELECT: "选择",
    Tool.RECT: "矩形",
    Tool.ELLIPSE: "圆形",
    Tool.ARROW: "箭头",
    Tool.BRUSH: "画笔",
    Tool.TEXT: "文字",
    Tool.NUMBER: "序号",
    Tool.MOSAIC: "马赛克",
    Tool.STICKER: "贴纸",
    Tool.WATERMARK: "水印",
    Tool.CROP: "裁剪",
    Tool.LASSO: "套索裁剪",
}

StatusHandler = Callable[[str], None]
ChangeHandler = Callable[[], None]


class _TextPromptDialog(tk.Toplevel):
    """Small text prompt that tolerates a busy X pointer grab.

    tkinter.simpledialog calls grab_set() without guarding it; if another
    dialog or a stale overlay grab froze the pointer, that raises TclError and
    aborts the whole callback. This dialog tries to grab but keeps working
    without one.
    """

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        prompt: str,
        fonts: Fonts,
    ) -> None:
        super().__init__(parent)
        self.result: str | None = None
        self._fonts = fonts
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        # Managed dialogs are composited below the override-redirect editor on
        # X11; use the same frameless style as the rest of QuickTools.
        self.overrideredirect(True)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Return>", lambda _event: self.ok())
        self.bind("<Escape>", lambda _event: self.cancel())

        shell = tk.Frame(
            self,
            bg=BG,
            padx=18,
            pady=14,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell,
            text=title,
            bg=BG,
            fg=TEXT,
            anchor="w",
            font=fonts.u(11, "bold"),
        ).pack(fill="x", pady=(0, 6))
        tk.Label(
            shell,
            text=prompt,
            bg=BG,
            fg=TEXT,
            anchor="w",
            font=fonts.u(10),
        ).pack(fill="x")
        self._value = tk.StringVar()
        self._entry = tk.Entry(
            shell,
            textvariable=self._value,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
            font=fonts.u(11),
        )
        self._entry.pack(fill="x", pady=(8, 12))
        buttons = tk.Frame(shell, bg=BG)
        buttons.pack(fill="x")
        FlatButton(
            buttons,
            "确定",
            self.ok,
            fonts=fonts,
            accent=True,
            font_size=9,
            padx=14,
            pady=6,
        ).pack(side="right")
        FlatButton(
            buttons,
            "取消",
            self.cancel,
            fonts=fonts,
            font_size=9,
            padx=14,
            pady=6,
        ).pack(side="right", padx=(0, 8))

        center_on_screen(self, 440, 210, parent=parent)
        self.deiconify()
        self.lift()
        try:
            from quicktools import x11_focus

            x11_focus.force_foreground(self)
        except Exception:
            pass
        try:
            self.focus_force()
            self._entry.focus_force()
        except tk.TclError:
            pass
        try:
            self.grab_set()
        except tk.TclError:
            # A stale/foreign grab must not prevent the prompt from working.
            log.warning("水印对话框无法取得 grab，将在无 grab 状态下继续")
        self.wait_window(self)

    def ok(self) -> str:
        self.result = self._value.get().strip()
        self._finish()
        return "break"

    def cancel(self) -> str:
        self.result = None
        self._finish()
        return "break"

    def _finish(self) -> None:
        try:
            current = self.grab_current()
            if current is self:
                current.grab_release()
        except (tk.TclError, KeyError):
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


class AnnotationCanvas(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        document: AnnotationDocument,
        fonts: Fonts,
        *,
        style: Style,
        on_status: StatusHandler | None = None,
        on_change: ChangeHandler | None = None,
        on_zoom: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(master, bg=CANVAS_BG)
        self.document = document
        self.fonts = fonts
        self.style = style.copy()
        self.on_status = on_status
        self.on_change = on_change
        self.on_zoom = on_zoom
        self.on_tool_change: Callable[[Tool], None] | None = None
        self.tool = Tool.SELECT
        self._view_scale = 1.0
        self._fit_scale = 1.0
        self._fit_mode = True
        self._fit_cap_one = True
        self._pan_start: tuple[float, float, float, float] | None = None
        self._space_pan = False
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._base_photo: ImageTk.PhotoImage | None = None
        self._sticker_photos: list[ImageTk.PhotoImage] = []
        self._text_photos: list[ImageTk.PhotoImage] = []
        self._image_item: int | None = None
        self._redraw_job: str | None = None
        self._drag_mode: str | None = None
        self._drag_start: Point | None = None
        self._drag_original: Annotation | None = None
        self._drag_handle: str | None = None
        self._temp: Annotation | None = None
        self._lasso_points: list[Point] = []
        self._lasso_item: int | None = None
        self._crop_rect: Rect | None = None
        self._crop_original: Rect | None = None
        self._crop_handle: str | None = None
        self._entry: tk.Entry | None = None
        self._entry_point: Point | None = None
        self._entry_existing: Annotation | None = None
        self._disposed = False

        self.canvas = tk.Canvas(
            self,
            bg=CANVAS_BG,
            highlightthickness=0,
            bd=0,
            cursor="arrow",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._schedule_view)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Button-4>", self._on_wheel_linux)
        self.canvas.bind("<Button-5>", self._on_wheel_linux)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", self._on_pan_motion)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<KeyPress-space>", self._on_space_press)
        self.canvas.bind("<KeyRelease-space>", self._on_space_release)
        self.canvas.bind("<FocusOut>", self._on_canvas_focus_out)
        self._initial_view_job: str | None = self.after(
            50, self._recompute_view
        )

    # ------------------------------------------------------------- view
    def _schedule_view(self, _event=None) -> None:
        if self._disposed:
            return
        if self._redraw_job is not None:
            try:
                self.after_cancel(self._redraw_job)
            except tk.TclError:
                pass
        self._redraw_job = self.after(40, self._recompute_view)

    def _canvas_size(self) -> tuple[int, int]:
        self.update_idletasks()
        return (
            max(1, self.canvas.winfo_width()),
            max(1, self.canvas.winfo_height()),
        )

    def _compute_fit_scale(
        self,
        canvas_width: int,
        canvas_height: int,
        *,
        cap_one: bool = False,
    ) -> float:
        image_width, image_height = self.document.image_size
        scale = min(
            canvas_width / max(1, image_width),
            canvas_height / max(1, image_height),
        )
        if cap_one:
            scale = min(scale, 1.0)
        return max(0.02, scale)

    def render_initial_view(self) -> None:
        """Render the first fit view before the host window is painted."""
        job = self._initial_view_job
        self._initial_view_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        self._recompute_view()

    def _recompute_view(self) -> None:
        self._redraw_job = None
        if self._disposed:
            return
        canvas_width, canvas_height = self._canvas_size()
        if canvas_width <= 2 or canvas_height <= 2:
            return
        self._fit_scale = self._compute_fit_scale(
            canvas_width, canvas_height, cap_one=self._fit_cap_one
        )
        if self._fit_mode:
            self._view_scale = self._fit_scale
        self._view_scale = max(0.02, self._view_scale)
        self._clamp_offsets(canvas_width, canvas_height)
        self._render_viewport(canvas_width, canvas_height)
        self._notify_zoom()
        self.redraw_annotations()

    def _clamp_offsets(self, canvas_width: int, canvas_height: int) -> None:
        image_width, image_height = self.document.image_size
        display_width = image_width * self._view_scale
        display_height = image_height * self._view_scale
        if display_width <= canvas_width:
            self._offset_x = (canvas_width - display_width) / 2
        else:
            self._offset_x = min(
                0.0, max(canvas_width - display_width, self._offset_x)
            )
        if display_height <= canvas_height:
            self._offset_y = (canvas_height - display_height) / 2
        else:
            self._offset_y = min(
                0.0, max(canvas_height - display_height, self._offset_y)
            )

    def _render_viewport(self, canvas_width: int, canvas_height: int) -> None:
        image_width, image_height = self.document.image_size
        scale = self._view_scale
        left = max(0, int(math.floor((0 - self._offset_x) / scale)))
        top = max(0, int(math.floor((0 - self._offset_y) / scale)))
        right = min(
            image_width,
            int(math.ceil((canvas_width - self._offset_x) / scale)),
        )
        bottom = min(
            image_height,
            int(math.ceil((canvas_height - self._offset_y) / scale)),
        )
        if right <= left or bottom <= top:
            left = max(0, min(image_width - 1, left))
            right = min(image_width, left + 1)
            top = max(0, min(image_height - 1, top))
            bottom = min(image_height, top + 1)
        source = self.document.base.crop(
            (left, top, right, bottom)
        ).convert("RGBA")
        target_width = max(1, int(round((right - left) * scale)))
        target_height = max(1, int(round((bottom - top) * scale)))
        if (target_width, target_height) != source.size:
            source = source.resize(
                (target_width, target_height), Image.LANCZOS
            )
        self._base_photo = ImageTk.PhotoImage(source, master=self.canvas)
        x = self._offset_x + left * scale
        y = self._offset_y + top * scale
        if self._image_item is None:
            self._image_item = self.canvas.create_image(
                x,
                y,
                anchor="nw",
                image=self._base_photo,
            )
        else:
            self.canvas.coords(self._image_item, x, y)
            self.canvas.itemconfigure(self._image_item, image=self._base_photo)
        self.canvas.tag_lower(self._image_item)

    def _notify_zoom(self) -> None:
        handler = self.on_zoom
        if handler is None:
            return
        try:
            handler(self._view_scale)
        except Exception:
            log.exception("截图缩放回调失败")

    # ------------------------------------------------------------- zoom/pan
    def fit_to_window(self) -> None:
        self._fit_mode = True
        self._fit_cap_one = False
        self._recompute_view()

    def zoom_to(self, scale: float) -> None:
        if self._drag_mode or self._lasso_points or self._entry is not None:
            return
        canvas_width, canvas_height = self._canvas_size()
        if canvas_width <= 2 or canvas_height <= 2:
            return
        self._fit_scale = self._compute_fit_scale(
            canvas_width, canvas_height
        )
        min_scale = 0.05
        max_scale = max(4.0, self._fit_scale * 8.0)
        target = min(max_scale, max(min_scale, float(scale)))
        anchor_x = canvas_width / 2
        anchor_y = canvas_height / 2
        image_x = (anchor_x - self._offset_x) / self._view_scale
        image_y = (anchor_y - self._offset_y) / self._view_scale
        self._view_scale = target
        self._offset_x = anchor_x - image_x * target
        self._offset_y = anchor_y - image_y * target
        self._fit_mode = False
        self._clamp_offsets(canvas_width, canvas_height)
        self._render_viewport(canvas_width, canvas_height)
        self._notify_zoom()
        self.redraw_annotations()

    def _zoom_at(self, x: float, y: float, factor: float) -> None:
        if self._drag_mode or self._lasso_points or self._entry is not None:
            return
        canvas_width, canvas_height = self._canvas_size()
        if canvas_width <= 2 or canvas_height <= 2:
            return
        self._fit_scale = self._compute_fit_scale(
            canvas_width, canvas_height
        )
        min_scale = 0.05
        max_scale = max(4.0, self._fit_scale * 8.0)
        new_scale = min(
            max_scale, max(min_scale, self._view_scale * float(factor))
        )
        if abs(new_scale - self._view_scale) < 1e-6:
            return
        image_x = (x - self._offset_x) / self._view_scale
        image_y = (y - self._offset_y) / self._view_scale
        self._view_scale = new_scale
        self._offset_x = x - image_x * new_scale
        self._offset_y = y - image_y * new_scale
        self._fit_mode = False
        self._clamp_offsets(canvas_width, canvas_height)
        self._render_viewport(canvas_width, canvas_height)
        self._notify_zoom()
        self.redraw_annotations()

    def _on_wheel_linux(self, event: tk.Event) -> str:
        factor = 1.15 if event.num == 4 else 1 / 1.15
        self._zoom_at(event.x, event.y, factor)
        return "break"

    def _on_wheel(self, event: tk.Event) -> str:
        delta = getattr(event, "delta", 0)
        if not delta:
            return "break"
        steps = delta / 120 if abs(delta) >= 120 else delta
        self._zoom_at(event.x, event.y, 1.15 ** steps)
        return "break"

    def _can_pan(self) -> bool:
        canvas_width, canvas_height = self._canvas_size()
        image_width, image_height = self.document.image_size
        return (
            image_width * self._view_scale > canvas_width
            or image_height * self._view_scale > canvas_height
        )

    def _restore_cursor(self) -> None:
        if self._pan_start is not None or self._space_pan:
            cursor = "fleur"
        elif self.tool is Tool.SELECT:
            cursor = "arrow"
        else:
            cursor = "crosshair"
        try:
            self.canvas.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _begin_pan(self, event: tk.Event) -> bool:
        if self._drag_mode or self._lasso_points or self._entry is not None:
            return False
        if self._pan_start is not None:
            return True
        if not self._can_pan():
            return False
        self._pan_start = (
            event.x,
            event.y,
            self._offset_x,
            self._offset_y,
        )
        self.canvas.configure(cursor="fleur")
        return True

    def _on_pan_press(self, event: tk.Event) -> str:
        self._begin_pan(event)
        return "break"

    def _on_pan_motion(self, event: tk.Event) -> str:
        if self._pan_start is None:
            return "break"
        start_x, start_y, start_offset_x, start_offset_y = self._pan_start
        self._offset_x = start_offset_x + (event.x - start_x)
        self._offset_y = start_offset_y + (event.y - start_y)
        canvas_width, canvas_height = self._canvas_size()
        self._clamp_offsets(canvas_width, canvas_height)
        self._render_viewport(canvas_width, canvas_height)
        self.redraw_annotations()
        return "break"

    def _on_pan_release(self, _event: tk.Event) -> str:
        self._pan_start = None
        self._restore_cursor()
        return "break"

    def _on_space_press(self, _event: tk.Event) -> str | None:
        if self._entry is not None:
            return None
        self._space_pan = True
        if self._can_pan():
            self.canvas.configure(cursor="fleur")
        return "break"

    def _on_space_release(self, _event: tk.Event) -> str:
        self._space_pan = False
        if self._pan_start is None:
            self._restore_cursor()
        return "break"

    def _on_canvas_focus_out(self, _event: tk.Event) -> None:
        self._space_pan = False
        if self._pan_start is None:
            self._restore_cursor()

    def _display_point(self, point: Point) -> tuple[float, float]:
        return (
            self._offset_x + point.x * self._view_scale,
            self._offset_y + point.y * self._view_scale,
        )

    def _image_point(self, event: tk.Event) -> Point:
        width, height = self.document.image_size
        x = (event.x - self._offset_x) / self._view_scale
        y = (event.y - self._offset_y) / self._view_scale
        return Point(
            max(0.0, min(float(width), x)),
            max(0.0, min(float(height), y)),
        )

    # ------------------------------------------------------------- tools
    def set_tool(self, tool: Tool, *, keep_selection: bool = False) -> None:
        if self._entry is not None:
            if self._entry.get().strip():
                self._commit_entry(self._entry_existing)
            else:
                self._cancel_entry()
        else:
            self._cancel_entry()
        self._cancel_lasso()
        new_tool = coerce_tool(tool)
        if new_tool is not Tool.CROP:
            self._crop_rect = None
            self._crop_original = None
            self._crop_handle = None
        previous_tool = self.tool
        self.tool = new_tool
        if new_tool is not previous_tool:
            log.info(
                "用户操作：切换标注工具为“%s”",
                _TOOL_NAMES.get(new_tool, new_tool.value),
            )
        if new_tool is not Tool.SELECT and not keep_selection:
            self.document.select(None)
        self._restore_cursor()
        if new_tool is Tool.BRUSH:
            self._report_status("画笔：按住左键绘制 · 可调整颜色和线宽")
        elif new_tool is Tool.CROP:
            width, height = self.document.image_size
            self._crop_rect = Rect(0, 0, width, height)
            self._crop_handle = None
            self._crop_original = None
            self._report_status(
                "裁剪：拖动图片边缘调整区域，Enter 应用，Esc 取消"
            )
        handler = self.on_tool_change
        if handler is not None:
            try:
                handler(new_tool)
            except Exception:
                log.exception("截图工具切换回调失败")
        self.redraw_annotations()

    def set_style(self, **changes) -> None:
        changed = {}
        for key, value in changes.items():
            if hasattr(self.style, key):
                old = getattr(self.style, key)
                setattr(self.style, key, value)
                if old != value:
                    changed[key] = value
        if changed:
            log.info("用户操作：修改标注样式 %s", changed)
        selected = self.document.selected()
        if selected is not None:
            self.document.update_style(selected.id, **changes)
            self._notify_change()
        self._update_entry_style()
        self.redraw_annotations()

    def current_style(self) -> Style:
        return self.style.copy()

    # ------------------------------------------------------------- actions
    def undo(self) -> bool:
        self._cancel_entry()
        old_size = self.document.image_size
        changed = self.document.undo()
        if changed:
            log.info(
                "用户操作：撤销，图片=%d×%d，标注=%d",
                *self.document.image_size,
                len(self.document.annotations),
            )
            if self.document.image_size != old_size:
                self._fit_mode = True
                self._fit_cap_one = False
            self._recompute_view()
            self._notify_change()
        else:
            log.info("用户操作：撤销（没有可撤销操作）")
        return changed

    def redo(self) -> bool:
        self._cancel_entry()
        old_size = self.document.image_size
        changed = self.document.redo()
        if changed:
            log.info(
                "用户操作：重做，图片=%d×%d，标注=%d",
                *self.document.image_size,
                len(self.document.annotations),
            )
            if self.document.image_size != old_size:
                self._fit_mode = True
                self._fit_cap_one = False
            self._recompute_view()
            self._notify_change()
        else:
            log.info("用户操作：重做（没有可重做操作）")
        return changed

    def reset_to_original(self) -> bool:
        self._cancel_entry()
        self._cancel_lasso()
        self._crop_rect = None
        self._crop_original = None
        self._crop_handle = None
        self.document.reset()
        log.info("用户操作：重置到未编辑状态")
        self._fit_mode = True
        self._fit_cap_one = True
        self._recompute_view()
        self._notify_change()
        self._report_status("已重置到未编辑状态")
        return True

    def set_document(self, document: AnnotationDocument) -> None:
        """Replace the edited image and reset transient/history state."""
        self._cancel_entry()
        self._cancel_lasso()
        if self._redraw_job is not None:
            try:
                self.after_cancel(self._redraw_job)
            except tk.TclError:
                pass
            self._redraw_job = None
        self._drag_mode = None
        self._drag_start = None
        self._drag_original = None
        self._drag_handle = None
        self._temp = None
        self._crop_rect = None
        self._crop_original = None
        self._crop_handle = None
        self._pan_start = None
        self.document = document
        self.set_tool(Tool.SELECT)
        self._fit_mode = True
        self._fit_cap_one = True
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._recompute_view()

    def apply_crop(self) -> bool:
        if self.tool is not Tool.CROP or self._crop_rect is None:
            return False
        image_width, image_height = self.document.image_size
        bounds = Rect(0, 0, image_width, image_height)
        crop = self._crop_rect.clamp(bounds)
        if crop.width < 8 or crop.height < 8:
            self._report_status("裁剪区域太小")
            return False
        if (
            crop.x == 0
            and crop.y == 0
            and crop.width == image_width
            and crop.height == image_height
        ):
            self._report_status("裁剪区域没有变化")
            return False
        if not self.document.crop(crop):
            log.warning("裁剪失败：区域无效 %s", crop)
            return False
        log.info(
            "用户操作：裁剪截图，区域=%s，结果=%d×%d",
            crop,
            *self.document.base.size,
        )
        self.set_tool(Tool.SELECT)
        self._fit_mode = True
        self._fit_cap_one = False
        self._recompute_view()
        self._notify_change()
        self._report_status("裁剪已应用，可撤销")
        return True

    def _report_status(self, message: str) -> None:
        handler = self.on_status
        if handler is None:
            return
        try:
            handler(message)
        except Exception:
            log.exception("截图编辑器状态回调失败")

    def rotate(self, clockwise: bool = True) -> None:
        selected = self.document.selected()
        if (
            selected is not None
            and selected.tool is Tool.STICKER
            and self.document.rotate_sticker(clockwise)
        ):
            self.redraw_annotations()
            self._notify_change()
            log.info(
                "用户操作：旋转贴纸 90°，边界=%s",
                selected.bounds,
            )
            self._report_status("贴纸已旋转 90°")
            return
        log.info("用户操作：旋转整张截图，顺时针=%s", clockwise)
        self.document.rotate(clockwise)
        self._recompute_view()
        self._notify_change()

    def flip(self, horizontal: bool = True) -> None:
        selected = self.document.selected()
        if (
            selected is not None
            and selected.tool is Tool.STICKER
            and self.document.flip_sticker(horizontal)
        ):
            self.redraw_annotations()
            self._notify_change()
            log.info(
                "用户操作：翻转贴纸，方向=%s",
                "水平" if horizontal else "垂直",
            )
            self._report_status(
                "贴纸已水平翻转" if horizontal else "贴纸已垂直翻转"
            )
            return
        log.info(
            "用户操作：翻转整张截图，方向=%s",
            "水平" if horizontal else "垂直",
        )
        self.document.flip(horizontal)
        self._recompute_view()
        self._notify_change()

    def delete_selected(self) -> None:
        selected = self.document.selected()
        if selected is None:
            return
        if self.document.remove(selected.id):
            log.info(
                "用户操作：删除标注 id=%s，工具=%s",
                selected.id,
                _TOOL_NAMES.get(selected.tool, selected.tool.value),
            )
            self.redraw_annotations()
            self._notify_change()
        else:
            log.warning("删除标注失败：id=%s 不存在", selected.id)

    def apply_selected_style(self, **changes) -> None:
        self.set_style(**changes)

    # ------------------------------------------------------------- events
    def _on_press(self, event: tk.Event) -> None:
        if self._entry is not None:
            if self._entry.get().strip():
                self._commit_entry(self._entry_existing)
            else:
                self._cancel_entry()
            return
        if self._space_pan and self._begin_pan(event):
            return
        self.canvas.focus_set()
        point = self._image_point(event)
        if self.tool is Tool.SELECT:
            self._begin_select(point, event)
            return
        if self.tool is Tool.TEXT:
            self._open_text_entry(point, event.x, event.y)
            return
        if self.tool is Tool.NUMBER:
            annotation = self.document.add_number(point, self.style)
            log.info(
                "用户操作：添加序号 %s，id=%s，位置=%s",
                annotation.number,
                annotation.id,
                point,
            )
            self.document.select(annotation.id)
            self.set_tool(Tool.SELECT, keep_selection=True)
            self._notify_change()
            return
        if self.tool is Tool.STICKER:
            self._add_sticker(point)
            return
        if self.tool is Tool.WATERMARK:
            self._add_watermark()
            return
        if self.tool is Tool.LASSO:
            self._start_lasso(point)
            return
        if self.tool is Tool.CROP:
            self._start_crop_drag(point)
            return
        if self.tool in (
            Tool.RECT,
            Tool.ELLIPSE,
            Tool.ARROW,
            Tool.BRUSH,
            Tool.MOSAIC,
        ):
            self._start_drawing(point)

    def _on_motion(self, event: tk.Event) -> None:
        if self._pan_start is not None:
            self._on_pan_motion(event)
            return
        point = self._image_point(event)
        if (
            self.tool is Tool.CROP
            and self._crop_handle is not None
            and self._crop_original is not None
        ):
            image_width, image_height = self.document.image_size
            self._crop_rect = resize_bounds(
                self._crop_original,
                self._crop_handle,
                point,
                minimum=8,
            ).clamp(Rect(0, 0, image_width, image_height))
            if self._crop_rect is not None:
                self._report_status(
                    f"裁剪：{self._crop_rect.width} × "
                    f"{self._crop_rect.height} · Enter 应用 · Esc 取消"
                )
            self.redraw_annotations()
            return
        if self._lasso_points:
            last = self._lasso_points[-1]
            if abs(point.x - last.x) + abs(point.y - last.y) < 2:
                return
            self._lasso_points.append(point)
            if self._lasso_item is not None:
                coords: list[float] = []
                for item in self._lasso_points:
                    coords.extend(self._display_point(item))
                self.canvas.coords(self._lasso_item, *coords)
            return
        if self._drag_mode == "draw" and self._temp is not None:
            self._update_temp(point)
            self.redraw_annotations()
            return
        if self._drag_mode == "move" and self._drag_original is not None:
            selected = self.document.selected()
            if selected is None:
                return
            dx = point.x - (self._drag_start.x if self._drag_start else point.x)
            dy = point.y - (self._drag_start.y if self._drag_start else point.y)
            moved = self._drag_original.clone()
            translate_annotation(moved, dx, dy)
            selected.bounds = moved.bounds
            selected.start = moved.start
            selected.end = moved.end
            selected.points = moved.points
            self.redraw_annotations()
            return
        if self._drag_mode == "resize" and self._drag_original is not None:
            selected = self.document.selected()
            if selected is None or self._drag_handle is None:
                return
            selected.bounds = resize_bounds(
                self._drag_original.bounds,
                self._drag_handle,
                point,
                minimum=8,
            )
            self.redraw_annotations()

    def _on_release(self, event: tk.Event) -> None:
        if self._pan_start is not None:
            self._on_pan_release(event)
            return
        point = self._image_point(event)
        if self.tool is Tool.CROP and self._crop_handle is not None:
            self._crop_handle = None
            self._crop_original = None
            if self._crop_rect is not None:
                self._report_status(
                    f"裁剪：{self._crop_rect.width} × "
                    f"{self._crop_rect.height} · Enter 应用 · Esc 取消"
                )
            self.redraw_annotations()
            return
        if self._lasso_points:
            self._finish_lasso(point)
            return
        if self._drag_mode == "draw":
            self._finish_drawing(point)
            return
        if self._drag_mode in ("move", "resize"):
            mode = self._drag_mode
            handle = self._drag_handle
            selected = self.document.selected()
            self._drag_mode = None
            self._drag_original = None
            self._drag_handle = None
            if selected is not None:
                log.info(
                    "用户操作：%s标注 id=%s，工具=%s，控制点=%s，边界=%s",
                    "移动" if mode == "move" else "缩放",
                    selected.id,
                    _TOOL_NAMES.get(selected.tool, selected.tool.value),
                    handle or "",
                    selected.bounds,
                )
            self.redraw_annotations()
            self._notify_change()

    def _on_double_click(self, event: tk.Event) -> None:
        if self.tool is not Tool.SELECT:
            return
        point = self._image_point(event)
        hit = self.document.hit_test(point)
        if hit is None:
            return
        if hit.tool not in (Tool.TEXT, Tool.WATERMARK):
            return
        self.document.select(hit.id)
        self._open_text_entry(
            Point(hit.bounds.x, hit.bounds.y),
            *self._display_point(Point(hit.bounds.x, hit.bounds.y)),
            existing=hit,
        )

    def _on_escape(self, _event=None) -> str | None:
        if self.handle_escape():
            return "break"
        return None

    def handle_escape(self) -> bool:
        if self._entry is not None:
            self._cancel_entry()
            return True
        if self._pan_start is not None:
            self._pan_start = None
            self._restore_cursor()
            return True
        if self._lasso_points:
            self._cancel_lasso()
            return True
        if self._drag_mode == "draw":
            self._temp = None
            self._drag_mode = None
            self.redraw_annotations()
            return True
        if self._drag_mode in ("move", "resize"):
            self._drag_mode = None
            self._drag_original = None
            self._drag_handle = None
            self.document.undo()
            self.redraw_annotations()
            self._notify_change()
            return True
        if self.tool is Tool.CROP and self._crop_rect is not None:
            self.set_tool(Tool.SELECT)
            self._report_status("已取消裁剪")
            return True
        if self.document.selected_id is not None:
            self.document.select(None)
            self.redraw_annotations()
            return True
        return False

    def dispose(self) -> None:
        self._disposed = True
        self._cancel_entry()
        self._cancel_lasso()
        for job_name in ("_redraw_job", "_initial_view_job"):
            job = getattr(self, job_name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, job_name, None)

    # ---------------------------------------------------------- selection
    def _begin_select(
        self, point: Point, event: tk.Event | None = None
    ) -> None:
        selected = self.document.selected()
        tolerance = 8 / max(0.05, self._view_scale)
        if selected is not None:
            handle = self.document.handle_at(selected, point, tolerance)
            if handle is None and selected.tool in RESIZABLE_TOOLS:
                # Allow dragging the dashed frame itself, not just the small
                # corner/edge handles.
                handle = self._selection_edge_at(
                    selected.bounds, point, tolerance
                )
            if handle is not None:
                self.document.begin_interaction()
                self._drag_mode = "resize"
                self._drag_start = point
                self._drag_original = selected.clone()
                self._drag_handle = handle
                return
        hit = self.document.hit_test(point)
        if hit is None:
            if self.document.selected_id is not None:
                log.info(
                    "用户操作：取消选中标注 id=%s",
                    self.document.selected_id,
                )
            self.document.select(None)
            self.redraw_annotations()
            if event is not None:
                self._begin_pan(event)
            return
        if self.document.selected_id != hit.id:
            log.info(
                "用户操作：选中标注 id=%s，工具=%s，边界=%s",
                hit.id,
                _TOOL_NAMES.get(hit.tool, hit.tool.value),
                hit.bounds,
            )
        self.document.select(hit.id)
        self.document.begin_interaction()
        self._drag_mode = "move"
        self._drag_start = point
        self._drag_original = hit.clone()
        self._drag_handle = None
        self.redraw_annotations()

    def _selection_edge_at(
        self, bounds: Rect, point: Point, tolerance: float
    ) -> str | None:
        near_left = abs(point.x - bounds.left) <= tolerance
        near_right = abs(point.x - bounds.right) <= tolerance
        near_top = abs(point.y - bounds.top) <= tolerance
        near_bottom = abs(point.y - bounds.bottom) <= tolerance
        inside_x = bounds.left - tolerance <= point.x <= bounds.right + tolerance
        inside_y = bounds.top - tolerance <= point.y <= bounds.bottom + tolerance
        if near_left and inside_y:
            return "w"
        if near_right and inside_y:
            return "e"
        if near_top and inside_x:
            return "n"
        if near_bottom and inside_x:
            return "s"
        return None

    # ----------------------------------------------------------- drawing
    def _start_drawing(self, point: Point) -> None:
        self._drag_mode = "draw"
        self._drag_start = point
        self._drag_original = None
        brush_points = (
            [Point(point.x, point.y)] if self.tool is Tool.BRUSH else []
        )
        self._temp = Annotation(
            tool=self.tool,
            bounds=Rect(int(point.x), int(point.y), 0, 0),
            style=self.style.copy(),
            start=Point(point.x, point.y) if self.tool is Tool.ARROW else None,
            end=Point(point.x, point.y) if self.tool is Tool.ARROW else None,
            points=brush_points,
            block_size=12,
        )
        if self.tool is Tool.BRUSH:
            self._temp.bounds = brush_bounds(
                brush_points, self.style.width
            )
        self.redraw_annotations()

    def _update_temp(self, point: Point) -> None:
        if self._temp is None or self._drag_start is None:
            return
        if self._temp.tool is Tool.BRUSH:
            points = self._temp.points
            last = points[-1] if points else None
            if (
                last is None
                or abs(point.x - last.x) + abs(point.y - last.y) >= 1.5
            ):
                points.append(Point(point.x, point.y))
                self._temp.bounds = brush_bounds(
                    points, self.style.width
                )
            return
        if self._temp.tool is Tool.ARROW:
            self._temp.start = self._drag_start
            self._temp.end = point
            self._temp.bounds = arrow_bounds(
                self._drag_start, point, self.style.width
            )
        else:
            self._temp.bounds = Rect.from_points(self._drag_start, point)

    def _finish_drawing(self, point: Point) -> None:
        temp = self._temp
        self._temp = None
        self._drag_mode = None
        if temp is None:
            return
        self._update_temp(point)
        if temp.tool is Tool.BRUSH:
            last = temp.points[-1] if temp.points else None
            if (
                last is None
                or abs(point.x - last.x) + abs(point.y - last.y) >= 0.5
            ):
                temp.points.append(Point(point.x, point.y))
            if temp.points:
                annotation = self.document.add_brush(
                    temp.points, self.style
                )
                log.info(
                    "用户操作：添加画笔标注 id=%s，点数=%d，边界=%s",
                    annotation.id,
                    len(temp.points),
                    annotation.bounds,
                )
            self.document.select(None)
            self.redraw_annotations()
            self._notify_change()
            return
        if temp.tool is Tool.ARROW:
            start = temp.start
            end = temp.end
            if start is None or end is None:
                return
            if abs(end.x - start.x) + abs(end.y - start.y) < 4:
                self.redraw_annotations()
                return
            annotation = self.document.add_arrow(
                start, end, self.style
            )
            log.info(
                "用户操作：添加箭头标注 id=%s，起点=%s，终点=%s",
                annotation.id,
                start,
                end,
            )
        else:
            rect = temp.bounds.normalized()
            if rect.width < 4 or rect.height < 4:
                self.redraw_annotations()
                return
            annotation = self.document.add_shape(
                temp.tool, rect, self.style
            )
            log.info(
                "用户操作：添加%s标注 id=%s，边界=%s",
                _TOOL_NAMES.get(temp.tool, temp.tool.value),
                annotation.id,
                rect,
            )
        self.document.select(None)
        self.redraw_annotations()
        self._notify_change()

    # --------------------------------------------------------------- crop
    def _start_crop_drag(self, point: Point) -> None:
        if self._crop_rect is None:
            width, height = self.document.image_size
            self._crop_rect = Rect(0, 0, width, height)
        handle = self._crop_handle_at(point)
        if handle is None:
            return
        self._crop_handle = handle
        self._crop_original = Rect(
            self._crop_rect.x,
            self._crop_rect.y,
            self._crop_rect.width,
            self._crop_rect.height,
        )

    def _crop_handle_at(self, point: Point) -> str | None:
        rect = self._crop_rect
        if rect is None:
            return None
        tolerance = max(6.0, 12.0 / max(0.05, self._view_scale))
        handles = handle_points(rect)
        for name in ("nw", "ne", "se", "sw"):
            handle = handles[name]
            if (
                abs(point.x - handle.x) <= tolerance
                and abs(point.y - handle.y) <= tolerance
            ):
                return name
        if (
            abs(point.y - rect.top) <= tolerance
            and rect.left <= point.x <= rect.right
        ):
            return "n"
        if (
            abs(point.y - rect.bottom) <= tolerance
            and rect.left <= point.x <= rect.right
        ):
            return "s"
        if (
            abs(point.x - rect.left) <= tolerance
            and rect.top <= point.y <= rect.bottom
        ):
            return "w"
        if (
            abs(point.x - rect.right) <= tolerance
            and rect.top <= point.y <= rect.bottom
        ):
            return "e"
        return None

    def _draw_crop_overlay(self) -> None:
        crop = self._crop_rect
        if crop is None:
            return
        image_width, image_height = self.document.image_size
        x0, y0 = self._display_point(Point(0, 0))
        x1, y1 = self._display_point(Point(image_width, image_height))
        left, top, right, bottom = self._display_box(crop)
        boxes = (
            (x0, y0, x1, top),
            (x0, bottom, x1, y1),
            (x0, top, left, bottom),
            (right, top, x1, bottom),
        )
        for box_left, box_top, box_right, box_bottom in boxes:
            if box_right <= box_left or box_bottom <= box_top:
                continue
            self.canvas.create_rectangle(
                box_left,
                box_top,
                box_right,
                box_bottom,
                fill="#000000",
                outline="",
                stipple="gray50",
                tags="crop",
            )
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=ACCENT,
            width=2,
            tags="crop",
        )
        for handle in handle_points(crop).values():
            x, y = self._display_point(handle)
            self.canvas.create_rectangle(
                x - 3,
                y - 3,
                x + 3,
                y + 3,
                fill="#ffffff",
                outline=ACCENT,
                width=1,
                tags="crop",
            )

    def _release_stale_grab(self) -> None:
        try:
            current = self.grab_current()
        except (tk.TclError, KeyError):
            return
        if current is None:
            return
        try:
            if not current.winfo_exists() or not current.winfo_viewable():
                current.grab_release()
        except tk.TclError:
            pass

    def add_sticker_at_center(self) -> None:
        width, height = self.document.image_size
        self._add_sticker(Point(width / 2, height / 2))

    def _add_sticker(self, point: Point) -> None:
        self._release_stale_grab()
        log.info("用户操作：打开贴纸文件选择框，插入中心=%s", point)
        self._report_status("请选择贴纸图片…")
        try:
            path = open_native_file_dialog(
                self,
                filedialog.askopenfilename,
                title="选择贴纸图片",
                filetypes=(
                    ("图片", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
                    ("所有文件", "*.*"),
                ),
            )
        except Exception as exc:
            log.exception("打开贴纸文件选择框失败")
            self.set_tool(Tool.SELECT)
            message = f"打开文件选择框失败：{exc}"
            self._report_status(message)
            show_toast = getattr(self.winfo_toplevel(), "show_toast", None)
            if callable(show_toast):
                try:
                    show_toast(message, error=True)
                except Exception:
                    pass
            return
        if not path:
            log.info("用户操作：取消选择贴纸图片")
            self.set_tool(Tool.SELECT)
            self._report_status("已取消添加贴纸")
            try:
                self.canvas.focus_set()
            except tk.TclError:
                pass
            return
        log.info("用户操作：选择贴纸图片 %s", path)
        try:
            with Image.open(path) as image:
                image.load()
                sticker = image.copy()
        except Exception as exc:
            log.warning("贴纸加载失败：%s", path, exc_info=True)
            message = f"贴纸加载失败：{exc}"
            self.set_tool(Tool.SELECT)
            self._report_status(message)
            show_toast = getattr(self.winfo_toplevel(), "show_toast", None)
            if callable(show_toast):
                try:
                    show_toast(message, error=True)
                except Exception:
                    pass
            return
        try:
            self.canvas.focus_set()
        except tk.TclError:
            pass
        annotation = self.document.add_sticker(sticker, point, self.style)
        log.info(
            "用户操作：插入贴纸 %s，原图=%d×%d，插入=%d×%d，边界=%s",
            path,
            sticker.width,
            sticker.height,
            annotation.bounds.width,
            annotation.bounds.height,
            annotation.bounds,
        )
        self.document.select(annotation.id)
        self.set_tool(Tool.SELECT, keep_selection=True)
        self._notify_change()
        self._report_status(
            "贴纸已添加：拖动虚线框或控制点缩放，工具栏“左转/右转”旋转。"
        )

    def _add_watermark(self) -> None:
        self._release_stale_grab()
        dialog = _TextPromptDialog(
            self.winfo_toplevel(),
            "添加水印",
            "输入水印文字：",
            self.fonts,
        )
        text = dialog.result
        if not text:
            log.info("用户操作：取消添加水印")
            return
        style = self.style.copy()
        style.opacity = 128
        style.font_size = max(20, self.style.font_size * 2)
        annotation = self.document.add_watermark(text, style)
        log.info(
            "用户操作：添加水印 %r，边界=%s",
            text[:80],
            annotation.bounds,
        )
        self.document.select(annotation.id)
        self.set_tool(Tool.SELECT, keep_selection=True)
        self._notify_change()

    # ------------------------------------------------------------- lasso
    def _start_lasso(self, point: Point) -> None:
        self._cancel_lasso()
        self._lasso_points = [point]
        x, y = self._display_point(point)
        self._lasso_item = self.canvas.create_line(
            x,
            y,
            x,
            y,
            fill=ACCENT,
            width=2,
            smooth=True,
            splinesteps=12,
            tags="lasso",
        )

    def _finish_lasso(self, point: Point) -> None:
        points = self._lasso_points
        self._lasso_points = []
        if self._lasso_item is not None:
            self.canvas.delete(self._lasso_item)
            self._lasso_item = None
        if not points or (
            abs(point.x - points[-1].x) + abs(point.y - points[-1].y) >= 2
        ):
            points.append(point)
        if len(points) < 3:
            return
        if self.document.annotations:
            confirmed = run_modal_dialog(
                self,
                lambda **kwargs: messagebox.askyesno(
                    "套索裁剪",
                    "套索裁剪会丢弃已有标注，是否继续？",
                    **kwargs,
                ),
            )
            if not confirmed:
                return
        if not self.document.crop_lasso(points, drop_annotations=True):
            log.warning("套索裁剪失败：区域无效或超出图片")
            return
        log.info(
            "用户操作：套索裁剪，路径点=%d，结果=%d×%d",
            len(points),
            *self.document.base.size,
        )
        self.set_tool(Tool.SELECT, keep_selection=False)
        self._recompute_view()
        self._notify_change()

    def _cancel_lasso(self) -> None:
        self._lasso_points = []
        if self._lasso_item is not None:
            try:
                self.canvas.delete(self._lasso_item)
            except tk.TclError:
                pass
            self._lasso_item = None

    # ------------------------------------------------------------- text
    def _sample_background(self, point: Point) -> str:
        image = self.document.base
        x = int(round(point.x))
        y = int(round(point.y))
        left = max(0, x - 8)
        top = max(0, y - 8)
        right = min(image.width, x + 8)
        bottom = min(image.height, y + 8)
        if right <= left or bottom <= top:
            return CANVAS_BG
        try:
            pixel = image.crop((left, top, right, bottom)).convert(
                "RGB"
            ).resize((1, 1), Image.LANCZOS).getpixel((0, 0))
            if not isinstance(pixel, tuple) or len(pixel) < 3:
                return CANVAS_BG
            red, green, blue = pixel[:3]
            return f"#{red:02x}{green:02x}{blue:02x}"
        except Exception:
            log.debug("采样文字输入框背景失败，使用画布背景色", exc_info=True)
            return CANVAS_BG

    def _open_text_entry(
        self,
        point: Point,
        display_x: float,
        display_y: float,
        *,
        existing: Annotation | None = None,
    ) -> None:
        self._cancel_entry()
        self._entry_point = point
        self._entry_existing = existing
        entry = tk.Entry(
            self.canvas,
            bg=self._sample_background(point),
            fg=self.style.color,
            insertbackground=self.style.color,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            insertwidth=1,
            highlightthickness=0,
            font=(
                self.fonts.ui,
                -max(8, int(self.style.font_size * self._view_scale)),
            ),
            width=max(6, len(existing.text) + 2 if existing is not None else 6),
        )
        if existing is not None:
            entry.insert(0, existing.text)
            entry.selection_range(0, tk.END)
        entry.place(x=display_x, y=display_y, anchor="nw")
        entry.focus_force()
        entry.bind(
            "<Return>",
            lambda _event, item=existing: self._commit_entry_event(item),
        )
        entry.bind("<Escape>", self._cancel_entry_event)
        entry.bind("<FocusOut>", self._on_entry_focus_out)
        entry.bind("<KeyRelease>", lambda _event: self._resize_entry())
        self._entry = entry

    def _on_entry_focus_out(self, _event=None) -> None:
        if self._entry is None:
            return
        if self._entry.get().strip():
            self._commit_entry(self._entry_existing)
        else:
            self._cancel_entry()

    def _resize_entry(self) -> None:
        entry = self._entry
        if entry is None:
            return
        try:
            width = len(entry.get()) + 2
        except tk.TclError:
            return
        entry.configure(width=max(6, min(80, width)))

    def _update_entry_style(self) -> None:
        entry = self._entry
        if entry is None:
            return
        try:
            entry.configure(
                font=(
                    self.fonts.ui,
                    -max(8, int(self.style.font_size * self._view_scale)),
                ),
                fg=self.style.color,
                insertbackground=self.style.color,
            )
        except tk.TclError:
            pass

    def _commit_entry_event(self, existing: Annotation | None) -> str:
        self._commit_entry(existing)
        return "break"

    def _cancel_entry_event(self, _event=None) -> str:
        self._cancel_entry()
        return "break"

    def commit_pending_entry(self) -> None:
        if self._entry is not None:
            self._commit_entry(self._entry_existing)

    def _commit_entry(self, existing: Annotation | None = None) -> None:
        entry = self._entry
        point = self._entry_point
        if existing is None:
            existing = self._entry_existing
        self._entry = None
        self._entry_point = None
        self._entry_existing = None
        if entry is None or point is None:
            return
        text = entry.get().strip()
        try:
            entry.destroy()
        except tk.TclError:
            pass
        if not text:
            return
        if existing is not None:
            self.document.update_text(existing.id, text)
            self.document.select(existing.id)
            log.info(
                "用户操作：修改文字标注 id=%s，内容=%r",
                existing.id,
                text[:80],
            )
        else:
            annotation = self.document.add_text(text, point, self.style)
            self.document.select(annotation.id)
            log.info(
                "用户操作：添加文字标注 id=%s，内容=%r，位置=%s",
                annotation.id,
                text[:80],
                point,
            )
        self.set_tool(Tool.SELECT, keep_selection=True)
        self._notify_change()

    def _cancel_entry(self) -> None:
        entry = self._entry
        self._entry = None
        self._entry_point = None
        self._entry_existing = None
        if entry is not None:
            try:
                entry.destroy()
            except tk.TclError:
                pass

    # ----------------------------------------------------------- drawing
    def redraw_annotations(self) -> None:
        self.canvas.delete("annotation")
        self.canvas.delete("selection")
        self.canvas.delete("crop")
        self._sticker_photos.clear()
        self._text_photos.clear()
        for annotation in self.document.annotations:
            self._draw_annotation(annotation, preview=False)
        if self._temp is not None:
            self._draw_annotation(self._temp, preview=True)
        self._draw_selection()
        if self.tool is Tool.CROP:
            self._draw_crop_overlay()

    def _draw_annotation(self, annotation: Annotation, *, preview: bool) -> None:
        style = annotation.style
        color = style.color
        width = max(1, int(round(style.width * self._view_scale)))
        if annotation.tool in (Tool.RECT, Tool.ELLIPSE):
            box = self._display_box(annotation.bounds)
            if annotation.tool is Tool.ELLIPSE:
                self.canvas.create_oval(
                    *box,
                    outline=color,
                    width=width,
                    tags="annotation",
                )
            else:
                self.canvas.create_rectangle(
                    *box,
                    outline=color,
                    width=width,
                    tags="annotation",
                )
        elif annotation.tool is Tool.ARROW:
            self._draw_arrow(annotation, width, color)
        elif annotation.tool is Tool.BRUSH:
            points = annotation.points
            if not points:
                return
            coords: list[float] = []
            for point in points:
                coords.extend(self._display_point(point))
            if len(coords) == 2:
                x, y = coords
                radius = max(1.0, width / 2)
                self.canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill=color,
                    outline=color,
                    tags="annotation",
                )
            else:
                self.canvas.create_line(
                    *coords,
                    fill=color,
                    width=width,
                    capstyle="round",
                    joinstyle="round",
                    tags="annotation",
                )
        elif annotation.tool in (Tool.TEXT, Tool.WATERMARK):
            try:
                preview = render_annotation_preview(
                    annotation, self.document.fonts
                )
                target_width = max(
                    1, int(round(preview.width * self._view_scale))
                )
                target_height = max(
                    1, int(round(preview.height * self._view_scale))
                )
                if (target_width, target_height) != preview.size:
                    preview = preview.resize(
                        (target_width, target_height), Image.LANCZOS
                    )
                photo = ImageTk.PhotoImage(preview, master=self.canvas)
            except Exception:
                log.debug("渲染文字预览失败", exc_info=True)
                return
            self._text_photos.append(photo)
            x, y = self._display_point(
                Point(annotation.bounds.x, annotation.bounds.y)
            )
            self.canvas.create_image(
                x,
                y,
                anchor="nw",
                image=photo,
                tags="annotation",
            )
        elif annotation.tool is Tool.NUMBER:
            box = self._display_box(annotation.bounds)
            self.canvas.create_oval(
                *box,
                fill=color,
                outline=color,
                tags="annotation",
            )
            x = (box[0] + box[2]) / 2
            y = (box[1] + box[3]) / 2
            self.canvas.create_text(
                x,
                y,
                text=str(annotation.number),
                fill="#ffffff",
                font=(
                    self.fonts.ui,
                    -max(8, int(style.font_size * 0.75 * self._view_scale)),
                ),
                tags="annotation",
            )
        elif annotation.tool is Tool.MOSAIC:
            box = self._display_box(annotation.bounds)
            self.canvas.create_rectangle(
                *box,
                fill="#6b7280",
                stipple="gray50",
                outline=color,
                width=width,
                tags="annotation",
            )
        elif annotation.tool is Tool.STICKER and annotation.image is not None:
            box = self._display_box(annotation.bounds)
            width_px = max(1, int(round(box[2] - box[0])))
            height_px = max(1, int(round(box[3] - box[1])))
            try:
                # Fill the annotation bounds exactly so the selection frame
                # always hugs the sticker after edge/corner resizing.
                preview_image = annotation.image.convert("RGBA").resize(
                    (width_px, height_px), Image.LANCZOS
                )
                photo = ImageTk.PhotoImage(preview_image, master=self.canvas)
            except Exception:
                log.warning(
                    "渲染贴纸预览失败：标注 id=%s，图片尺寸=%s",
                    annotation.id,
                    getattr(annotation.image, "size", None),
                    exc_info=True,
                )
                return
            self._sticker_photos.append(photo)
            self.canvas.create_image(
                box[0],
                box[1],
                anchor="nw",
                image=photo,
                tags="annotation",
            )

    def _draw_arrow(self, annotation: Annotation, width: int, color: str) -> None:
        start = annotation.start
        end = annotation.end
        if start is None or end is None:
            return
        sx, sy = self._display_point(start)
        ex, ey = self._display_point(end)
        self.canvas.create_line(
            sx,
            sy,
            ex,
            ey,
            fill=color,
            width=width,
            arrow="last",
            arrowshape=(max(8, width * 3), max(10, width * 4), max(3, width)),
            tags="annotation",
            capstyle="round",
        )

    def _draw_selection(self) -> None:
        selected = self.document.selected()
        if selected is None:
            return
        box = self._display_box(selected.bounds)
        self.canvas.create_rectangle(
            *box,
            outline=ACCENT,
            width=1,
            dash=(4, 3),
            tags="selection",
        )
        if selected.tool in RESIZABLE_TOOLS:
            for _name, handle in handle_points(selected.bounds).items():
                x, y = self._display_point(handle)
                self.canvas.create_rectangle(
                    x - 3,
                    y - 3,
                    x + 3,
                    y + 3,
                    fill="#ffffff",
                    outline=ACCENT,
                    width=1,
                    tags="selection",
                )

    def _display_box(self, rect: Rect) -> tuple[float, float, float, float]:
        x1, y1 = self._display_point(Point(rect.left, rect.top))
        x2, y2 = self._display_point(Point(rect.right, rect.bottom))
        return x1, y1, x2, y2

    # ------------------------------------------------------------- notify
    def _notify_change(self) -> None:
        handler = self.on_change
        if handler is not None:
            try:
                handler()
            except Exception:
                log.exception("截图编辑器变更回调失败")

    def render(self) -> Image.Image:
        return self.document.render()
