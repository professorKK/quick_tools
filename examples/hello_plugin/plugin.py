"""Minimal QuickTools plugin.

Copy this folder into the QuickTools user plugin directory and click
"重新扫描插件" in Settings.

The launcher already gives every plugin a frameless window with the shared
title bar (settings / pin / hide / maximize / close), so this file only builds
the content and an optional settings page.
"""

from __future__ import annotations

import json
import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.ui_theme import ACCENT, BG, MUTED, PANEL, TEXT, FlatButton


class HelloPlugin(PluginBase):
    SETTINGS_FILE = "settings.json"

    def __init__(self, context) -> None:
        super().__init__(context)
        self._counter = tk.IntVar(value=0)
        self._show_hint = self._load_show_hint()

    # --------------------------------------------------------------- helpers
    def _settings_path(self):
        return self.context.data_dir / self.SETTINGS_FILE

    def _load_show_hint(self) -> bool:
        try:
            data = json.loads(self._settings_path().read_text(encoding="utf-8"))
        except Exception:
            return True
        return bool(data.get("show_hint", True))

    def _save_show_hint(self, value: bool) -> None:
        self._settings_path().write_text(
            json.dumps({"show_hint": value}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._show_hint = value

    # ------------------------------------------------------------------- UI
    def create_ui(self, window: tk.Toplevel) -> None:
        # Do not create your own title bar or pin button: QuickTools attaches
        # the shared frame before calling create_ui().
        window.title("示例插件 · 快捷工具")
        window.geometry("420x260")
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
        self._hint_label = tk.Label(
            panel,
            text="插件由独立窗口承载，关闭启动器不会关闭这个窗口。",
            bg=PANEL,
            fg=MUTED,
            wraplength=340,
            justify="left",
        )
        self._hint_label.pack(anchor="w", pady=(8, 0))
        if not self._show_hint:
            self._hint_label.pack_forget()

        tk.Label(
            panel,
            textvariable=self._counter,
            bg=PANEL,
            fg=ACCENT,
            font=("TkDefaultFont", 16, "bold"),
        ).pack(anchor="w", pady=(16, 4))

        FlatButton(
            panel,
            "点我 +1",
            self._increment,
            font_size=10,
            padx=14,
            pady=8,
        ).pack(anchor="w")

    def create_settings_ui(self, parent: tk.Misc) -> None:
        """Optional settings page shown in the shared settings dialog."""
        tk.Label(
            parent,
            text="示例设置",
            bg=BG,
            fg=TEXT,
            font=("TkDefaultFont", 15, "bold"),
        ).pack(anchor="w")

        show_hint = tk.BooleanVar(value=self._show_hint)
        tk.Checkbutton(
            parent,
            text="在窗口中显示提示文字",
            variable=show_hint,
            bg=BG,
            fg=TEXT,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=BG,
            anchor="w",
            font=("TkDefaultFont", 10),
            highlightthickness=0,
            bd=0,
        ).pack(anchor="w", pady=(12, 0))

        status = tk.StringVar(value="")

        def save() -> None:
            self._save_show_hint(bool(show_hint.get()))
            hint = getattr(self, "_hint_label", None)
            if hint is not None:
                if self._show_hint:
                    hint.pack(anchor="w", pady=(8, 0))
                else:
                    hint.pack_forget()
            status.set("设置已保存")
            host = parent.winfo_toplevel()
            setter = getattr(host, "set_status", None)
            if callable(setter):
                setter("示例插件设置已保存")

        tk.Label(
            parent,
            textvariable=status,
            bg=BG,
            fg=ACCENT,
            font=("TkDefaultFont", 9),
        ).pack(anchor="w", pady=(12, 0))
        FlatButton(
            parent,
            "保存设置",
            save,
            accent=True,
            font_size=10,
            padx=14,
            pady=8,
        ).pack(anchor="w", pady=(10, 0))

    def _increment(self) -> None:
        self._counter.set(self._counter.get() + 1)
