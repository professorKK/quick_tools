"""Shared settings and about dialog for every QuickTools plugin.

The dialog is deliberately owned by the framework, not by individual plugins:
it provides the title bar, the navigation, an automatically generated About
page and a consistent card-based look. Plugins only fill the settings page
via ``PluginBase.create_settings_ui(parent)``.
"""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable

from .logging_setup import get_logger
from .plugin_api import PluginBase, PluginMeta
from .settings_widgets import (
    Card,
    IconBadge,
    NavItem,
    SectionHeader,
)
from .ui_theme import (
    ACCENT,
    CARD_BG,
    CARD_BORDER,
    DANGER,
    DIVIDER,
    MUTED,
    SURFACE,
    TEXT,
    FlatButton,
    Fonts,
    center_on_screen,
    open_in_file_manager,
    pick_fonts,
)
from .window_frame import WindowFrame

log = get_logger(__name__)

_ABOUT_WRAP = 500


class ScrollableFrame(tk.Frame):
    """A themed vertical scroller used by the settings/about pages."""

    def __init__(self, master: tk.Misc, *, background: str = SURFACE) -> None:
        super().__init__(master, bg=background)
        self.background = background
        self.canvas = tk.Canvas(
            self,
            bg=background,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            bg=CARD_BORDER,
            troughcolor=background,
            activebackground=ACCENT,
            bd=0,
            relief="flat",
            width=9,
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self._scrollbar_visible = True
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=background)
        self._window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_wheel(self.canvas)

    def _on_inner_configure(self, _event=None) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)
        self._sync_scrollbar()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        """Keep the scrollbar out of the layout when the page fits."""
        try:
            bbox = self.canvas.bbox("all")
            needed = bool(bbox and bbox[3] > self.canvas.winfo_height() + 2)
            if needed and not self._scrollbar_visible:
                self.scrollbar.pack(
                    side="right", fill="y", before=self.canvas
                )
                self._scrollbar_visible = True
            elif not needed and self._scrollbar_visible:
                self.scrollbar.pack_forget()
                self._scrollbar_visible = False
        except tk.TclError:
            pass

    def bind_wheel(self, widget: tk.Misc | None = None) -> None:
        target = widget or self.inner
        target.bind("<Button-4>", self._on_wheel, add="+")
        target.bind("<Button-5>", self._on_wheel, add="+")
        target.bind("<MouseWheel>", self._on_wheel, add="+")
        for child in target.winfo_children():
            if isinstance(
                child,
                (
                    tk.Spinbox,
                    tk.Entry,
                    tk.Text,
                    ttk.Entry,
                    ttk.Spinbox,
                    ttk.Combobox,
                ),
            ):
                continue
            self.bind_wheel(child)

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            units = -3 if getattr(event, "delta", 0) > 0 else 3
        self.canvas.yview_scroll(units, "units")
        return "break"


