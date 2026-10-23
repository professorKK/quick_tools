"""Searchable, scrollable recent screenshot list."""

from __future__ import annotations

import logging
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageTk

from quicktools.modal_dialogs import run_modal_dialog
from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    BUTTON,
    DANGER,
    FlatButton,
    MUTED,
    TEXT,
    pick_fonts,
    reveal_in_file_manager,
)

from ..models import CaptureError, CaptureMode
from .icons import IconSet
from .widgets import (
    ActionLink,
    FilterMenu,
    PlaceholderEntry,
    ScrollableFrame,
)

if TYPE_CHECKING:
    from ..plugin import ScreenshotPlugin

log = logging.getLogger(__name__)

ToastHandler = Callable[[str, bool], None]

_FILTER_OPTIONS = [
    ("全部", "all"),
    ("已收藏", "favorite"),
    None,
    *[(mode.label, mode.value) for mode in CaptureMode],
]
_MODE_VALUES = {mode.value for mode in CaptureMode}
_STAR_COLOR = "#f59e0b"


class RecentView(tk.Frame):
    INITIAL_ROW_COUNT = 8
    ROW_CHUNK_BUDGET_SECONDS = 0.025
    ROW_CHUNK_DELAY_MS = 10

    def __init__(
        self,
        master: tk.Misc,
        plugin: "ScreenshotPlugin",
        *,
        on_toast: ToastHandler | None = None,
        icons: IconSet | None = None,
    ) -> None:
        super().__init__(master, bg=BG)
        self.plugin = plugin
        self.on_toast = on_toast
        self.fonts = pick_fonts(master)
        self.icons = icons or IconSet(self)
        self._photos: list[ImageTk.PhotoImage] = []
        self._search_var = tk.StringVar()
        self._search_job: str | None = None
        self._filter_var = tk.StringVar(value="all")
        self._filter_button: FlatButton | None = None
        self._entries: list = []
        self._render_job: str | None = None
        self._render_generation = 0
        self._render_cursor = 0
        self._build()
        self._search_trace = self._search_var.trace_add(
            "write", self._on_search_changed
        )
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", pady=(0, 8))
        tk.Label(
            header,
            text="最近截图",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(13, "bold"),
        ).pack(side="left")

        self._filter_menu = FilterMenu(
            self, self._filter_var, _FILTER_OPTIONS, self._on_filter_changed
        )
        self._filter_button = FlatButton(
            header,
            "筛选",
            lambda: self._filter_menu.popup(self._filter_button),
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("filter", 15, MUTED),
        )
        self._filter_button.pack(side="right")
        FlatButton(
            header,
            "清空",
            self._clear,
            fonts=self.fonts,
            font_size=9,
            padx=9,
            pady=5,
            bg=BUTTON,
            fg=TEXT,
            image=self.icons.get("trash", 15, MUTED),
        ).pack(side="right", padx=(0, 6))

        search = PlaceholderEntry(
            header,
            self.fonts,
            placeholder="搜索截图名称、模式、日期…",
            textvariable=self._search_var,
            icons=self.icons,
            background=BG,
        )
        search.pack(side="left", fill="x", expand=True, padx=(14, 10))

        border = tk.Frame(self, bg=BORDER)
        border.pack(fill="both", expand=True)
        self._scroll = ScrollableFrame(
            border, background=BG, scrollbar_bg=BG
        )
        self._scroll.pack(fill="both", expand=True, padx=1, pady=1)

    # --------------------------------------------------------------- refresh
    def _on_search_changed(self, *_args) -> None:
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.after(120, self._refresh_from_search)

    def _refresh_from_search(self) -> None:
        self._search_job = None
        query = self._search_var.get().strip()
        if query:
            log.info("用户操作：搜索最近截图 %r", query)
        self.refresh()
        self._scroll.scroll_to_top()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        try:
            self._search_var.trace_remove("write", self._search_trace)
        except Exception:
            pass
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
            self._search_job = None
        self._cancel_pending_render()

    def _on_filter_changed(self) -> None:
        log.info(
            "用户操作：筛选最近截图，筛选=%s，搜索=%r",
            self._filter_var.get(),
            self._search_var.get().strip(),
        )
        self.refresh()
        self._scroll.scroll_to_top()

    def _set_filter(self, value: str) -> None:
        self._filter_var.set(value)
        self._on_filter_changed()

    def _filter_args(self) -> tuple[bool | None, str | None]:
        value = self._filter_var.get()
        favorite = True if value == "favorite" else None
        mode = value if value in _MODE_VALUES else None
        return favorite, mode

    def _cancel_pending_render(self) -> None:
        self._render_generation += 1
        job = self._render_job
        self._render_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass

    def _render_more_rows(self, generation: int) -> None:
        self._render_job = None
        if generation != self._render_generation or not self.winfo_exists():
            return
        deadline = time.perf_counter() + self.ROW_CHUNK_BUDGET_SECONDS
        total = len(self._entries)
        cursor = self._render_cursor
        while cursor < total:
            row = self._build_row(self._entries[cursor])
            self._scroll.bind_wheel(row)
            cursor += 1
            if time.perf_counter() >= deadline:
                break
        self._render_cursor = cursor
        if cursor < total:
            self._render_job = self.after(
                self.ROW_CHUNK_DELAY_MS,
                lambda: self._render_more_rows(generation),
            )

    def refresh(self) -> None:
        self._cancel_pending_render()
        for child in self._scroll.inner.winfo_children():
            child.destroy()
        self._photos.clear()
        service = self.plugin.service
        entries = []
        if service is not None:
            favorite, mode = self._filter_args()
            entries = service.recent_entries(
                limit=None, favorite=favorite, mode=mode
            )
        else:
            log.warning("最近截图：截图服务未启动，无法刷新列表")
        query = self._search_var.get().strip().casefold()
        if query:
            entries = [entry for entry in entries if self._matches(entry, query)]
        preview_ids = [entry.id for entry in entries[:30]]
        log.info(
            "最近截图：刷新列表，显示 %d 条，筛选=%s，搜索=%r，"
            "记录 id=%s%s",
            len(entries),
            self._filter_var.get(),
            query,
            preview_ids,
            "…" if len(entries) > len(preview_ids) else "",
        )
        self._entries = entries
        self._render_cursor = 0
        if not entries:
            self._show_empty_state(query)
            return
        initial = min(len(entries), self.INITIAL_ROW_COUNT)
        for entry in entries[:initial]:
            row = self._build_row(entry)
            self._scroll.bind_wheel(row)
        self._render_cursor = initial
        if initial < len(entries):
            generation = self._render_generation
            self._render_job = self.after(
                self.ROW_CHUNK_DELAY_MS,
                lambda: self._render_more_rows(generation),
            )

    def _show_empty_state(self, query: str) -> None:
        if query:
            text = "没有匹配的最近截图。"
        elif self._filter_var.get() == "favorite":
            text = "还没有收藏的截图。\n点击截图右侧的“收藏”即可收藏。"
        elif self._filter_var.get() in _MODE_VALUES:
            text = "没有该模式的截图。"
        else:
            text = "还没有截图。\n完成一次截图后会在这里显示缩略图和操作入口。"
        empty = tk.Label(
            self._scroll.inner,
            text=text,
            bg=BG,
            fg=MUTED,
            justify="center",
            font=self.fonts.u(10),
        )
        empty.pack(expand=True, pady=40)
        self._scroll.bind_wheel(empty)

    def _matches(self, entry, query: str) -> bool:
        try:
            mode_label = CaptureMode.from_value(entry.mode).label
        except CaptureError:
            mode_label = entry.mode or "截图"
        stamp = datetime.fromtimestamp(entry.updated_at).strftime(
            "%Y-%m-%d %H:%M"
        )
        haystack = " ".join(
            [
                mode_label,
                f"{entry.width} x {entry.height}",
                f"{entry.width}×{entry.height}",
                stamp,
                entry.name,
                str(entry.path),
            ]
        ).casefold()
        return query in haystack

    def _build_row(self, entry) -> tk.Frame:
        row = tk.Frame(
            self._scroll.inner,
            bg=BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        row.pack(fill="x", padx=6, pady=(0, 8))
        thumb = self._thumbnail(entry)
        if thumb is None:
            tk.Label(
                row,
                text="无预览",
                bg=BG,
                fg=MUTED,
                width=12,
                font=self.fonts.u(9),
            ).pack(side="left", padx=(0, 12))
        else:
            preview = tk.Label(
                row,
                image=thumb,
                bg=BG,
                bd=0,
                highlightbackground=BORDER,
                highlightthickness=1,
            )
            preview.pack(side="left", padx=(0, 12))

        meta = tk.Frame(row, bg=BG)
        meta.pack(side="left", fill="x", expand=True)
        try:
            mode_label = CaptureMode.from_value(entry.mode).label
        except CaptureError:
            mode_label = entry.mode or "截图"
        tk.Label(
            meta,
            text=f"{mode_label} · {entry.width} × {entry.height}",
            bg=BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        ).pack(anchor="w")
        stamp = datetime.fromtimestamp(entry.updated_at).strftime(
            "%m-%d %H:%M"
        )
        tk.Label(
            meta,
            text=stamp,
            bg=BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(8),
        ).pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(row, bg=BG)
        actions.pack(side="right", padx=(4, 4))
        favorite_color = _STAR_COLOR if entry.favorite else MUTED
        for icon_name, text, command, color, hover_color in (
            ("folder", "打开", lambda e=entry: self._reveal(e), MUTED, ACCENT),
            ("copy", "复制", lambda e=entry: self._copy(e), MUTED, ACCENT),
            ("edit", "编辑", lambda e=entry: self._edit(e), MUTED, ACCENT),
            (
                "star-filled" if entry.favorite else "star",
                "已收藏" if entry.favorite else "收藏",
                lambda e=entry: self._toggle_favorite(e),
                favorite_color,
                ACCENT,
            ),
            (
                "trash",
                "删除",
                lambda e=entry: self._delete(e),
                DANGER,
                DANGER,
            ),
        ):
            ActionLink(
                actions,
                icon_name=icon_name,
                text=text,
                command=command,
                fonts=self.fonts,
                icons=self.icons,
                bg=BG,
                color=color,
                hover_color=hover_color,
            ).pack(side="left", padx=(6, 0))
        return row

    def _thumbnail(self, entry) -> ImageTk.PhotoImage | None:
        service = self.plugin.service
        if service is None or service.recent is None:
            return None
        path = service.recent.thumb_path(entry)
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                thumb = image.copy()
            thumb.thumbnail((112, 72), Image.LANCZOS)
            photo = ImageTk.PhotoImage(thumb, master=self)
        except Exception:
            log.warning(
                "读取截图缩略图失败：记录 id=%s，文件=%s",
                entry.id,
                path,
                exc_info=True,
            )
            return None
        self._photos.append(photo)
        return photo

    # --------------------------------------------------------------- actions
    def _toast(self, message: str, error: bool = False) -> None:
        if self.on_toast is not None:
            self.on_toast(message, error)

    @staticmethod
    def _describe(entry) -> str:
        return (
            f"id={entry.id} 模式={entry.mode or '未知'} "
            f"尺寸={entry.width}×{entry.height} "
            f"收藏={bool(entry.favorite)} "
            f"文件={entry.path}"
        )

    def _reveal(self, entry) -> None:
        log.info("用户操作：在文件管理器中定位最近截图 %s", self._describe(entry))
        try:
            reveal_in_file_manager(entry.path)
        except Exception as exc:
            log.exception("定位最近截图文件失败：%s", entry.path)
            self._toast(f"无法打开文件管理器：{exc}", True)
            return
        self._toast("已打开截图所在位置")

    def _edit(self, entry) -> None:
        log.info("用户操作：最近截图列表编辑图片 %s", self._describe(entry))
        service = self.plugin.service
        if service is None:
            log.warning("编辑最近截图失败：截图服务未启动")
            return
        service.open_recent(entry)

    def _copy(self, entry) -> None:
        log.info("用户操作：最近截图列表复制图片 %s", self._describe(entry))
        service = self.plugin.service
        if service is None:
            log.warning("复制最近截图失败：截图服务未启动")
            return
        service.copy_recent(entry)
        status = service.last_status or "截图已复制到剪贴板"
        self._toast(status, "失败" in status or "不可用" in status)

    def _toggle_favorite(self, entry) -> None:
        log.info(
            "用户操作：切换最近截图收藏 %s", self._describe(entry)
        )
        service = self.plugin.service
        if service is None:
            log.warning("收藏最近截图失败：截图服务未启动")
            return
        updated = service.toggle_recent_favorite(entry)
        self.refresh()
        if updated is not None:
            self._toast("已收藏截图" if updated.favorite else "已取消收藏")
        else:
            status = getattr(service, "last_status", "")
            self._toast(status or "收藏失败", True)

    def _confirm_delete(self, entry) -> bool:
        message = (
            "确定删除这张截图及其文件吗？\n\n"
            f"{entry.name}\n\n"
            "此操作不可撤销。"
        )
        try:
            return bool(
                run_modal_dialog(
                    self,
                    lambda parent: messagebox.askyesno(
                        "删除截图", message, parent=parent
                    ),
                )
            )
        except Exception:
            log.exception("删除最近截图的确认框失败：id=%s", entry.id)
            return False

    def _delete(self, entry) -> None:
        log.info("用户操作：删除最近截图 %s", self._describe(entry))
        if not self._confirm_delete(entry):
            log.info("用户操作：取消删除最近截图 id=%s", entry.id)
            return
        service = self.plugin.service
        if service is None:
            log.warning("删除最近截图失败：截图服务未启动")
            self._toast("截图服务未启动", True)
            return
        deleted = service.delete_recent(entry)
        self.refresh()
        if deleted:
            self._toast("已删除截图")
            return
        status = getattr(service, "last_status", "")
        self._toast(status or "删除截图失败", True)

    def _clear(self) -> None:
        log.info("用户操作：最近截图列表点击清空全部")
        service = self.plugin.service
        if service is None:
            log.warning("清空最近截图失败：截图服务未启动")
            self._toast("截图服务未启动", True)
            return
        service.clear_recent()
        self.refresh()
        status = service.last_status or "已清空最近截图"
        self._toast(status, "失败" in status or "未删除" in status)
