"""Calculator plugin entry point."""

from __future__ import annotations

import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.plugins.calculator.view import CalculatorView
from quicktools.ui_theme import BG, center_on_screen


class CalculatorPlugin(PluginBase):
    settings_cards = True

    def __init__(self, context) -> None:
        super().__init__(context)
        self._view: CalculatorView | None = None

    def create_ui(self, window: tk.Toplevel) -> None:
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

    def create_settings_ui(self, parent: tk.Misc) -> None:
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