class AboutPage(tk.Frame):
    """Automatically generated plugin information page."""

    def __init__(
        self,
        master: tk.Misc,
        meta: PluginMeta,
        fonts: Fonts,
        *,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, bg=SURFACE)
        self.meta = meta
        self.fonts = fonts
        self._on_status = on_status
        self._data_dir: Path | None = None
        scroll = ScrollableFrame(self, background=SURFACE)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        body.grid_columnconfigure(0, weight=1)

        hero = Card(body)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        hero_body = hero.body
        header = tk.Frame(hero_body, bg=CARD_BG)
        header.pack(fill="x")
        badge = IconBadge(
            header, meta.display_icon, size=54, fonts=fonts
        )
        badge.pack(side="left", padx=(0, 14))
        titles = tk.Frame(header, bg=CARD_BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text=meta.name,
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=fonts.u(19, "bold"),
        ).pack(fill="x")
        kind = "内置插件" if meta.builtin else "用户插件"
        author = f" · {meta.author}" if meta.author else ""
        tk.Label(
            titles,
            text=f"版本 {meta.version} · {kind}{author}",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            font=fonts.u(9),
        ).pack(fill="x", pady=(3, 0))

        summary = meta.display_summary
        if summary:
            summary_label = tk.Label(
                hero_body,
                text=summary,
                bg=CARD_BG,
                fg=TEXT,
                anchor="w",
                justify="left",
                wraplength=_ABOUT_WRAP,
                font=fonts.u(10),
            )
            summary_label.pack(fill="x", pady=(14, 0))
            self._auto_wrap(summary_label, hero_body)

        description_card = Card(body)
        description_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        description_body = description_card.body
        SectionHeader(
            description_body, "插件说明", fonts=fonts
        ).pack(fill="x", pady=(0, 8))
        description = (meta.description or "").strip()
        description_label = tk.Label(
            description_body,
            text=description or "这个插件还没有填写详细说明。",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=_ABOUT_WRAP,
            font=fonts.u(9),
        )
        description_label.pack(fill="x")
        self._auto_wrap(description_label, description_body)

        info_card = Card(body)
        info_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        info_body = info_card.body
        SectionHeader(info_body, "插件信息", fonts=fonts).pack(
            fill="x", pady=(0, 2)
        )
        self._info_row(info_body, "插件 ID", meta.id)
        self._info_row(info_body, "版本", meta.version)
        self._info_row(info_body, "类型", kind)
        self._info_row(info_body, "作者", meta.author or "未提供")
        self._info_row(info_body, "插件目录", str(meta.folder))
        self._data_dir_label = self._info_row(
            info_body, "数据目录", "", last=True
        )

        buttons = tk.Frame(body, bg=SURFACE)
        buttons.grid(row=3, column=0, sticky="w", pady=(0, 18))
        FlatButton(
            buttons,
            "打开插件目录",
            self._open_plugin_dir,
            fonts=fonts,
            font_size=9,
            padx=12,
            pady=7,
        ).pack(side="left", padx=(0, 8))
        FlatButton(
            buttons,
            "打开数据目录",
            self._open_data_dir,
            fonts=fonts,
            font_size=9,
            padx=12,
            pady=7,
        ).pack(side="left", padx=(0, 8))
        FlatButton(
            buttons,
            "复制插件信息",
            self._copy_info,
            fonts=fonts,
            font_size=9,
            padx=12,
            pady=7,
        ).pack(side="left")
        self.set_data_dir("")
        scroll.bind_wheel()

    # --------------------------------------------------------------- paint
    def _info_row(
        self,
        parent: tk.Misc,
        label: str,
        value: str,
        *,
        last: bool = False,
    ) -> tk.Label:
        row = tk.Frame(parent, bg=CARD_BG)
        row.pack(fill="x", pady=(8, 8 if last else 7))
        tk.Label(
            row,
            text=label,
            bg=CARD_BG,
            fg=MUTED,
            width=10,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(side="left", anchor="n")
        value_label = tk.Label(
            row,
            text=value,
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            justify="left",
            wraplength=_ABOUT_WRAP - 100,
            font=self.fonts.u(9),
        )
        value_label.pack(side="left", fill="x", expand=True)
        self._auto_wrap(value_label, parent, extra=110)
        if not last:
            tk.Frame(parent, bg=DIVIDER, height=1).pack(fill="x")
        return value_label

    def _auto_wrap(
        self, label: tk.Label, container: tk.Misc, *, extra: int = 0
    ) -> None:
        def update(event: tk.Event) -> None:
            try:
                label.configure(
                    wraplength=max(180, event.width - 40 - extra)
                )
            except tk.TclError:
                pass

        container.bind("<Configure>", update, add="+")

    # ------------------------------------------------------------- actions
    def _plugin_data_dir(self) -> Path | None:
        return self._data_dir

    def set_data_dir(self, path: Path | str) -> None:
        self._data_dir = Path(path) if str(path) else None
        try:
            self._data_dir_label.configure(
                text=str(self._data_dir) if self._data_dir else "未提供"
            )
        except tk.TclError:
            pass

    def _open_plugin_dir(self) -> None:
        try:
            open_in_file_manager(self.meta.folder)
            self._status(f"已打开插件目录：{self.meta.folder}")
        except Exception as exc:
            self._status(f"无法打开插件目录：{exc}")

    def _open_data_dir(self) -> None:
        path = self._plugin_data_dir()
        if path is None:
            self._status("该插件没有提供数据目录")
            return
        try:
            open_in_file_manager(path)
            self._status(f"已打开数据目录：{path}")
        except Exception as exc:
            self._status(f"无法打开数据目录：{exc}")

    def _copy_info(self) -> None:
        text = (
            f"{self.meta.name} {self.meta.version}\n"
            f"ID：{self.meta.id}\n"
            f"目录：{self.meta.folder}\n"
        )
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._status("插件信息已复制到剪贴板")
        except tk.TclError:
            self._status("复制失败")

    def _status(self, message: str) -> None:
        if self._on_status is not None:
            self._on_status(message)


class PluginSettingsDialog(tk.Toplevel):
    """Framework-owned settings shell with settings and about pages."""

    def __init__(
        self,
        master: tk.Misc,
        meta: PluginMeta,
        fonts: Fonts | None = None,
        *,
        builder: Callable[[tk.Misc], None] | None = None,
        builder_cards: bool = False,
        data_dir: Path | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.meta = meta
        self.fonts = fonts or pick_fonts(self)
        self._builder = builder
        self._builder_cards = builder_cards
        self._data_dir = data_dir
        self._on_close = on_close
        self._closed = False
        self._status_job: str | None = None
        self.current_page = "settings"

        self.title(f"{meta.name} · 设置 · 快捷工具")
        self.configure(bg=SURFACE)
        self.minsize(700, 560)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.frame = WindowFrame(
            self,
            title=f"{meta.name} · 设置",
            subtitle="设置与关于",
            icon=meta.display_icon,
            fonts=self.fonts,
            dialog=True,
            pin=False,
            minimize=False,
            maximize=False,
            resizable=True,
            on_close=self.close,
        )
        self._build()
        self.show_page("settings")
        self.update_idletasks()
        center_on_screen(self, 840, 690, parent=master)
        self.after(30, self._grab)

    # --------------------------------------------------------------- build
    def _build(self) -> None:
        shell = tk.Frame(self, bg=SURFACE)
        shell.pack(fill="both", expand=True)

        sidebar_holder = tk.Frame(shell, bg=SURFACE, width=204)
        sidebar_holder.pack(side="left", fill="y")
        sidebar_holder.pack_propagate(False)
        sidebar_card = Card(sidebar_holder, padding=(12, 14))
        sidebar_card.pack(
            fill="both", expand=True, padx=(16, 0), pady=16
        )
        sidebar = sidebar_card.body

        brand = tk.Frame(sidebar, bg=CARD_BG)
        brand.pack(fill="x", pady=(0, 12))
        IconBadge(
            brand,
            self.meta.display_icon,
            size=38,
            background=CARD_BG,
            fonts=self.fonts,
        ).pack(side="left", padx=(2, 9))
        brand_text = tk.Frame(brand, bg=CARD_BG)
        brand_text.pack(side="left", fill="x", expand=True)
        tk.Label(
            brand_text,
            text=self.meta.name,
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(12, "bold"),
        ).pack(fill="x")
        tk.Label(
            brand_text,
            text=f"v{self.meta.version}",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(8),
        ).pack(fill="x", pady=(2, 0))

        tk.Frame(sidebar, bg=DIVIDER, height=1).pack(
            fill="x", pady=(0, 10)
        )
        tk.Label(
            sidebar,
            text="插件设置",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(8),
        ).pack(fill="x", padx=(11, 0), pady=(0, 6))

        self._nav: dict[str, NavItem] = {}
        for name, label, kind in (
            ("settings", "设置", "settings"),
            ("about", "关于", "about"),
        ):
            item = NavItem(
                sidebar,
                label,
                kind,
                lambda page=name: self.show_page(page),
                fonts=self.fonts,
            )
            item.pack(fill="x", pady=(0, 2))
            self._nav[name] = item

        tk.Frame(sidebar, bg=CARD_BG).pack(fill="both", expand=True)
        tk.Label(
            sidebar,
            text="快捷工具",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(8),
        ).pack(fill="x", padx=(11, 0))

        content = tk.Frame(shell, bg=SURFACE)
        content.pack(
            side="left", fill="both", expand=True, padx=(16, 18), pady=16
        )
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        header = tk.Frame(content, bg=SURFACE)
        header.grid(row=0, column=0, sticky="ew")
        self._page_title = tk.StringVar(value="设置")
        self._page_subtitle = tk.StringVar(value="")
        tk.Label(
            header,
            textvariable=self._page_title,
            bg=SURFACE,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(20, "bold"),
        ).pack(fill="x")
        tk.Label(
            header,
            textvariable=self._page_subtitle,
            bg=SURFACE,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(fill="x", pady=(3, 0))

        self.page_container = tk.Frame(content, bg=SURFACE)
        self.page_container.grid(
            row=1, column=0, sticky="nsew", pady=(12, 0)
        )
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)

        self._settings_scroll = ScrollableFrame(
            self.page_container, background=SURFACE
        )
        self._settings_scroll.grid(row=0, column=0, sticky="nsew")
        self.settings_body = self._settings_scroll.inner
        self.about_page = AboutPage(
            self.page_container,
            self.meta,
            self.fonts,
            on_status=self.set_status,
        )
        self.about_page.grid(row=0, column=0, sticky="nsew")
        if self._data_dir is not None:
            self.about_page.set_data_dir(self._data_dir)
        self._build_settings_page()

        footer = tk.Frame(content, bg=SURFACE)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        tk.Frame(footer, bg=CARD_BORDER, height=1).pack(
            fill="x", pady=(0, 9)
        )
        footer_row = tk.Frame(footer, bg=SURFACE)
        footer_row.pack(fill="x")
        self._status_var = tk.StringVar(value="")
        self._status_label = tk.Label(
            footer_row,
            textvariable=self._status_var,
            bg=SURFACE,
            fg=MUTED,
            anchor="w",
            justify="left",
            font=self.fonts.u(9),
        )
        self._status_label.pack(side="left", fill="x", expand=True)
        FlatButton(
            footer_row,
            "关闭",
            self.close,
            fonts=self.fonts,
            font_size=10,
            padx=18,
            pady=8,
        ).pack(side="right")

    def _build_settings_page(self) -> None:
        page = tk.Frame(self.settings_body, bg=SURFACE)
        page.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 2))
        if self._builder is None:
            card = Card(page)
            card.pack(fill="x")
            self._show_empty_state(card.body)
            self._settings_scroll.bind_wheel()
            return

        body: tk.Misc
        if self._builder_cards:
            # Built-in plugins lay out their own card groups so sections keep
            # a clear hierarchy; no extra card is wrapped around the page.
            body = page
        else:
            card = Card(page)
            card.pack(fill="x")
            body = card.body
        try:
            self._builder(body)
        except Exception:
            log.exception("构建插件设置页失败：%s", self.meta.id)
            tk.Label(
                page,
                text="设置页加载失败，请查看日志。",
                bg=SURFACE,
                fg=DANGER,
                font=self.fonts.u(10),
            ).pack(anchor="w", pady=(20, 0))
        self._settings_scroll.bind_wheel()

    def _show_empty_state(self, body: tk.Misc) -> None:
        tk.Label(
            body,
            text="这个插件没有可配置的选项",
            bg=CARD_BG,
            fg=TEXT,
            font=self.fonts.u(13, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body,
            text="你仍然可以在“关于”页查看插件版本、说明和文件位置。",
            bg=CARD_BG,
            fg=MUTED,
            justify="left",
            wraplength=460,
            font=self.fonts.u(9),
        ).pack(anchor="w", pady=(6, 0))

    # -------------------------------------------------------------- pages
    def show_page(self, name: str) -> None:
        if name not in self._nav:
            name = "settings"
        self.current_page = name
        if name == "settings":
            self._page_title.set("设置")
            self._page_subtitle.set(
                f"调整{self.meta.name}的偏好设置，保存后立即生效。"
            )
            widget = self._settings_scroll
        else:
            self._page_title.set("关于")
            self._page_subtitle.set("版本信息、详细说明和文件位置。")
            widget = self.about_page
        widget.tkraise()
        for key, button in self._nav.items():
            button.set_active(key == name)

    # ------------------------------------------------------------ feedback
    def set_status(self, message: str, *, error: bool = False) -> None:
        try:
            self._status_var.set(message)
            self._status_label.configure(fg=DANGER if error else MUTED)
        except tk.TclError:
            return
        job = self._status_job
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        try:
            self._status_job = self.after(4000, self._clear_status)
        except tk.TclError:
            self._status_job = None

    def _clear_status(self) -> None:
        self._status_job = None
        try:
            self._status_var.set("")
        except tk.TclError:
            pass

    # --------------------------------------------------------------- close
    def _grab(self) -> None:
        try:
            self.lift()
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._status_job is not None:
            try:
                self.after_cancel(self._status_job)
            except tk.TclError:
                pass
            self._status_job = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                log.exception("关闭插件设置对话框失败")
        try:
            self.destroy()
        except tk.TclError:
            pass


def _meta_from_manifest(folder: Path, plugin_id: str) -> PluginMeta | None:
    manifest = folder / "plugin.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return PluginMeta(
        id=str(raw.get("id") or plugin_id),
        name=str(raw.get("name") or plugin_id),
        description=str(raw.get("description") or ""),
        version=str(raw.get("version") or "0.0.0"),
        entry=str(raw.get("entry") or "plugin.py"),
        class_name=str(raw.get("class") or ""),
        folder=folder,
        icon=str(raw.get("icon") or "◆"),
        order=100,
        builtin=False,
        background=raw.get("background") is True,
        summary=str(raw.get("summary") or ""),
        author=str(raw.get("author") or ""),
    )


