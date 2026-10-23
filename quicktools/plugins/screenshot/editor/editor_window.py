"""Screenshot editor window with annotation canvas and toolbar."""

from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import dataclass
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
    DISABLED_TEXT,
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

from quicktools.modal_dialogs import (
    open_native_file_dialog,
    run_modal_dialog,
)

from ..settings import ScreenshotSettings
from ..ui.icons import IconSet
from .annotations import Style, Tool
from .canvas import AnnotationCanvas
from .document import AnnotationDocument
from .fonts import FontResolver
from .toolbar import AnnotationToolbar

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavigationTarget:
    image: Image.Image
    entry_id: str
    has_newer: bool
    has_older: bool


CopyHandler = Callable[[Image.Image], None]
SaveHandler = Callable[[Image.Image, Path | None], Path]
AutoSaveHandler = Callable[[Image.Image], bool | None]
CloseHandler = Callable[[bool], None]
ReturnHandler = Callable[[bool], None]
NavigateHandler = Callable[[int], NavigationTarget | None]

AUTOSAVE_DELAY_MS = 400
NAV_EDGE_ZONE_PX = 96
NAV_INSET_PX = 14
NAV_ARROW_SIZE = 22
NAV_IDLE_BG = "#f1efea"
NAV_HOVER_BG = "#ffffff"
NAV_PRESS_BG = "#b8b3aa"


