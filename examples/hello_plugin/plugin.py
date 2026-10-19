"""Minimal QuickTools plugin.

Copy this folder into the QuickTools user plugin directory and click
"重新扫描插件" in Settings.
"""

from __future__ import annotations

import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.ui_theme import BG, MUTED, PANEL, TEXT


class HelloPlugin(PluginBase):
    def create_ui(self, window: tk.Toplevel) -> None:
        window.title("示例插件 · 快捷工具")
        window.geometry("420x240")
        window.configure(bg=BG)

        panel = tk.Frame(window, bg=PANEL, padx=24, pady=24)
        panel.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            panel,
            text="Hello, QuickTools!",
            bg=PANEL,
            fg=TEXT,
            font=("TkDefaultFont", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            panel,
            text="插件由独立窗口承载，关闭启动器不会关闭这个窗口。",
            bg=PANEL,
            fg=MUTED,
            wraplength=340,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        counter = tk.IntVar(value=0)
        label = tk.Label(panel, textvariable=counter, bg=PANEL, fg=TEXT)
        label.pack(anchor="w", pady=(16, 4))

        def increment() -> None:
            counter.set(counter.get() + 1)

        tk.Button(panel, text="点我 +1", command=increment).pack(anchor="w")
