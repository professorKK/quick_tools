"""Clipboard history plugin entry point."""

from __future__ import annotations

import logging
import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.ui_theme import BG, center_on_screen

from .service import ClipboardService
from .view import ClipboardView

log = logging.getLogger(__name__)


class ClipboardPlugin(PluginBase):
    settings_cards = True

    def __init__(self, context) -> None:
        super().__init__(context)
        self.service: ClipboardService | None = None
        self._startup_error = ""
        self._view: ClipboardView | None = None

    # ------------------------------------------------------------- lifecycle
    def start_service(self) -> None:
        if self.service is not None:
            return
        try:
            service = ClipboardService(self.context.data_dir, self.context.root)
            service.start()
        except Exception as exc:
            self._startup_error = str(exc) or exc.__class__.__name__
            log.exception("启动剪贴板后台服务失败")
            return
        self.service = service
        self._startup_error = ""

    def stop_service(self) -> None:
        view = self._view
        if view is not None:
            try:
                view.flush_pending_edit()
            except Exception:
                log.exception("退出前保存剪贴板编辑失败")
        service = self.service
        self.service = None
        if service is not None:
            try:
                service.stop()
            except Exception:
                log.exception("停止剪贴板后台服务失败")

    def copy_image_png(self, png: bytes) -> None:
        """Public bridge used by other built-in plugins through the launcher."""
        service = self.service
        if service is None:
            raise RuntimeError("剪贴板服务未运行")
        service.copy_image_png(png)

    # ------------------------------------------------------------------- UI
    def create_ui(self, window: tk.Toplevel) -> None:
        if self.service is None:
            self.start_service()
        window.title("剪贴板 · 快捷工具")
        window.configure(bg=BG)
        view = ClipboardView(
            window,
            self.service,
            self._startup_error,
            on_open_settings=lambda: self.open_settings(window),
        )
        view.pack(fill="both", expand=True)
        self._view = view

        window.update_idletasks()
        width = min(1240, max(980, int(window.winfo_screenwidth() * 0.9)))
        height = min(800, max(640, int(window.winfo_screenheight() * 0.88)))
        center_on_screen(window, width, height)
        window.minsize(min(980, width), min(640, height))
        window.resizable(True, True)
        window.after(60, view.focus_search)

    def create_settings_ui(self, parent: tk.Misc) -> None:
        from quicktools.settings_widgets import Card
        from quicktools.ui_theme import CARD_BG, TEXT

        from .settings_view import ClipboardSettingsPanel

        view = self._view
        if view is None:
            card = Card(parent)
            card.pack(fill="x")
            tk.Label(
                card.body,
                text="请先打开剪贴板窗口，再修改设置。",
                bg=CARD_BG,
                fg=TEXT,
                font=("TkDefaultFont", 10),
            ).pack(anchor="w")
            return
        ClipboardSettingsPanel(parent, view).pack(fill="both", expand=True)
