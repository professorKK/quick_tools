"""Calculator plugin entry point."""

from __future__ import annotations

import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.plugins.calculator.view import CalculatorView
from quicktools.ui_theme import BG, center_on_screen


class CalculatorPlugin(PluginBase):
    def create_ui(self, window: tk.Toplevel) -> None:
        window.title("计算器 · 快捷工具")
        window.configure(bg=BG)
        view = CalculatorView(window)
        view.pack(fill="both", expand=True)

        window.update_idletasks()
        width = min(620, int(window.winfo_screenwidth() * 0.9))
        height = min(
            max(view.winfo_reqheight(), 650),
            int(window.winfo_screenheight() * 0.92),
        )
        center_on_screen(window, width, height)
        window.minsize(min(520, width), min(640, height))
        window.resizable(True, True)
        window.after(60, view.focus_active)