def _is_descendant_or_self(widget, ancestor) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = getattr(widget, "master", None)
    return False


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
        on_navigate: NavigateHandler | None = None,
        nav_has_newer: bool = False,
        nav_has_older: bool = False,
        initial_tool: Tool | None = None,
        auto_copy_on_close: bool | None = None,
    ) -> None:
        super().__init__(root)
        self.image = image.copy()
        self.settings = settings
        self.auto_copy_on_close = (
            bool(settings.auto_copy)
            if auto_copy_on_close is None
            else bool(auto_copy_on_close)
        )
        self.on_copy = on_copy
        self.on_save = on_save
        self.on_autosave = on_autosave
        self.on_navigate = on_navigate
        self.on_close = on_close
        self.on_return = on_return
        self._nav_has_newer = bool(nav_has_newer)
        self._nav_has_older = bool(nav_has_older)
        self._nav_buttons: dict[int, FlatButton] = {}
        self._nav_visible = {-1: False, 1: False}
        self._nav_check_job: str | None = None
        self._navigating = False
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
        log.info(
            "编辑器：创建编辑窗口，图片=%d×%d，可切换：更新=%s 更早=%s",
            self.image.width,
            self.image.height,
            self._nav_has_newer,
            self._nav_has_older,
        )

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
        self._build_nav_arrows()
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

    # ------------------------------------------------------------- navigation
    def _build_nav_arrows(self) -> None:
        if self.on_navigate is None:
            return
        canvas = self._canvas.canvas
        for side, icon_name in ((-1, "chevron-left"), (1, "chevron-right")):
            button = FlatButton(
                canvas,
                " ",
                lambda s=side: self._navigate(s),
                fonts=self.fonts,
                padx=8,
                pady=10,
                bg=NAV_IDLE_BG,
                fg=TEXT,
                hover_bg=NAV_HOVER_BG,
                press_bg=NAV_PRESS_BG,
                image=self.icons.get(icon_name, NAV_ARROW_SIZE, TEXT),
                disabled_image=self.icons.get(
                    icon_name, NAV_ARROW_SIZE, DISABLED_TEXT
                ),
                compound="center",
                highlightthickness=1,
                highlightbackground=BORDER,
                bd=0,
            )
            self._nav_buttons[side] = button
            button.bind(
                "<Enter>",
                lambda _event, s=side: self._reveal_nav_side(s),
                add="+",
            )
            button.bind("<Leave>", self._schedule_nav_check, add="+")
        canvas.bind("<Motion>", self._on_nav_motion, add="+")
        canvas.bind("<Enter>", self._on_nav_motion, add="+")
        canvas.bind("<Leave>", self._schedule_nav_check, add="+")
        self._update_nav_enabled()

    def _update_nav_enabled(self) -> None:
        if not self._nav_buttons:
            return
        self._nav_buttons[-1].set_enabled(self._nav_has_newer)
        self._nav_buttons[1].set_enabled(self._nav_has_older)

    def _on_nav_motion(self, event: tk.Event) -> None:
        if not self._nav_buttons:
            return
        self._cancel_nav_check()
        width = max(1, self._canvas.canvas.winfo_width())
        self._set_nav_visible(-1, event.x <= NAV_EDGE_ZONE_PX)
        self._set_nav_visible(
            1, event.x >= width - NAV_EDGE_ZONE_PX
        )

    def _reveal_nav_side(self, side: int) -> None:
        self._cancel_nav_check()
        self._set_nav_visible(side, True)
        self._set_nav_visible(-side, False)

    def _schedule_nav_check(self, _event=None) -> None:
        if not self._nav_buttons or self._closed:
            return
        self._cancel_nav_check()
        self._nav_check_job = self.after(70, self._check_nav_hover)

    def _cancel_nav_check(self) -> None:
        job = self._nav_check_job
        self._nav_check_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass

    def _check_nav_hover(self) -> None:
        self._nav_check_job = None
        if self._closed or not self._nav_buttons:
            return
        try:
            pointer_x, pointer_y = self.winfo_pointerxy()
            under = self.winfo_containing(pointer_x, pointer_y)
        except (tk.TclError, KeyError):
            # Tk's native file dialog is created in Tcl and is not registered
            # as a Python widget, so winfo_containing() can raise KeyError
            # (nametowidget) while it owns the pointer/grab.
            self._hide_nav_arrows()
            return
        for side, button in self._nav_buttons.items():
            if under is not None and _is_descendant_or_self(under, button):
                self._set_nav_visible(side, True)
                self._set_nav_visible(-side, False)
                return
        canvas = self._canvas.canvas
        if under is not None and _is_descendant_or_self(under, canvas):
            x = pointer_x - canvas.winfo_rootx()
            width = max(1, canvas.winfo_width())
            self._set_nav_visible(-1, x <= NAV_EDGE_ZONE_PX)
            self._set_nav_visible(
                1, x >= width - NAV_EDGE_ZONE_PX
            )
            return
        self._hide_nav_arrows()

    def _set_nav_visible(self, side: int, visible: bool) -> None:
        button = self._nav_buttons.get(side)
        if button is None or self._nav_visible.get(side) == visible:
            return
        self._nav_visible[side] = visible
        if visible:
            button.place(
                in_=self._canvas.canvas,
                relx=0.0 if side == -1 else 1.0,
                rely=0.5,
                x=NAV_INSET_PX if side == -1 else -NAV_INSET_PX,
                anchor="w" if side == -1 else "e",
            )
            button.lift()
        else:
            button.place_forget()

    def _hide_nav_arrows(self) -> None:
        self._set_nav_visible(-1, False)
        self._set_nav_visible(1, False)

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

    def _autosave(self) -> bool:
        self._autosave_job = None
        if self._closed or self.on_autosave is None:
            return False
        try:
            rendered = self._canvas.render()
            result = self.on_autosave(rendered)
        except Exception as exc:
            log.exception("自动保存截图失败")
            self._status_var.set(f"自动保存失败：{exc}")
            self.show_toast(f"自动保存失败：{exc}", error=True)
            return False
        if result is False:
            message = "自动保存失败：最近截图未能更新"
            log.warning("编辑器：%s，图片=%d×%d", message, *rendered.size)
            self._status_var.set(message)
            self.show_toast(message, error=True)
            return False
        self._done = True
        self.mark_exported()
        self._status_var.set("修改已自动保存。")
        log.info(
            "编辑器：自动保存成功，图片=%d×%d",
            rendered.width,
            rendered.height,
        )
        return True

    def _flush_autosave(self) -> None:
        if self._autosave_job is None:
            return
        self._cancel_autosave()
        self._autosave()

    def _persist_before_navigation(self) -> bool:
        self._cancel_autosave()
        if self.document.content_signature() == self._clean_signature:
            return True
        log.info("编辑器导航：切换前保存当前修改")
        if self.on_autosave is None:
            message = "自动保存不可用，已取消切换。"
            log.warning("编辑器导航：%s", message)
            self._status_var.set(message)
            self.show_toast(message, error=True)
            return False
        if not self._autosave():
            message = "自动保存失败，已取消切换。"
            log.warning("编辑器导航：%s", message)
            self._status_var.set(message)
            self.show_toast(message, error=True)
            return False
        return True

    def _navigate(self, direction: int) -> None:
        label = "上一张（更新）" if direction == -1 else "下一张（更早）"
        log.info("用户操作：编辑器%s", label)
        if (
            self._closed
            or self._navigating
            or self.on_navigate is None
            or direction not in (-1, 1)
        ):
            log.warning("编辑器导航被忽略：编辑器已关闭或导航不可用")
            return
        if direction == -1 and not self._nav_has_newer:
            log.info("编辑器导航：没有更新的一张")
            return
        if direction == 1 and not self._nav_has_older:
            log.info("编辑器导航：没有更早的一张")
            return
        self._navigating = True
        try:
            self._canvas.commit_pending_entry()
            if not self._persist_before_navigation():
                return
            try:
                target = self.on_navigate(direction)
            except Exception as exc:
                log.exception("切换相邻截图失败")
                message = f"切换截图失败：{exc}"
                self._status_var.set(message)
                self.show_toast(message, error=True)
                return
            if target is None:
                message = "没有可切换的截图。"
                log.warning("编辑器导航失败：%s", message)
                self._status_var.set(message)
                self.show_toast(message, error=True)
                return
            self._apply_navigation_target(target)
        finally:
            self._navigating = False

    def _apply_navigation_target(self, target: NavigationTarget) -> None:
        log.info(
            "编辑器：切换到记录 id=%s，图片=%d×%d，可切换：更新=%s 更早=%s",
            target.entry_id,
            target.image.width,
            target.image.height,
            target.has_newer,
            target.has_older,
        )
        document = AnnotationDocument(target.image, self.font_resolver)
        self.image = target.image.copy()
        self.document = document
        self._canvas.set_document(document)
        self.mark_exported()
        self._size_var.set(
            f"{document.base.width} × {document.base.height}"
        )
        self._nav_has_newer = target.has_newer
        self._nav_has_older = target.has_older
        self._update_nav_enabled()
        self._cancel_autosave()
        self._done = False
        self._status_var.set("已切换到相邻截图。")
        self.show_toast("已切换截图")
        try:
            self._canvas.canvas.focus_set()
        except tk.TclError:
            pass

    def _on_zoom(self, scale: float) -> None:
        self._zoom_var.set(f"缩放 {scale * 100:.0f}%")

    # -------------------------------------------------------------- actions
    def show_toast(self, message: str, error: bool = False) -> None:
        if error:
            log.warning("编辑器提示：%s", message)
        else:
            log.info("编辑器提示：%s", message)
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
        log.info(
            "用户操作：编辑器复制截图，图片=%d×%d",
            rendered.width,
            rendered.height,
        )
        self.show_toast("已复制到剪贴板")
        self._flash_copy_button()

    def _copy_on_close(self) -> None:
        """Copy the final image before the editor closes when enabled."""
        if not self.auto_copy_on_close:
            log.info("用户操作：关闭编辑器时未复制截图（设置已关闭）")
            return
        try:
            self._canvas.commit_pending_entry()
            rendered = self._canvas.render()
            self.on_copy(rendered)
            log.info(
                "用户操作：关闭编辑器时自动复制截图，图片=%d×%d",
                rendered.width,
                rendered.height,
            )
        except Exception as exc:
            log.exception("关闭截图时自动复制失败")
            self._status_var.set(f"自动复制失败：{exc}")

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
        log.info(
            "用户操作：编辑器保存截图到 %s，图片=%d×%d",
            path,
            rendered.width,
            rendered.height,
        )
        self.show_toast("保存成功")

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

    def save_as(self) -> None:
        self._canvas.commit_pending_entry()
        self._release_stale_grab()
        extension = self._extension()
        path = open_native_file_dialog(
            self,
            filedialog.asksaveasfilename,
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
            log.info("用户操作：取消另存为截图")
            try:
                self._canvas.canvas.focus_set()
            except tk.TclError:
                pass
            return
        log.info("用户操作：截图另存为 %s", path)
        try:
            self._canvas.commit_pending_entry()
            rendered = self._canvas.render()
            saved = self.on_save(rendered, Path(path))
        except Exception as exc:
            log.exception("另存截图失败：%s", path)
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
        log.info(
            "用户操作：请求关闭编辑器，返回助手=%s", return_to_assistant
        )
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
            log.warning("编辑器关闭：存在未保存修改，弹出确认框")
            confirmed = run_modal_dialog(
                self,
                lambda **kwargs: messagebox.askyesno(
                    title, message, **kwargs
                ),
            )
            log.info("编辑器关闭：未保存确认结果=%s", confirmed)
            if not confirmed:
                return
        self._copy_on_close()
        self._finish(return_to_assistant=return_to_assistant)

    def _finish(self, return_to_assistant: bool = False) -> None:
        if self._closed:
            return
        log.info(
            "编辑器：窗口关闭，完成=%s，返回助手=%s",
            self._done,
            return_to_assistant,
        )
        self._closed = True
        for job_name in (
            "_focus_job",
            "_focus_canvas_job",
            "_toast_job",
            "_copy_flash_job",
            "_autosave_job",
            "_nav_check_job",
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
        self._hide_nav_arrows()
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