def open_plugin_settings(
    plugin: PluginBase,
    master: Any = None,
    *,
    page: str = "settings",
) -> bool:
    """Open (or focus) the shared settings/about dialog for ``plugin``."""
    context = getattr(plugin, "context", None)
    if context is None:
        return False
    meta = getattr(context, "meta", None)
    if meta is None:
        meta = _meta_from_manifest(
            Path(context.plugin_dir), str(context.plugin_id)
        )
    if meta is None:
        return False

    existing = getattr(plugin, "_settings_dialog", None)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.show_page(page)
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return True
        except tk.TclError:
            pass

    if master is None:
        master = getattr(context, "root", None)
    if not isinstance(master, tk.Misc):
        master = getattr(context, "root", None)
    elif not isinstance(master, (tk.Tk, tk.Toplevel)):
        try:
            master = master.winfo_toplevel()
        except tk.TclError:
            master = getattr(context, "root", None)
    if not isinstance(master, tk.Misc):
        return False

    builder: Callable[[tk.Misc], None] | None = None
    method = getattr(plugin, "create_settings_ui", None)
    if (
        callable(method)
        and type(plugin).create_settings_ui
        is not PluginBase.create_settings_ui
    ):
        builder = method

    def clear_reference() -> None:
        if getattr(plugin, "_settings_dialog", None) is dialog:
            plugin._settings_dialog = None

    dialog = PluginSettingsDialog(
        master,
        meta,
        pick_fonts(master),
        builder=builder,
        builder_cards=bool(getattr(plugin, "settings_cards", False)),
        data_dir=getattr(context, "data_dir", None),
        on_close=clear_reference,
    )
    plugin._settings_dialog = dialog
    dialog.show_page(page)
    return True
