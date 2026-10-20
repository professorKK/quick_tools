"""Searchable, scrollable recent screenshot list."""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from PIL import Image, ImageTk

from quicktools.ui_theme import (
    BG,
    BORDER,
    BUTTON,
    FlatButton,
    MUTED,
    TEXT,
    pick_fonts,
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
            placeholder="搜索截图名称、内容...",
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

    def _on_filter_changed(self) -> None:
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

    def refresh(self) -> None:
        for child in self._scroll.inner.winfo_children():
            child.destroy()
        self._photos.clear()
        service = self.plugin.service
        entries = []
        if service is not None:
            favorite, mode = self._filter_args()
            entries = service.recent_entries(
                limit=500, favorite=favorite, mode=mode
            )
        query = self._search_var.get().strip().casefold()
        if query:
            entries = [entry for entry in entries if self._matches(entry, query)]
        if not entries:
            self._show_empty_state(query)
            return
        for entry in entries:
            row = self._build_row(entry)
            self._scroll.bind_wheel(row)

    def _show_empty_state(self, query: str) -> None:
        if query:
            text = "没有匹配的最近截图。"
        elif self._filter_var.get() == "favorite":
            text = "还没有收藏的截图。\n点击截图右侧的星标即可收藏。"
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
        saved_name = ""
        if entry.saved_path:
            saved_name = entry.saved_path.replace("\\", "/").rsplit("/", 1)[-1]
        haystack = " ".join(
            [
                mode_label,
                f"{entry.width} x {entry.height}",
                f"{entry.width}×{entry.height}",
                stamp,
                saved_name,
                entry.source or "",
                entry.png_path,
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

        star = tk.Label(
            row,
            bg=BG,
            cursor="hand2",
            image=self.icons.get(
                "star-filled" if entry.favorite else "star",
                20,
                _STAR_COLOR if entry.favorite else MUTED,
            ),
        )
        star.pack(side="right", padx=(8, 2))
        star.bind("<Button-1>", lambda _event, e=entry: self._toggle_favorite(e))

        actions = tk.Frame(row, bg=BG)
        actions.pack(side="right", padx=(4, 4))
        for icon_name, text, command in (
            ("open", "打开", lambda e=entry: self._open(e)),
            ("copy", "复制", lambda e=entry: self._copy(e)),
            ("trash", "删除", lambda e=entry: self._delete(e)),
        ):
            ActionLink(
                actions,
                icon_name=icon_name,
                text=text,
                command=command,
                fonts=self.fonts,
                icons=self.icons,
                bg=BG,
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
            log.debug("读取截图缩略图失败", exc_info=True)
            return None
        self._photos.append(photo)
        return photo

    # --------------------------------------------------------------- actions
    def _toast(self, message: str, error: bool = False) -> None:
        if self.on_toast is not None:
            self.on_toast(message, error)

    def _open(self, entry) -> None:
        service = self.plugin.service
        if service is not None:
            service.open_recent(entry)

    def _copy(self, entry) -> None:
        service = self.plugin.service
        if service is None:
            return
        service.copy_recent(entry)
        status = service.last_status or "截图已复制到剪贴板"
        self._toast(status, "失败" in status or "不可用" in status)

    def _toggle_favorite(self, entry) -> None:
        service = self.plugin.service
        if service is None:
            return
        updated = service.toggle_recent_favorite(entry)
        self.refresh()
        if updated is not None:
            self._toast("已收藏截图" if updated.favorite else "已取消收藏")
        else:
            status = getattr(service, "last_status", "")
            self._toast(status or "收藏失败", True)

    def _delete(self, entry) -> None:
        service = self.plugin.service
        if service is not None:
            service.delete_recent(entry)
        self.refresh()
        self._toast("已删除截图记录")

    def _clear(self) -> None:
        service = self.plugin.service
        if service is not None:
            service.clear_recent()
        self.refresh()
        self._toast("已清空最近截图")
