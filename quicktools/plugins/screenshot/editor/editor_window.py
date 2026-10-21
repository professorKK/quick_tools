"""Screenshot editor window with annotation canvas and toolbar."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from PIL import Image

from quicktools.ui_theme import (
    ACCENT,
    ACCENT_HOVER,
    BG,
    BORDER,
    BUTTON,
    DANGER,
    FlatButton,
    MUTED,
    ON_ACCENT,
    PANEL,
    SUCCESS,
    TEXT,
    center_on_screen,
    pick_fonts,
)
from quicktools.window_frame import WindowFrame

from ..settings import ScreenshotSettings
from ..ui.icons import IconSet
from .annotations import Style, Tool
from .canvas import AnnotationCanvas
from .document import AnnotationDocument
from .fonts import FontResolver
from .toolbar import AnnotationToolbar

log = logging.getLogger(__name__)

CopyHandler = Callable[[Image.Image], None]
SaveHandler = Callable[[Image.Image, Path | None], Path]
AutoSaveHandler = Callable[[Image.Image], None]
CloseHandler = Callable[[bool], None]
ReturnHandler = Callable[[bool], None]

AUTOSAVE_DELAY_MS = 400


class CaptureEditor(tk.Toplevel):
    def __init__(
        self,
        root: tk.Misc,
        image: Image.Image,
        settings: ScreenshotSettings,
        *,
        on_copy: CopyHandler,
        on_save: SaveHandler,
        on_close: CloseHandler,
        on_return: ReturnHandler | None = None,
        on_autosave: AutoSaveHandler | None = None,
        initial_tool: Tool | None = None,
    ) -> None:
        super().__init__(root)
        self.image = image.copy()
        self.settings = settings
        self.on_copy = on_copy
        self.on_save = on_save
        self.on_autosave = on_autosave
        self.on_close = on_close
        self.on_return = on_return
        self.fonts = pick_fonts(self)
        self.icons = IconSet(self)
        self.font_resolver = FontResolver()
        self.document = AnnotationDocument(self.image, self.font_resolver)
        self._clean_signature = self.document.content_signature()
        self.edit_style = Style(
            color=settings.default_color,
            width=settings.default_width,
            font_size=settings.default_font_size,
        )
        self._done = False
        self._closed = False
        self._suppress_close = False
        self._copy_button: FlatButton | None = None
        self._close_return_button: FlatButton | None = None
        self._toast_label: tk.Label | None = None
        self._toast_icon = None
        self._toast_job: str | None = None
        self._copy_flash_job: str | None = None
        self._autosave_job: str | None = None

        self.title("截图 · 快捷工具")
        self.configure(bg=BG)
        self.minsize(960, 620)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._bind_shortcuts()
        self.frame = WindowFrame(
            self,
            title="编辑截图",
            icon="S",
            fonts=self.fonts,
            on_close=self.close,
        )
        self.pin_button = self.frame.pin_button
        self._build()
        if initial_tool is not None:
            self._canvas.set_tool(initial_tool)
            if initial_tool is Tool.LASSO:
                self._status_var.set("用套索圈出要保留的区域；Esc 取消。")

        width = min(1320, max(900, int(self.winfo_screenwidth() * 0.74)))
        height = min(960, max(620, int(self.winfo_screenheight() * 0.82)))
        center_on_screen(self, width, height)
        self._focus_job = self.after(60, self._focus)
        self._focus_canvas_job = self.after(100, self._focus_canvas)

    # ------------------------------------------------------------------ UI
    def _bind_shortcuts(self) -> None:
        self.bind("<Control-z>", lambda _event: self._undo())
        self.bind("<Control-y>", lambda _event: self._redo())
        self.bind("<Control-Shift-Z>", lambda _event: self._redo())
        self.bind("<Control-Z>", lambda _event: self._redo())
        self.bind("<Control-c>", lambda _event: self._copy_shortcut())
        self.bind("<Control-s>", lambda _event: self._save_shortcut())
        self.bind("<Control-0>", lambda _event: self._fit_view())
        self.bind("<Control-1>", lambda _event: self._zoom_100())
        self.bind("<Delete>", lambda _event: self._delete_shortcut())
        self.bind("<Return>", lambda _event: self._apply_crop_shortcut())
        self.bind("<Escape>", lambda _event: self._escape())

    def _typing(self) -> bool:
        widget = self.focus_get()
        return isinstance(
            widget,
            (
                tk.Entry,
                tk.Text,
                tk.Spinbox,
                ttk.Entry,
                ttk.Spinbox,
                ttk.Combobox,
            ),
        )

    def _undo(self) -> None:
        if not self._typing():
            self._canvas.undo()

    def _redo(self) -> None:
        if not self._typing():
            self._canvas.redo()

    def _delete_shortcut(self) -> None:
        if not self._typing():
            self._canvas.delete_selected()

    def _fit_view(self) -> None:
        if not self._typing():
            self._canvas.fit_to_window()

    def _zoom_100(self) -> None:
        if not self._typing():
            self._canvas.zoom_to(1.0)

    def _apply_crop_shortcut(self) -> str | None:
        if self._typing():
            return None
        if self._canvas.apply_crop():
            return "break"
        return None

    def _on_canvas_status(self, message: str) -> None:
        status_var = getattr(self, "_status_var", None)
        if status_var is not None:
            status_var.set(message)

    def _copy_shortcut(self) -> None:
        if not self._typing():
            self.copy()

    def _save_shortcut(self) -> None:
        if not self._typing():
            self.save()

    def _build(self) -> None:
        self._zoom_var = tk.StringVar(value="缩放 100%")
        shell = tk.Frame(self, bg=BG, padx=16, pady=12)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(
            header,
            text="标注编辑",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(17, "bold"),
        ).pack(side="left")
        self._size_var = tk.StringVar(
            value=f"{self.document.base.width} × {self.document.base.height}"
        )
        tk.Label(
            header,
            textvariable=self._size_var,
            bg=PANEL,
            fg=MUTED,
            padx=8,
            pady=3,
            font=self.fonts.m(9),
        ).pack(side="left", padx=(10, 0))
        zoom_frame = tk.Frame(header, bg=BG)
        zoom_frame.pack(side="right")
        tk.Label(
            zoom_frame,
            textvariable=self._zoom_var,
            bg=BG,
            fg=MUTED,
            font=self.fonts.m(9),
        ).pack(side="left", padx=(0, 10))
        FlatButton(
            zoom_frame,
            "适应",
            lambda: self._canvas.fit_to_window(),
            fonts=self.fonts,
            font_size=9,
            padx=9,
            pady=4,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("fit", 14, TEXT),
        ).pack(side="left")
        FlatButton(
            zoom_frame,
            "1:1",
            lambda: self._canvas.zoom_to(1.0),
            fonts=self.fonts,
            font_size=9,
            padx=9,
            pady=4,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("one-to-one", 14, TEXT),
        ).pack(side="left", padx=(4, 0))
        tk.Frame(shell, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

        canvas_border = tk.Frame(shell, bg=BORDER)
        canvas_border.pack(fill="both", expand=True, pady=(8, 0))
        self._canvas = AnnotationCanvas(
            canvas_border,
            self.document,
            self.fonts,
            style=self.edit_style,
            on_status=self._on_canvas_status,
            on_change=self._on_document_changed,
            on_zoom=self._on_zoom,
        )
        self._canvas.pack(fill="both", expand=True, padx=1, pady=1)
        self.toolbar = AnnotationToolbar(
            shell, self._canvas, self.fonts, icons=self.icons
        )
        self.toolbar.pack(fill="x", pady=(8, 6), before=canvas_border)

        if not self.font_resolver.has_cjk_font:
            tk.Label(
                shell,
                text="未找到中文字体，导出文字时可能显示为方块。",
                bg=BG,
                fg="#c5221f",
                anchor="w",
                font=self.fonts.u(9),
            ).pack(fill="x", pady=(0, 4))

        footer = tk.Frame(shell, bg=BG)
        footer.pack(fill="x", pady=(10, 0))
        self._status_var = tk.StringVar(
            value="选择工具后圈选、标注；修改会自动保存。"
        )
        tk.Label(
            footer,
            textvariable=self._status_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=620,
            font=self.fonts.u(9),
        ).pack(side="left", fill="x", expand=True)
        FlatButton(
            footer,
            "关闭",
            self.close,
            fonts=self.fonts,
            font_size=10,
            padx=14,
            pady=8,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("close", 15, TEXT),
        ).pack(side="right")
        self._close_return_button = FlatButton(
            footer,
            "关闭并返回",
            self.close_and_return,
            fonts=self.fonts,
            font_size=10,
            padx=14,
            pady=8,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("home", 15, TEXT),
        )
        self._close_return_button.pack(side="right", padx=(0, 8))
        FlatButton(
            footer,
            "另存为",
            self.save_as,
            fonts=self.fonts,
            font_size=10,
            padx=14,
            pady=8,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("save-as", 15, TEXT),
        ).pack(side="right", padx=(0, 8))
        self._copy_button = FlatButton(
            footer,
            "复制",
            self.copy,
            fonts=self.fonts,
            accent=True,
            active_bg=ACCENT,
            active_hover_bg=ACCENT_HOVER,
            font_size=10,
            padx=14,
            pady=8,
            image=self.icons.get("copy", 15, ON_ACCENT),
        )
        self._copy_button.pack(side="right", padx=(0, 8))

    def _focus(self) -> None:
        if self._closed:
            return
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _focus_canvas(self) -> None:
        if self._closed:
            return
        try:
            self._canvas.canvas.focus_set()
        except tk.TclError:
            pass

    def _escape(self) -> str:
        if self._typing():
            return "break"
        if self._canvas.handle_escape():
            return "break"
        self.close()
        return "break"

    def _on_document_changed(self) -> None:
        self._size_var.set(
            f"{self.document.base.width} × {self.document.base.height}"
        )
        self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if self.on_autosave is None or self._closed:
            return
        self._cancel_autosave()
        self._autosave_job = self.after(AUTOSAVE_DELAY_MS, self._autosave)

    def _cancel_autosave(self) -> None:
        job = self._autosave_job
        self._autosave_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass

    def _autosave(self) -> None:
        self._autosave_job = None
        if self._closed or self.on_autosave is None:
            return
        try:
            rendered = self._canvas.render()
            self.on_autosave(rendered)
        except Exception as exc:
            log.exception("自动保存截图失败")
            self._status_var.set(f"自动保存失败：{exc}")
            self.show_toast(f"自动保存失败：{exc}", error=True)
            return
        self._done = True
        self.mark_exported()
        self._status_var.set("修改已自动保存。")

    def _flush_autosave(self) -> None:
        if self._autosave_job is None:
            return
        self._cancel_autosave()
        self._autosave()

    def _on_zoom(self, scale: float) -> None:
        self._zoom_var.set(f"缩放 {scale * 100:.0f}%")

    # -------------------------------------------------------------- actions
    def show_toast(self, message: str, error: bool = False) -> None:
        if self._toast_job is not None:
            try:
                self.after_cancel(self._toast_job)
            except tk.TclError:
                pass
            self._toast_job = None
        if self._toast_label is not None:
            try:
                self._toast_label.destroy()
            except tk.TclError:
                pass
        self._toast_icon = self.icons.get(
            "warning" if error else "check",
            15,
            "#ffffff" if error else SUCCESS,
        )
        self._toast_label = tk.Label(
            self,
            text=message,
            bg=DANGER if error else "#ffffff",
            fg="#ffffff" if error else TEXT,
            padx=16,
            pady=9,
            font=self.fonts.u(10, "bold"),
            image=self._toast_icon,
            compound="left",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self._toast_label.place(
            relx=1.0, rely=1.0, x=-24, y=-80, anchor="se"
        )
        self._toast_label.lift()
        self._toast_job = self.after(1800, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_job = None
        label = self._toast_label
        self._toast_label = None
        if label is not None:
            try:
                label.destroy()
            except tk.TclError:
                pass

    def _flash_copy_button(self) -> None:
        button = self._copy_button
        if button is None:
            return
        try:
            button.configure(text="已复制 ✓")
        except tk.TclError:
            return
        self._copy_flash_job = self.after(1600, self._restore_copy_button)

    def _restore_copy_button(self) -> None:
        self._copy_flash_job = None
        button = self._copy_button
        if button is None:
            return
        try:
            button.configure(text="复制")
        except tk.TclError:
            pass

    def copy(self) -> None:
        try:
            self._canvas.commit_pending_entry()
            rendered = self._canvas.render()
            self.on_copy(rendered)
        except Exception as exc:
            log.exception("复制截图失败")
            self._status_var.set(f"复制失败：{exc}")
            self.show_toast(f"复制失败：{exc}", error=True)
            return
        self._done = True
        self._cancel_autosave()
        self.mark_exported()
        self._status_var.set("已复制到剪贴板。")
        self.show_toast("已复制到剪贴板")
        self._flash_copy_button()

    def save(self) -> None:
        try:
            self._canvas.commit_pending_entry()
            rendered = self._canvas.render()
            path = self.on_save(rendered, None)
        except Exception as exc:
            log.exception("保存截图失败")
            self._status_var.set(f"保存失败：{exc}")
            return
        self._done = True
        self._cancel_autosave()
        self.mark_exported()
        self._status_var.set(f"已保存：{path}")
        self.show_toast("保存成功")

    def _release_stale_grab(self) -> None:
        try:
            current = self.grab_current()
        except tk.TclError:
            return
        if current is None:
            return
        try:
            if not current.winfo_exists() or not current.winfo_viewable():
                current.grab_release()
        except tk.TclError:
            pass

    def save_as(self) -> None:
        self._canvas.commit_pending_entry()
        self._release_stale_grab()
        extension = self._extension()
        path = filedialog.asksaveasfilename(
            parent=self,
            title="截图另存为",
            defaultextension=f".{extension}",
            filetypes=(
                ("PNG 图片", "*.png"),
                ("JPEG 图片", "*.jpg *.jpeg"),
                ("WebP 图片", "*.webp"),
                ("所有文件", "*.*"),
            ),
            initialfile=f"screenshot.{extension}",
        )
        if not path:
            return
        try:
            self._canvas.commit_pending_entry()
            rendered = self._canvas.render()
            saved = self.on_save(rendered, Path(path))
        except Exception as exc:
            log.exception("另存截图失败")
            self._status_var.set(f"保存失败：{exc}")
            return
        self._done = True
        self._cancel_autosave()
        self.mark_exported()
        self._status_var.set(f"已保存：{saved}")
        self.show_toast("已保存")

    def _extension(self) -> str:
        image_format = self.settings.image_format
        if image_format == "jpeg":
            return "jpg"
        if image_format == "webp":
            return "webp"
        return "png"

    def mark_exported(self) -> None:
        """Record the current content as the last exported state."""
        self._clean_signature = self.document.content_signature()

    def close(self) -> None:
        self._request_close(return_to_assistant=False)

    def close_and_return(self) -> None:
        self._request_close(return_to_assistant=True)

    def _request_close(self, *, return_to_assistant: bool) -> None:
        if self._closed:
            return
        self._canvas.commit_pending_entry()
        # 自动保存成功后 mark_exported() 会把基线前移，正常关闭就不会命中。
        modified = self.document.content_signature() != self._clean_signature
        if modified and self.on_autosave is not None:
            # 还没到防抖时间的改动先落库，失败时靠下面的确认提示兜底。
            self._flush_autosave()
            modified = self.document.content_signature() != self._clean_signature
        if modified:
            self._release_stale_grab()
            reason = "这张截图还有未保存的修改"
            if return_to_assistant:
                title = "关闭截图并返回"
                message = f"{reason}，确定关闭并返回截图助手吗？"
            else:
                title = "关闭截图"
                message = f"{reason}，确定关闭吗？"
            confirmed = messagebox.askyesno(
                title,
                message,
                parent=self,
            )
            if not confirmed:
                return
        self._finish(return_to_assistant=return_to_assistant)

    def _finish(self, return_to_assistant: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        for job_name in (
            "_focus_job",
            "_focus_canvas_job",
            "_toast_job",
            "_copy_flash_job",
            "_autosave_job",
        ):
            job = getattr(self, job_name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, job_name, None)
        if self._toast_label is not None:
            try:
                self._toast_label.destroy()
            except tk.TclError:
                pass
            self._toast_label = None
        try:
            self._canvas.dispose()
        except Exception:
            pass
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
        if not self._suppress_close:
            if return_to_assistant and self.on_return is not None:
                self.on_return(self._done)
            else:
                self.on_close(self._done)

    def dispose(self) -> None:
        """Destroy without invoking the close callback (service shutdown)."""
        self._suppress_close = True
        self._finish()
