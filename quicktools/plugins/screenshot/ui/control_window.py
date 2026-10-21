"""Main control window for the screenshot plugin."""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    DANGER,
    MUTED,
    PANEL,
    TEXT,
    pick_fonts,
)

from .about_page import AboutPage
from .home_page import HomePage
from .icons import IconSet
from .widgets import NavItem, bind_click_recursive

if TYPE_CHECKING:
    from ..plugin import ScreenshotPlugin


class ControlWindow(tk.Frame):
    def __init__(self, master: tk.Misc, plugin: "ScreenshotPlugin") -> None:
        super().__init__(master, bg=BG)
        self.plugin = plugin
        self.fonts = pick_fonts(master)
        self.icons = IconSet(self)
        self.status_var = tk.StringVar(value=plugin.status_text())
        self._hotkey_var = tk.StringVar()
        self._save_dir_var = tk.StringVar()
        self._toast_label: tk.Label | None = None
        self._toast_job: str | None = None
        self.current_page = "home"
        self.pages: dict[str, tk.Frame] = {}
        self._nav_items: dict[str, NavItem] = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_content()

        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh_settings()
        self.show_page("home")
        self.update_idletasks()
        fixed = self.home_page.fixed_height()
        fixed += self.footer.winfo_reqheight()
        fixed += self._status_label.winfo_reqheight() + 32
        self.recommended_min_height = max(720, fixed + 230)

    # -------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> None:
        self.sidebar = tk.Frame(
            self,
            bg=BG,
            width=176,
            padx=10,
            pady=14,
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.grid_columnconfigure(0, minsize=176)

        brand = tk.Frame(self.sidebar, bg=BG)
        brand.pack(fill="x", pady=(0, 16))
        tk.Label(
            brand,
            bg=BG,
            image=self.icons.tile(
                "camera", size=34, bg="#e8f0fe", fg=ACCENT, radius=9
            ),
        ).pack(side="left", padx=(2, 8))
        tk.Label(
            brand,
            text="截图助手",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(12, "bold"),
        ).pack(side="left")

        home = NavItem(
            self.sidebar,
            "首页",
            "home",
            self.icons,
            self.fonts,
            lambda: self.show_page("home"),
            active=True,
        )
        home.pack(fill="x", pady=(0, 4))
        about = NavItem(
            self.sidebar,
            "关于",
            "info",
            self.icons,
            self.fonts,
            lambda: self.show_page("about"),
        )
        about.pack(fill="x")
        self._nav_items = {"home": home, "about": about}

        tk.Frame(self.sidebar, bg=BG).pack(fill="both", expand=True)
        NavItem(
            self.sidebar,
            "设置",
            "gear",
            self.icons,
            self.fonts,
            self._open_settings,
        ).pack(fill="x")

    # -------------------------------------------------------------- content
    def _build_content(self) -> None:
        self.content = tk.Frame(self, bg=BG, padx=22, pady=16)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.page_container = tk.Frame(self.content, bg=BG)
        self.page_container.grid(row=0, column=0, sticky="nsew")
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)

        self.home_page = HomePage(
            self.page_container,
            self.plugin,
            self.fonts,
            self.icons,
            on_toast=self.show_toast,
        )
        self.about_page = AboutPage(
            self.page_container,
            self.plugin,
            self.fonts,
            self.icons,
            on_open_settings=self._open_settings,
        )
        self.pages = {"home": self.home_page, "about": self.about_page}
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.recent_view = self.home_page.recent_view

        self.footer = tk.Frame(self.content, bg=BG)
        self.footer.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tk.Frame(self.footer, bg=BORDER, height=1).pack(
            fill="x", pady=(0, 8)
        )
        footer_row = tk.Frame(self.footer, bg=BG)
        footer_row.pack(fill="x")
        tk.Label(
            footer_row,
            textvariable=self._hotkey_var,
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="left")
        save = tk.Frame(footer_row, bg=BG, cursor="hand2")
        save.pack(side="left", fill="x", expand=True, padx=(20, 0))
        tk.Label(
            save,
            bg=BG,
            image=self.icons.get("folder", 14, MUTED),
        ).pack(side="left", padx=(0, 5))
        tk.Label(
            save,
            textvariable=self._save_dir_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(9),
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True)
        bind_click_recursive(save, lambda _event: self.plugin.open_save_folder())

        self._status_label = tk.Label(
            self.content,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=780,
            font=self.fonts.u(9),
        )
        self._status_label.grid(row=2, column=0, sticky="ew", pady=(6, 0))

    # --------------------------------------------------------------- pages
    def show_page(self, name: str) -> None:
        page = self.pages.get(name)
        if page is None:
            return
        page.tkraise()
        if self._toast_label is not None:
            self._toast_label.lift()
        self.current_page = name
        for key, item in self._nav_items.items():
            item.set_active(key == name)
        if name == "about":
            self.about_page.refresh()

    def refresh_settings(self) -> None:
        settings = self.plugin.settings
        if settings.hotkey_enabled:
            self._hotkey_var.set(f"快捷键：{settings.hotkey.display()}")
        else:
            self._hotkey_var.set("快捷键：未启用")
        self._save_dir_var.set(
            f"保存目录：{settings.resolved_save_dir()}"
        )
        about = getattr(self, "about_page", None)
        if about is not None:
            about.refresh()
        home = getattr(self, "home_page", None)
        if home is not None:
            home.refresh_hotkeys()

    def on_show(self) -> None:
        self.refresh_settings()
        view = getattr(self, "recent_view", None)
        if view is not None:
            view.refresh()
        self.status_var.set(self.plugin.status_text())

    # ---------------------------------------------------------------- toast
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
        self._toast_label = tk.Label(
            self.page_container,
            text=message,
            bg=DANGER if error else PANEL,
            fg="#ffffff" if error else TEXT,
            padx=16,
            pady=8,
            font=self.fonts.u(10, "bold"),
            image=self.icons.get(
                "warning" if error else "check",
                15,
                "#ffffff" if error else "#15803d",
            ),
            compound="left",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self._toast_label.place(
            relx=1.0, rely=1.0, x=-18, y=-12, anchor="se"
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

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._toast_job is not None:
            try:
                self.after_cancel(self._toast_job)
            except tk.TclError:
                pass
            self._toast_job = None

    # -------------------------------------------------------------- actions
    def _open_settings(self) -> None:
        opener = getattr(self.plugin, "open_settings", None)
        if callable(opener):
            opener(self.winfo_toplevel())

    def set_status(self, message: str) -> None:
        self.status_var.set(message)
