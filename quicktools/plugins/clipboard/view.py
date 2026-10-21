"""Three-pane clipboard history window."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from PIL import Image, ImageTk
from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    BUTTON,
    DANGER,
    MUTED,
    PANEL,
    PANEL_ALT,
    ROW_ACTIVE,
    SUCCESS,
    TEXT,
    FlatButton,
    Fonts,
    pick_fonts,
)

from .models import (
    ClipboardEntry,
    ClipboardError,
    ClipboardKind,
    PartialFilesError,
    current_platform,
    platform_label,
)
from .platform_utils import (
    accessible_paths,
    format_count,
    format_size,
    format_time,
    middle_ellipsis,
    preview_text,
    reveal_path,
    source_label,
)
from .service import ClipboardService
from .widgets import (
    NavItem,
    PlaceholderEntry,
    ScrollableFrame,
    TypeBadge,
    bind_wheel_recursive,
    horizontal_divider,
    vertical_divider,
)

log = logging.getLogger(__name__)

CARD_HOVER = "#f8fafc"


class ClipboardView(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        service: ClipboardService | None,
        startup_error: str = "",
        on_open_settings: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg=BG)
        self.service = service
        self._startup_error = startup_error
        self._on_open_settings = on_open_settings
        self.fonts: Fonts = pick_fonts(self.winfo_toplevel())
        self._detached = False
        self._listener = self._on_service_event
        self._entries: list[ClipboardEntry] = []
        self._selected_id: int | None = None
        self._filter_kind: ClipboardKind | None = None
        self._newest_first = True
        self._search_job: str | None = None
        self._flash_job: str | None = None
        self._card_rows: dict[int, list[tk.Widget]] = {}
        self._card_labels: dict[int, dict[str, tk.Label]] = {}
        self._current_entry: ClipboardEntry | None = None
        self._detail_signature: tuple | None = None
        self._text_editor: tk.Text | None = None
        self._edit_save_job: str | None = None
        self._edit_dirty = False
        self._preview_photo = None
        self._thumb_photo = None
        self._counts = {"all": 0, "text": 0, "image": 0, "files": 0}
        self._last_status_level = "ok"

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=232)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=3, minsize=360)
        self.grid_columnconfigure(3, weight=0)
        self.grid_columnconfigure(4, weight=2, minsize=340)

        self._build_sidebar().grid(row=0, column=0, sticky="nsew")
        vertical_divider(self).grid(row=0, column=1, sticky="ns")
        self._build_list_panel().grid(row=0, column=2, sticky="nsew")
        vertical_divider(self).grid(row=0, column=3, sticky="ns")
        self._build_detail_panel().grid(row=0, column=4, sticky="nsew")

        if self.service is not None:
            self.service.add_listener(self._listener)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._bind_keys()
        self.refresh(reset_scroll=True)

    # ---------------------------------------------------------------- layout
    def _build_sidebar(self) -> tk.Frame:
        sidebar = tk.Frame(self, bg=PANEL, padx=14, pady=16)
        header = tk.Frame(sidebar, bg=PANEL)
        header.pack(fill="x", pady=(0, 18))
        badge = tk.Frame(header, bg=ACCENT, width=46, height=46)
        badge.pack(side="left", padx=(0, 12))
        badge.pack_propagate(False)
        tk.Label(
            badge,
            text="C",
            bg=ACCENT,
            fg="#ffffff",
            font=self.fonts.u(22, "bold"),
        ).pack(fill="both", expand=True)
        titles = tk.Frame(header, bg=PANEL)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text="剪贴板",
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(17, "bold"),
        ).pack(fill="x")
        tk.Label(
            titles,
            text="记录你的每一次复制",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(fill="x", pady=(3, 0))

        self._count_vars = {
            "all": tk.StringVar(value="0"),
            "text": tk.StringVar(value="0"),
            "image": tk.StringVar(value="0"),
            "files": tk.StringVar(value="0"),
        }
        nav = tk.Frame(sidebar, bg=PANEL)
        nav.pack(fill="x")
        self._nav_items: dict[str, NavItem] = {}
        entries = (
            ("all", "全部记录", "≡", None),
            ("text", "文本", "T", ClipboardKind.TEXT),
            ("image", "图片", "P", ClipboardKind.IMAGE),
            ("files", "文件", "F", ClipboardKind.FILES),
        )
        for key, label, glyph, kind in entries:
            item = NavItem(
                nav,
                label,
                glyph,
                self.fonts,
                lambda k=kind: self._set_filter(k),
                count_var=self._count_vars[key],
            )
            item.pack(fill="x", pady=1)
            self._nav_items[key] = item

        tk.Frame(sidebar, bg=PANEL, height=14).pack(fill="x")
        horizontal_divider(sidebar).pack(fill="x", padx=6)
        tk.Frame(sidebar, bg=PANEL, height=10).pack(fill="x")
        NavItem(
            sidebar,
            "搜索",
            "⌕",
            self.fonts,
            self.focus_search,
        ).pack(fill="x", pady=1)
        NavItem(
            sidebar,
            "设置",
            "⚙",
            self.fonts,
            self._open_settings,
        ).pack(fill="x", pady=1)

        spacer = tk.Frame(sidebar, bg=PANEL)
        spacer.pack(fill="both", expand=True)
        status = tk.Frame(
            sidebar,
            bg=PANEL_ALT,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        status.pack(fill="x", side="bottom")
        line = tk.Frame(status, bg=PANEL_ALT)
        line.pack(fill="x")
        self._status_dot = tk.Canvas(
            line,
            width=12,
            height=12,
            bg=PANEL_ALT,
            highlightthickness=0,
            bd=0,
        )
        self._status_dot.pack(side="left", padx=(0, 7))
        self._status_dot_id = self._status_dot.create_oval(
            2, 2, 10, 10, fill=SUCCESS, outline=""
        )
        self._status_headline = tk.StringVar(value="正在启动…")
        tk.Label(
            line,
            textvariable=self._status_headline,
            bg=PANEL_ALT,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(8, "bold"),
        ).pack(side="left", fill="x", expand=True)
        self._status_detail = tk.StringVar(value="")
        tk.Label(
            status,
            textvariable=self._status_detail,
            bg=PANEL_ALT,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=185,
            font=self.fonts.u(8),
        ).pack(fill="x", pady=(5, 0))
        return sidebar

    def _build_list_panel(self) -> tk.Frame:
        panel = tk.Frame(self, bg=BG, padx=14, pady=14)
        header = tk.Frame(panel, bg=BG)
        header.pack(fill="x", pady=(0, 10))
        self.search = PlaceholderEntry(
            header,
            self.fonts,
            placeholder="搜索剪贴板内容…",
            background=PANEL,
        )
        self.search.pack(side="left", fill="x", expand=True)
        self.search.var.trace_add("write", self._on_search_changed)
        self._filter_button = FlatButton(
            header,
            "筛选",
            self._open_filter_menu,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=8,
        )
        self._filter_button.pack(side="left", padx=(8, 0))
        self._sort_button = FlatButton(
            header,
            "↓ 最新",
            self._toggle_sort,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=8,
        )
        self._sort_button.pack(side="left", padx=(6, 0))

        border = tk.Frame(panel, bg=BORDER)
        border.pack(fill="both", expand=True)
        holder = tk.Frame(border, bg=BG)
        holder.pack(fill="both", expand=True, padx=1, pady=1)
        self.list_scroll = ScrollableFrame(holder, background=BG)
        self.list_scroll.pack(fill="both", expand=True)
        return panel

    def _build_detail_panel(self) -> tk.Frame:
        panel = tk.Frame(self, bg=BG, padx=16, pady=14)
        header = tk.Frame(panel, bg=BG)
        header.pack(fill="x")
        self._detail_badge_holder = tk.Frame(header, bg=BG)
        self._detail_badge_holder.pack(side="left", padx=(0, 12))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        self._detail_title_var = tk.StringVar(value="")
        tk.Label(
            titles,
            textvariable=self._detail_title_var,
            bg=BG,
            fg=TEXT,
            anchor="w",
            justify="left",
            wraplength=300,
            font=self.fonts.u(14, "bold"),
        ).pack(fill="x")
        self._detail_meta_var = tk.StringVar(value="")
        tk.Label(
            titles,
            textvariable=self._detail_meta_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(fill="x", pady=(3, 0))
        self._detail_time_var = tk.StringVar(value="")
        tk.Label(
            titles,
            textvariable=self._detail_time_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(fill="x", pady=(2, 0))

        actions = tk.Frame(panel, bg=BG)
        actions.pack(fill="x", pady=(14, 8))
        self._copy_button = FlatButton(
            actions,
            "二次复制",
            self._copy_current,
            fonts=self.fonts,
            accent=True,
            font_size=10,
            padx=14,
            pady=8,
        )
        self._copy_button.pack(side="left")
        self._reveal_button = FlatButton(
            actions,
            "打开位置",
            self._reveal_current,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=8,
        )
        self._reveal_button.pack(side="left", padx=(8, 0))
        self._delete_button = FlatButton(
            actions,
            "删除",
            self._delete_current,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=8,
            fg=DANGER,
        )
        self._delete_button.pack(side="left", padx=(8, 0))

        self._message_var = tk.StringVar(value="")
        self._message_label = tk.Label(
            panel,
            textvariable=self._message_var,
            bg=BG,
            fg=SUCCESS,
            anchor="w",
            font=self.fonts.u(9),
        )
        self._message_label.pack(fill="x", pady=(0, 6))

        self.detail_scroll = ScrollableFrame(panel, background=BG)
        self.detail_scroll.pack(fill="both", expand=True)
        self._render_detail(None, force=True)
        return panel

    # --------------------------------------------------------------- refresh
    def refresh(self, reset_scroll: bool = False, *_args) -> None:
        self._search_job = None
        if self._detached:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        if self.service is None:
            self._entries = []
            self._selected_id = None
            self._update_counts()
            self._update_nav_selection()
            self._render_list(reset_scroll=True)
            self._render_detail(None, force=True)
            self._update_status()
            return

        try:
            self._counts = self.service.counts()
            self._entries = self.service.entries(
                self._filter_kind,
                self.search.get(),
                newest_first=self._newest_first,
            )
        except Exception:
            log.exception("刷新剪贴板列表失败")
            self._entries = []
        self._update_counts()
        self._update_nav_selection()

        ids = {entry.id for entry in self._entries}
        if self._selected_id not in ids:
            self._selected_id = self._entries[0].id if self._entries else None
        self._render_list(reset_scroll=reset_scroll)
        self._render_detail(self._selected_entry())
        self._update_status()

    def _selected_entry(self) -> ClipboardEntry | None:
        for entry in self._entries:
            if entry.id == self._selected_id:
                return entry
        return None

    def _update_counts(self) -> None:
        for key, var in self._count_vars.items():
            var.set(str(self._counts.get(key, 0)))

    def _update_nav_selection(self) -> None:
        key = {
            None: "all",
            ClipboardKind.TEXT: "text",
            ClipboardKind.IMAGE: "image",
            ClipboardKind.FILES: "files",
        }[self._filter_kind]
        for name, item in self._nav_items.items():
            item.set_selected(name == key)

    def _render_list(self, *, reset_scroll: bool) -> None:
        inner = self.list_scroll.inner
        try:
            previous = self.list_scroll.canvas.yview()[0]
        except tk.TclError:
            previous = 0.0
        for child in inner.winfo_children():
            child.destroy()
        self._card_rows.clear()
        self._card_labels.clear()

        if not self._entries:
            empty = tk.Frame(inner, bg=BG)
            empty.pack(fill="both", expand=True, pady=80)
            message = (
                "剪贴板服务未启动"
                if self.service is None
                else "没有匹配的剪贴板记录"
            )
            tk.Label(
                empty,
                text=message,
                bg=BG,
                fg=MUTED,
                font=self.fonts.u(11),
            ).pack()
            if self.service is not None:
                tk.Label(
                    empty,
                    text="复制一些内容后，记录会自动出现在这里。",
                    bg=BG,
                    fg=MUTED,
                    font=self.fonts.u(9),
                ).pack(pady=(6, 0))
        else:
            for entry in self._entries:
                self._make_card(inner, entry)

        self.update_idletasks()
        if reset_scroll:
            self.list_scroll.scroll_to_top()
        else:
            try:
                self.list_scroll.canvas.yview_moveto(previous)
            except tk.TclError:
                pass

    def _make_card(self, parent: tk.Misc, entry: ClipboardEntry) -> None:
        selected = entry.id == self._selected_id
        background = ROW_ACTIVE if selected else PANEL_ALT
        card = tk.Frame(
            parent,
            bg=background,
            highlightbackground=BORDER,
            highlightthickness=1,
            cursor="hand2",
            padx=1,
            pady=1,
        )
        card.pack(fill="x", padx=3, pady=3)
        inner = tk.Frame(card, bg=background, padx=9, pady=8)
        inner.pack(fill="x")

        badge = TypeBadge(inner, entry.kind, size=40, fonts=self.fonts)
        badge.pack(side="left", padx=(0, 10))

        time_label = tk.Label(
            inner,
            text=format_time(entry.last_copied_at),
            bg=background,
            fg=MUTED,
            anchor="ne",
            font=self.fonts.u(8),
            cursor="hand2",
        )
        time_label.pack(side="right", anchor="n", padx=(6, 0))

        text_box = tk.Frame(inner, bg=background)
        text_box.pack(side="left", fill="x", expand=True)
        title = tk.Label(
            text_box,
            text=middle_ellipsis(entry.title, 52),
            bg=background,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(11, "bold"),
            cursor="hand2",
        )
        title.pack(fill="x")
        secondary_text, secondary_color = self._card_secondary(entry)
        secondary = tk.Label(
            text_box,
            text=secondary_text,
            bg=background,
            fg=secondary_color,
            anchor="w",
            font=self.fonts.u(8),
            cursor="hand2",
        )
        secondary.pack(fill="x", pady=(2, 0))
        meta = tk.Label(
            text_box,
            text=format_count(entry.kind.value, entry.char_count, entry.byte_size),
            bg=background,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(8),
            cursor="hand2",
        )
        meta.pack(fill="x", pady=(2, 0))

        row_widgets: list[tk.Widget] = [
            card,
            inner,
            text_box,
            title,
            secondary,
            meta,
            time_label,
        ]
        for widget in (badge, badge.label):
            widget.bind(
                "<Button-1>", lambda _e, eid=entry.id: self._select(eid)
            )
            widget.bind(
                "<Double-Button-1>",
                lambda _e, eid=entry.id: self._copy_by_id(eid),
            )
        for widget in row_widgets:
            widget.bind(
                "<Button-1>", lambda _e, eid=entry.id: self._select(eid)
            )
            widget.bind(
                "<Double-Button-1>",
                lambda _e, eid=entry.id: self._copy_by_id(eid),
            )
            widget.bind(
                "<Enter>",
                lambda _e, row=row_widgets, eid=entry.id: self._card_hover(
                    row, eid, True
                ),
            )
            widget.bind(
                "<Leave>",
                lambda _e, row=row_widgets, eid=entry.id: self._card_hover(
                    row, eid, False
                ),
            )
        bind_wheel_recursive(card, self.list_scroll._on_wheel)
        self._card_rows[entry.id] = row_widgets
        self._card_labels[entry.id] = {
            "title": title,
            "secondary": secondary,
            "meta": meta,
        }

    def _card_secondary(self, entry: ClipboardEntry) -> tuple[str, str]:
        kind = entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind)
        if kind == "text":
            return preview_text(entry.text_content or "", 90), MUTED
        if kind == "image":
            return "点击查看图片预览", MUTED
        if entry.source_platform != current_platform():
            return (
                f"不可访问（来自 {platform_label(entry.source_platform)} 的路径）",
                DANGER,
            )
        available, missing = accessible_paths(entry.paths, entry.source_platform)
        if missing and available:
            first = middle_ellipsis(available[0], 60)
            return f"⚠ {first}（{len(missing)} 个文件已失效）", DANGER
        if missing:
            first = middle_ellipsis(entry.paths[0] if entry.paths else "", 60)
            return f"⚠ 文件已移动或删除：{first}", DANGER
        first = entry.paths[0] if entry.paths else ""
        if len(entry.paths) > 1:
            first = f"{first} 等 {len(entry.paths)} 个文件"
        return middle_ellipsis(first, 70), MUTED

    def _card_hover(
        self, row: list[tk.Widget], entry_id: int, entering: bool
    ) -> None:
        selected = entry_id == self._selected_id
        if entering and not selected:
            color = CARD_HOVER
        else:
            color = ROW_ACTIVE if selected else PANEL_ALT
        for widget in row:
            try:
                widget.configure(bg=color)
            except tk.TclError:
                pass

    def _select(self, entry_id: int) -> None:
        if self._selected_id == entry_id:
            return
        self._flush_text_edit()
        old = self._selected_id
        self._selected_id = entry_id
        for card_id in (old, entry_id):
            if card_id is None:
                continue
            for widget in self._card_rows.get(card_id, []):
                try:
                    widget.configure(
                        bg=ROW_ACTIVE if card_id == entry_id else PANEL_ALT
                    )
                except tk.TclError:
                    pass
        self._render_detail(self._selected_entry())

    # ----------------------------------------------------------------- detail
    @staticmethod
    def _entry_detail_signature(entry: ClipboardEntry) -> tuple:
        signature = (
            entry.id,
            entry.last_copied_at,
            entry.copy_count,
            entry.byte_size,
            entry.digest,
        )
        kind = (
            entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind)
        )
        if kind == "files":
            _available, missing = accessible_paths(
                entry.paths, entry.source_platform
            )
            signature += (len(missing),)
        return signature

    def _render_detail(self, entry: ClipboardEntry | None, *, force: bool = False) -> None:
        signature = (
            self._entry_detail_signature(entry) if entry is not None else None
        )
        if not force and signature is not None and signature == self._detail_signature:
            self._current_entry = entry
            return

        # Replacing the detail body. Persist any in-progress edit first.
        self._flush_text_edit()
        self._cancel_edit_timer()
        self._text_editor = None
        self._edit_dirty = False
        if entry is not None and self.service is not None:
            refreshed = self.service.get(entry.id)
            if refreshed is None:
                # The edit merged this row into another entry; the refresh
                # triggered by the merge renders the surviving entry.
                return
            entry = refreshed
            signature = self._entry_detail_signature(entry)
        self._current_entry = entry
        self._detail_signature = signature

        for child in self._detail_badge_holder.winfo_children():
            child.destroy()
        inner = self.detail_scroll.inner
        for child in inner.winfo_children():
            child.destroy()

        self._preview_photo = None
        self._thumb_photo = None

        if entry is None:
            self._detail_title_var.set("选择一条记录")
            self._detail_meta_var.set("查看内容、路径和复制来源")
            self._detail_time_var.set("")
            self._copy_button.set_enabled(False)
            self._reveal_button.set_enabled(False)
            self._delete_button.set_enabled(False)
            tk.Label(
                inner,
                text="从左侧选择一条剪贴板记录",
                bg=BG,
                fg=MUTED,
                font=self.fonts.u(10),
            ).pack(pady=60)
            self._bind_detail_wheel(inner)
            self.update_idletasks()
            try:
                self.detail_scroll.scroll_to_top()
            except tk.TclError:
                pass
            return

        TypeBadge(
            self._detail_badge_holder, entry.kind, size=44, fonts=self.fonts
        ).pack()
        self._detail_title_var.set(middle_ellipsis(entry.title, 60))
        self._detail_meta_var.set(
            format_count(entry.kind.value, entry.char_count, entry.byte_size)
        )
        self._detail_time_var.set(format_time(entry.last_copied_at, detail=True))
        kind = entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind)
        self._copy_button.set_enabled(True)
        self._reveal_button.set_enabled(kind != "text")
        self._delete_button.set_enabled(True)

        if kind == "text":
            self._build_text_detail(inner, entry)
        elif kind == "image":
            self._build_image_detail(inner, entry)
        else:
            self._build_files_detail(inner, entry)

        self._build_source_card(inner, entry)
        self._build_tips_card(inner)
        self._bind_detail_wheel(inner)
        self.update_idletasks()
        try:
            self.detail_scroll.scroll_to_top()
        except tk.TclError:
            pass

    def _section_label(self, parent: tk.Misc, text: str) -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            bg=BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        )
        label.pack(fill="x", pady=(12, 6))
        return label

    def _bordered(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(
            parent,
            bg=PANEL_ALT,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        return frame

    def _build_text_detail(self, parent: tk.Misc, entry: ClipboardEntry) -> None:
        self._section_label(parent, "内容（可编辑，自动保存）")
        wrapper = self._bordered(parent)
        wrapper.pack(fill="both", expand=True, pady=(0, 4))
        text = tk.Text(
            wrapper,
            height=15,
            wrap="word",
            undo=True,
            bg=PANEL_ALT,
            fg=TEXT,
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            font=self.fonts.u(10),
            insertbackground=TEXT,
            selectbackground=ACCENT,
        )
        scrollbar = tk.Scrollbar(
            wrapper,
            orient="vertical",
            command=text.yview,
            bg=BORDER,
            troughcolor=PANEL_ALT,
            activebackground=ACCENT,
            bd=0,
            relief="flat",
            width=10,
        )
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", entry.text_content or "")
        text.edit_reset()
        text.edit_modified(False)
        text.bind("<<Modified>>", self._on_text_modified)
        text.bind("<FocusOut>", self._flush_text_edit)
        self._text_editor = text
        self._edit_dirty = False

    # ---------------------------------------------------------- text editing
    def _on_text_modified(self, _event=None) -> None:
        editor = self._text_editor
        if editor is None:
            return
        try:
            if not editor.edit_modified():
                return
            editor.edit_modified(False)
        except tk.TclError:
            return
        self._edit_dirty = True
        self._cancel_edit_timer()
        self._edit_save_job = self.after(700, self._save_pending_edit)

    def _save_pending_edit(self) -> None:
        self._edit_save_job = None
        self._flush_text_edit()

    def _cancel_edit_timer(self) -> None:
        if self._edit_save_job is not None:
            try:
                self.after_cancel(self._edit_save_job)
            except tk.TclError:
                pass
            self._edit_save_job = None

    def _flush_text_edit(self, _event=None) -> None:
        self._cancel_edit_timer()
        if (
            not self._edit_dirty
            or self._text_editor is None
            or self._current_entry is None
        ):
            return
        try:
            text = self._text_editor.get("1.0", "end-1c")
        except tk.TclError:
            return
        self._save_text_edit(text)

    def _save_text_edit(self, text: str) -> None:
        entry = self._current_entry
        if entry is None or self.service is None:
            return
        if text == (entry.text_content or ""):
            self._edit_dirty = False
            return
        if not text.strip():
            self._edit_dirty = False
            try:
                if self._text_editor is not None:
                    self._text_editor.delete("1.0", "end")
                    self._text_editor.insert("1.0", entry.text_content or "")
                    self._text_editor.edit_modified(False)
            except tk.TclError:
                pass
            self._flash("内容不能为空，已恢复")
            return
        try:
            updated = self.service.update_entry_text(entry.id, text)
        except Exception as exc:
            self._edit_dirty = False
            log.exception("保存剪贴板文本编辑失败")
            self._flash(f"保存失败：{exc}")
            return
        self._edit_dirty = False
        if updated is None:
            self._flash("该记录不可编辑")
            return
        if updated.id != entry.id:
            self._selected_id = updated.id
            self.refresh()
            self._flash("内容与已有记录重复，已合并")
            return
        self._apply_edited_entry(updated)
        self._flash("已保存")

    def _apply_edited_entry(self, entry: ClipboardEntry) -> None:
        self._entries = [
            entry if item.id == entry.id else item for item in self._entries
        ]
        self._current_entry = entry
        self._detail_title_var.set(middle_ellipsis(entry.title, 60))
        self._detail_meta_var.set(
            format_count(entry.kind.value, entry.char_count, entry.byte_size)
        )
        self._detail_signature = self._entry_detail_signature(entry)
        labels = self._card_labels.get(entry.id)
        if labels is not None:
            labels["title"].configure(text=middle_ellipsis(entry.title, 52))
            labels["secondary"].configure(
                text=preview_text(entry.text_content or "", 90), fg=MUTED
            )
            labels["meta"].configure(
                text=format_count(
                    entry.kind.value, entry.char_count, entry.byte_size
                )
            )

    def flush_pending_edit(self) -> None:
        """Public hook used when the plugin service is about to stop."""
        try:
            self._flush_text_edit()
        except Exception:
            log.exception("刷新未保存的剪贴板文本编辑失败")

    def _preview_size(self) -> tuple[int, int]:
        try:
            width = self.detail_scroll.canvas.winfo_width()
        except tk.TclError:
            width = 0
        if width <= 1:
            width = max(320, self.winfo_width() // 3)
        max_width = max(220, width - 40)
        max_height = 360
        try:
            window_height = self.winfo_toplevel().winfo_height()
            max_height = max(180, min(380, int(window_height * 0.45)))
        except tk.TclError:
            pass
        return max_width, max_height

    @staticmethod
    def _make_preview_photo(
        source: str | Path, max_width: int, max_height: int
    ):
        with Image.open(source) as image:
            image.load()
            preview = image.copy()
        try:
            preview.thumbnail((max_width, max_height), Image.LANCZOS)
            return ImageTk.PhotoImage(preview)
        finally:
            preview.close()

    def _build_image_detail(self, parent: tk.Misc, entry: ClipboardEntry) -> None:
        full_path = self.service.image_file(entry) if self.service else None
        thumb_path = self.service.thumb_file(entry) if self.service else None
        max_width, max_height = self._preview_size()
        self._section_label(parent, "图片预览")
        wrapper = self._bordered(parent)
        wrapper.pack(fill="x", pady=(0, 4))

        photo = None
        used_thumbnail = False
        if full_path is not None:
            try:
                photo = self._make_preview_photo(
                    full_path, max_width, max_height
                )
            except Exception:
                log.warning("加载图片预览失败：%s", full_path, exc_info=True)
        if photo is None and thumb_path is not None:
            try:
                photo = self._make_preview_photo(
                    thumb_path, max_width, max_height
                )
                used_thumbnail = True
            except Exception:
                log.warning("加载图片缩略图失败：%s", thumb_path, exc_info=True)
        if photo is None:
            # Last resort: let Tk decode a PNG directly. This also keeps
            # previews working if Pillow's ImageTk helper is unavailable.
            fallback = thumb_path or full_path
            if fallback is not None:
                try:
                    photo = tk.PhotoImage(file=str(fallback))
                    used_thumbnail = fallback == thumb_path
                except tk.TclError:
                    photo = None

        if photo is not None:
            self._preview_photo = photo
            tk.Label(
                wrapper,
                image=self._preview_photo,
                bg=PANEL_ALT,
                bd=0,
            ).pack(padx=8, pady=8)
            if full_path is None or used_thumbnail:
                self._warning_label(
                    parent,
                    "原始图片文件不存在或无法读取，当前显示缩略图。",
                )
        else:
            tk.Label(
                wrapper,
                text="图片文件不存在或无法读取",
                bg=PANEL_ALT,
                fg=DANGER,
                font=self.fonts.u(10),
                pady=30,
            ).pack(fill="x")

        display_path = full_path or thumb_path
        if display_path is not None:
            self._section_label(
                parent, "图片路径" if full_path is not None else "缩略图路径"
            )
            self._build_path_rows(
                parent, [str(display_path)], entry.source_platform
            )

    def _build_files_detail(self, parent: tk.Misc, entry: ClipboardEntry) -> None:
        self._section_label(parent, "文件路径")
        self._build_path_rows(parent, list(entry.paths), entry.source_platform)

        self._section_label(parent, "预览")
        wrapper = self._bordered(parent)
        wrapper.pack(fill="x", pady=(0, 4))
        thumb = self.service.thumb_file(entry) if self.service else None
        preview_source: str | Path | None = thumb
        if preview_source is None and len(entry.paths) == 1:
            if entry.source_platform == current_platform():
                candidate = Path(entry.paths[0])
                try:
                    if (
                        candidate.is_file()
                        and candidate.stat().st_size <= 50 * 1024 * 1024
                    ):
                        preview_source = candidate
                except OSError:
                    preview_source = None

        max_width, max_height = self._preview_size()
        if preview_source is not None:
            try:
                self._thumb_photo = self._make_preview_photo(
                    preview_source, max_width, max_height
                )
                tk.Label(
                    wrapper,
                    image=self._thumb_photo,
                    bg=PANEL_ALT,
                    bd=0,
                ).pack(padx=8, pady=8)
            except Exception:
                log.warning(
                    "加载文件预览失败：%s", preview_source, exc_info=True
                )
                self._thumb_photo = None
        if self._thumb_photo is None and preview_source is not None:
            try:
                self._thumb_photo = tk.PhotoImage(
                    file=str(preview_source)
                )
            except tk.TclError:
                self._thumb_photo = None
        if self._thumb_photo is None:
            TypeBadge(wrapper, entry.kind, size=96, fonts=self.fonts).pack(
                pady=(16, 8)
            )
        name = entry.paths[0] if len(entry.paths) == 1 and entry.paths else entry.title
        tk.Label(
            wrapper,
            text=middle_ellipsis(name, 70),
            bg=PANEL_ALT,
            fg=TEXT,
            font=self.fonts.u(10, "bold"),
        ).pack(pady=(4, 2))
        tk.Label(
            wrapper,
            text=f"{len(entry.paths)} 个文件 · {format_size(entry.byte_size)}",
            bg=PANEL_ALT,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(pady=(0, 12))

        if entry.source_platform != current_platform():
            self._warning_label(
                parent,
                f"该记录来自 {platform_label(entry.source_platform)}，"
                "当前系统无法访问这些路径。",
            )
        else:
            available, missing = accessible_paths(
                entry.paths, entry.source_platform
            )
            if missing:
                preview = "\n".join(missing[:4])
                if len(missing) > 4:
                    preview += f"\n……另有 {len(missing) - 4} 个"
                self._warning_label(
                    parent,
                    f"{len(missing)} 个文件已移动或删除：\n{preview}",
                )

    def _build_path_rows(
        self, parent: tk.Misc, paths: list[str], source_platform: str
    ) -> None:
        foreign = source_platform != current_platform()
        flags = accessible_paths(paths, source_platform)
        if foreign:
            flags = [False for _ in paths]
        for path, exists in zip(paths, flags):
            row = self._bordered(parent)
            row.pack(fill="x", pady=2)
            status_text = (
                "存在"
                if exists
                else (
                    f"不可访问（{platform_label(source_platform)} 路径）"
                    if foreign
                    else "不可访问"
                )
            )
            tk.Label(
                row,
                text=status_text,
                bg=PANEL_ALT,
                fg=SUCCESS if exists else DANGER,
                font=self.fonts.u(8),
                padx=8,
                pady=6,
            ).pack(side="left")
            entry_widget = tk.Entry(
                row,
                bg=PANEL_ALT,
                fg=TEXT if exists else MUTED,
                readonlybackground=PANEL_ALT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=self.fonts.u(8),
            )
            entry_widget.insert(0, path)
            entry_widget.configure(state="readonly")
            entry_widget.pack(side="left", fill="x", expand=True, padx=4)
            FlatButton(
                row,
                "复制",
                lambda p=path: self._copy_path(p),
                fonts=self.fonts,
                font_size=8,
                padx=7,
                pady=4,
            ).pack(side="right", padx=5, pady=4)

    def _warning_label(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=BG,
            fg=DANGER,
            anchor="w",
            justify="left",
            wraplength=330,
            font=self.fonts.u(8),
        ).pack(fill="x", pady=(5, 0))

    def _build_source_card(self, parent: tk.Misc, entry: ClipboardEntry) -> None:
        self._section_label(parent, "复制来源")
        card = self._bordered(parent)
        card.pack(fill="x", pady=(0, 4))
        tk.Label(
            card,
            text=source_label(entry.source),
            bg=PANEL_ALT,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(fill="x", padx=10, pady=(8, 2))
        detail = format_time(entry.last_copied_at, detail=True)
        if entry.copy_count > 1:
            detail += f" · 共复制 {entry.copy_count} 次"
        tk.Label(
            card,
            text=detail,
            bg=PANEL_ALT,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(8),
        ).pack(fill="x", padx=10, pady=(0, 8))

    def _build_tips_card(self, parent: tk.Misc) -> None:
        self._section_label(parent, "小贴士")
        card = self._bordered(parent)
        card.pack(fill="x", pady=(0, 10))
        tips = (
            "• 支持文本、图片、文件等多种内容记录\n"
            "• 图片保存在插件数据目录，文件仅记录原始路径\n"
            "• 文件移动或删除后会显示不可访问提示\n"
            "• 关闭窗口后仍会在后台自动记录"
        )
        tk.Label(
            card,
            text=tips,
            bg=PANEL_ALT,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=self.fonts.u(8),
            padx=10,
            pady=8,
        ).pack(fill="x")

    # ---------------------------------------------------------------- actions
    def _copy_current(self) -> None:
        self._flush_text_edit()
        if self._current_entry is not None:
            self._copy_entry(self._current_entry)

    def _copy_by_id(self, entry_id: int) -> None:
        entry = next((item for item in self._entries if item.id == entry_id), None)
        if entry is not None:
            self._copy_entry(entry)

    def _copy_entry(self, entry: ClipboardEntry) -> None:
        if self.service is None:
            return
        try:
            try:
                self.service.copy_entry(entry)
            except PartialFilesError as exc:
                if not exc.available:
                    raise ClipboardError(
                        "所有文件都已移动或删除，无法复制。"
                    ) from exc
                preview = "\n".join(exc.missing[:5])
                if len(exc.missing) > 5:
                    preview += f"\n……另有 {len(exc.missing) - 5} 个"
                confirmed = messagebox.askyesno(
                    "部分文件不可访问",
                    "以下文件已移动或删除：\n\n"
                    f"{preview}\n\n仍复制其余 {len(exc.available)} 个文件？",
                    parent=self.winfo_toplevel(),
                )
                if not confirmed:
                    return
                self.service.copy_entry(entry, paths=exc.available)
        except ClipboardError as exc:
            messagebox.showerror(
                "无法复制", str(exc), parent=self.winfo_toplevel()
            )
            return
        except Exception as exc:
            log.exception("复制剪贴板记录失败")
            messagebox.showerror(
                "无法复制", str(exc), parent=self.winfo_toplevel()
            )
            return
        self._flash("已复制到剪贴板")
        self.refresh()

    def _copy_path(self, path: str) -> None:
        if self.service is None:
            return
        try:
            self.service.copy_plain_text(path)
        except Exception as exc:
            messagebox.showerror(
                "无法复制路径", str(exc), parent=self.winfo_toplevel()
            )
            return
        self._flash("路径已复制到剪贴板")

    def _reveal_current(self) -> None:
        self._flush_text_edit()
        entry = self._current_entry
        if entry is None or self.service is None:
            return
        kind = entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind)
        if kind == "text":
            return
        if kind == "files" and entry.source_platform != current_platform():
            messagebox.showerror(
                "无法打开位置",
                f"该路径来自 {platform_label(entry.source_platform)}，"
                "当前系统无法访问。",
                parent=self.winfo_toplevel(),
            )
            return
        if kind == "image":
            path = self.service.image_file(entry)
            if path is None:
                messagebox.showerror(
                    "无法打开位置",
                    "图片文件不存在。",
                    parent=self.winfo_toplevel(),
                )
                return
            target = str(path)
        else:
            available, missing = accessible_paths(
                entry.paths, entry.source_platform
            )
            if not available:
                messagebox.showerror(
                    "无法打开位置",
                    "文件已移动或删除：\n" + "\n".join(missing[:5]),
                    parent=self.winfo_toplevel(),
                )
                return
            target = available[0]
        try:
            reveal_path(target)
        except ClipboardError as exc:
            messagebox.showerror(
                "无法打开位置", str(exc), parent=self.winfo_toplevel()
            )

    def _delete_current(self) -> None:
        self._flush_text_edit()
        entry = self._current_entry
        if entry is None or self.service is None:
            return
        self._delete_entry(entry.id)

    def _delete_entry(self, entry_id: int) -> None:
        if self.service is None:
            return
        try:
            deleted = self.service.delete_entry(entry_id)
        except Exception as exc:
            messagebox.showerror(
                "无法删除", str(exc), parent=self.winfo_toplevel()
            )
            return
        if deleted:
            if self._selected_id == entry_id:
                self._selected_id = None
            self._flash("已删除该记录")
            self.refresh()

    # ------------------------------------------------------------------ search
    def _on_search_changed(self, *_args) -> None:
        self._flush_text_edit()
        if self._search_job is not None:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.after(150, lambda: self.refresh(reset_scroll=True))

    def _set_filter(self, kind: ClipboardKind | None) -> None:
        self._flush_text_edit()
        self._filter_kind = kind
        self.refresh(reset_scroll=True)

    def _open_filter_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0)
        current = {
            None: "all",
            ClipboardKind.TEXT: "text",
            ClipboardKind.IMAGE: "image",
            ClipboardKind.FILES: "files",
        }[self._filter_kind]
        variable = tk.StringVar(value=current)
        options = (
            ("all", "全部", None),
            ("text", "文本", ClipboardKind.TEXT),
            ("image", "图片", ClipboardKind.IMAGE),
            ("files", "文件", ClipboardKind.FILES),
        )
        for value, label, kind in options:
            menu.add_radiobutton(
                label=label,
                value=value,
                variable=variable,
                command=lambda k=kind: self._set_filter(k),
            )
        try:
            menu.tk_popup(
                self._filter_button.winfo_rootx(),
                self._filter_button.winfo_rooty()
                + self._filter_button.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _toggle_sort(self) -> None:
        self._flush_text_edit()
        self._newest_first = not self._newest_first
        self._sort_button.configure(
            text="↓ 最新" if self._newest_first else "↑ 最早"
        )
        self.refresh(reset_scroll=True)

    # ---------------------------------------------------------------- status
    def _update_status(self) -> None:
        if self.service is None:
            headline = "监听不可用"
            detail = self._startup_error or "剪贴板后台服务未启动"
            level = "error"
        else:
            headline, detail, level = self.service.status_text()
        self._status_headline.set(headline)
        self._status_detail.set(detail)
        color = {"ok": SUCCESS, "warn": "#d97706", "error": DANGER}[level]
        try:
            self._status_dot.itemconfigure(self._status_dot_id, fill=color)
        except tk.TclError:
            pass
        self._last_status_level = level

    def _flash(self, message: str) -> None:
        self._message_var.set(message)
        if self._flash_job is not None:
            try:
                self.after_cancel(self._flash_job)
            except tk.TclError:
                pass
        self._flash_job = self.after(2500, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash_job = None
        try:
            self._message_var.set("")
        except tk.TclError:
            pass

    def _on_service_event(self, event: str, entry_id: int | None) -> None:
        if self._detached:
            return
        if event == "edited":
            # The editor already applied this change locally; refreshing here
            # would rebuild the Text widget and steal the caret.
            return
        if event == "copied":
            self._flash("已复制到剪贴板")
        self.refresh(reset_scroll=False)

    # --------------------------------------------------------------- settings
    def _open_settings(self) -> None:
        if self.service is None:
            messagebox.showerror(
                "剪贴板不可用",
                self._startup_error or "剪贴板后台服务未启动。",
                parent=self.winfo_toplevel(),
            )
            return
        self._flush_text_edit()
        callback = self._on_open_settings
        if callback is not None:
            callback()

    # --------------------------------------------------------------- keyboard
    def _bind_keys(self) -> None:
        top = self.winfo_toplevel()
        top.bind(
            "<Control-f>", lambda _e: (self.focus_search(), "break")[1]
        )
        top.bind("<Delete>", self._on_delete_key)
        top.bind("<Return>", self._on_return_key)
        top.bind("<Escape>", lambda _e: self._close_window())

    def _typing_focus(self) -> bool:
        try:
            widget = self.focus_get()
        except (tk.TclError, AttributeError):
            return False
        if widget is None:
            return False
        return widget.winfo_class() in (
            "Entry",
            "TEntry",
            "Text",
            "Spinbox",
            "TSpinbox",
        )

    def _on_delete_key(self, _event=None):
        if self._typing_focus() or self._current_entry is None:
            return None
        self._delete_entry(self._current_entry.id)
        return "break"

    def _on_return_key(self, _event=None):
        if self._typing_focus():
            return None
        if self._current_entry is not None:
            self._copy_entry(self._current_entry)
            return "break"
        return None

    def _close_window(self) -> None:
        self._flush_text_edit()
        top = self.winfo_toplevel()
        try:
            command = top.protocol("WM_DELETE_WINDOW")
            if command:
                top.tk.call(command)
            else:
                top.destroy()
        except tk.TclError:
            pass

    def focus_search(self) -> None:
        self._flush_text_edit()
        try:
            self.search.focus()
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- cleanup
    def _bind_detail_wheel(self, widget: tk.Misc) -> None:
        if isinstance(widget, (tk.Text, tk.Entry, tk.Spinbox)):
            return
        widget.bind(
            "<Button-4>", lambda e: self.detail_scroll._on_wheel(e), add="+"
        )
        widget.bind(
            "<Button-5>", lambda e: self.detail_scroll._on_wheel(e), add="+"
        )
        widget.bind(
            "<MouseWheel>",
            lambda e: self.detail_scroll._on_wheel(e),
            add="+",
        )
        for child in widget.winfo_children():
            self._bind_detail_wheel(child)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self.detach()

    def detach(self) -> None:
        if self._detached:
            return
        try:
            self._flush_text_edit()
        except Exception:
            log.exception("窗口关闭时保存剪贴板编辑失败")
        self._cancel_edit_timer()
        self._text_editor = None
        self._edit_dirty = False
        self._detached = True
        if self.service is not None:
            self.service.remove_listener(self._listener)
        for job in (self._search_job, self._flash_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._search_job = None
        self._flash_job = None
        self._preview_photo = None
        self._thumb_photo = None
