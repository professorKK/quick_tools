"""Calculator plugin entry point."""

from __future__ import annotations

import logging
import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.plugins.calculator.qt_host import (
    ExternalCalculatorWindow,
    qt_available,
)
from quicktools.plugins.calculator.view import CalculatorView
from quicktools.ui_theme import BG, center_on_screen

log = logging.getLogger(__name__)


class CalculatorPlugin(PluginBase):
    settings_cards = True

    def __init__(self, context) -> None:
        super().__init__(context)
        self._view: CalculatorView | None = None
        self._external: ExternalCalculatorWindow | None = None

    def create_ui(self, window: tk.Toplevel) -> None:
        if qt_available():
            external = ExternalCalculatorWindow(
                window,
                self.context.data_dir,
                on_failure=lambda: self._fallback_to_tk(window),
            )
            try:
                started = external.start()
            except Exception:
                log.exception("启动 PyQt 计算器界面失败，回退到 Tk")
                try:
                    external.close()
                except Exception:
                    pass
                started = False
            if started:
                self._external = external
                log.info("计算器使用 PyQt 独立窗口")
                return
            external._restore_host()
        self._create_tk_ui(window)

    def _fallback_to_tk(self, window: tk.Toplevel) -> None:
        if self._view is not None:
            return
        self._external = None
        log.warning("PyQt 计算器不可用，回退到 Tk 界面")
        self._create_tk_ui(window)
        try:
            window.deiconify()
            window.lift()
            window.focus_force()
        except tk.TclError:
            pass

    def _create_tk_ui(self, window: tk.Toplevel) -> None:
        window.title("计算器 · 快捷工具")
        window.configure(bg=BG)
        view = CalculatorView(
            window,
            data_dir=self.context.data_dir,
            on_open_settings=lambda: self.open_settings(window),
        )
        view.pack(fill="both", expand=True)
        self._view = view

        window.update_idletasks()
        width = min(620, int(window.winfo_screenwidth() * 0.9))
        height = min(
            max(view.winfo_reqheight(), 650),
            int(window.winfo_screenheight() * 0.92),
        )
        center_on_screen(window, width, height)
        # The window can shrink until the paper shows a single layer and the
        # keypad is at its compact row height; anything smaller would clip.
        min_height = min(view.minimum_window_height(), height)
        window.minsize(min(520, width), min_height)
        window.resizable(True, True)
        window.after(60, view.focus_active)

    def on_window_shown(self, window: tk.Toplevel) -> None:
        # The launcher hides plugin windows instead of destroying them, so a
        # re-entry would otherwise keep the caret and active row from the last
        # visit. Always offer a fresh input row while keeping the history.
        if self._external is not None:
            self._external.show()
            return
        if self._view is not None:
            self._view.begin_new_entry()

    def create_settings_ui(self, parent: tk.Misc) -> None:
        if self._external is not None:
            from quicktools.settings_widgets import Card
            from quicktools.ui_theme import CARD_BG, TEXT

            card = Card(parent)
            card.pack(fill="x")
            tk.Label(
                card.body,
                text="计算器使用独立的 PyQt 窗口，请在计算器窗口顶部的齿轮按钮中打开设置。",
                bg=CARD_BG,
                fg=TEXT,
                font=("TkDefaultFont", 10),
                wraplength=420,
                justify="left",
            ).pack(anchor="w")
            return

        from quicktools.plugins.calculator.settings_view import (
            CalculatorSettingsPanel,
        )
        from quicktools.settings_widgets import Card
        from quicktools.ui_theme import CARD_BG, TEXT

        view = self._view
        if view is None:
            card = Card(parent)
            card.pack(fill="x")
            tk.Label(
                card.body,
                text="请先打开计算器，再修改设置。",
                bg=CARD_BG,
                fg=TEXT,
                font=("TkDefaultFont", 10),
            ).pack(anchor="w")
            return
        CalculatorSettingsPanel(parent, view).pack(fill="both", expand=True)
