"""Scratchpad settings dialog for the calculator plugin."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from quicktools.plugins.calculator.settings import (
    MAX_MAX_RECORDS,
    MIN_MAX_RECORDS,
)
from quicktools.ui_theme import (
    BG,
    BORDER,
    DANGER,
    MUTED,
    PANEL,
    TEXT,
    FlatButton,
    Fonts,
    center_on_screen,
    pick_fonts,
)

if TYPE_CHECKING:
    from quicktools.plugins.calculator.view import CalculatorView


class ScratchpadSettingsDialog(tk.Toplevel):
    """Modal editor for scratchpad memory limits and clear-all."""

    def __init__(self, master: tk.Misc, view: "CalculatorView") -> None:
        super().__init__(master)
        self.view = view
        self.fonts: Fonts = pick_fonts(self)
        self.title("草稿纸设置 · 快捷工具")
        self.configure(bg=BG)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.max_var = tk.StringVar(value=str(view.max_records))
        self.count_var = tk.StringVar(value="")
        self._build()
        self._refresh_count()
        self.update_idletasks()
        height = max(330, self.winfo_reqheight())
        center_on_screen(self, 480, height, parent=master)
        self.resizable(False, False)
        self.after(30, self._grab)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG, padx=20, pady=16)
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell,
            text="草稿纸设置",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(14, "bold"),
        ).pack(anchor="w")

        panel = tk.Frame(
            shell,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        panel.pack(fill="x", pady=(12, 12))

        body = tk.Frame(panel, bg=PANEL, padx=14, pady=12)
        body.pack(fill="x")
        body.grid_columnconfigure(1, weight=1)

        tk.Label(
            body,
            textvariable=self.count_var,
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.u(10),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        tk.Label(
            body,
            text="最多保存条数",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(10),
        ).grid(row=1, column=0, sticky="w", pady=(12, 0))
        spinbox = ttk.Spinbox(
            body,
            from_=MIN_MAX_RECORDS,
            to=MAX_MAX_RECORDS,
            increment=10,
            width=8,
            textvariable=self.max_var,
            font=self.fonts.u(10),
        )
        spinbox.grid(row=1, column=1, sticky="e", pady=(12, 0))
        spinbox.bind("<Return>", lambda _event: self._save())

        tk.Label(
            body,
            text=(
                "只保存非空行。调小上限会立即删除最早的记录，"
                "且无法恢复。"
            ),
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=400,
            font=self.fonts.u(9),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        tk.Label(
            shell,
            text="提示：草稿纸每行右侧的 × 可以删除单条记录。",
            bg=BG,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=self.fonts.u(9),
        ).pack(anchor="w")

        buttons = tk.Frame(shell, bg=BG)
        buttons.pack(fill="x", pady=(16, 0))
        self.clear_button = FlatButton(
            buttons,
            "清空全部记录",
            self._clear_all,
            fonts=self.fonts,
            font_size=9,
            padx=12,
            pady=7,
            fg=DANGER,
        )
        self.clear_button.pack(side="left")
        FlatButton(
            buttons,
            "保存",
            self._save,
            fonts=self.fonts,
            accent=True,
            font_size=10,
            padx=16,
            pady=8,
        ).pack(side="right")
        FlatButton(
            buttons,
            "取消",
            self.close,
            fonts=self.fonts,
            font_size=10,
            padx=16,
            pady=8,
        ).pack(side="right", padx=(0, 8))

    # -------------------------------------------------------------- actions
    def _refresh_count(self) -> None:
        count = self.view.scratchpad_record_count()
        self.count_var.set(f"当前记忆：{count} 条")
        self.clear_button.set_enabled(count > 0)

    def _save(self) -> None:
        raw = self.max_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if not (MIN_MAX_RECORDS <= value <= MAX_MAX_RECORDS):
            messagebox.showerror(
                "设置错误",
                f"最大记录数必须是 {MIN_MAX_RECORDS} 到 "
                f"{MAX_MAX_RECORDS} 之间的整数。",
                parent=self,
            )
            return
        try:
            self.view.apply_max_records(value)
        except Exception as exc:
            messagebox.showerror(
                "保存失败",
                f"无法保存草稿纸设置：{exc}",
                parent=self,
            )
            return
        self.close()
        try:
            self.view.after_idle(self.view.focus_active)
        except tk.TclError:
            pass

    def _clear_all(self) -> None:
        count = self.view.scratchpad_record_count()
        if count <= 0:
            return
        if not messagebox.askyesno(
            "清空草稿纸",
            f"确定要清空全部 {count} 条草稿记录吗？此操作无法撤销。",
            parent=self,
        ):
            return
        try:
            self.view.clear_scratchpad()
        except Exception as exc:
            messagebox.showerror(
                "清空失败",
                f"无法清空草稿纸记忆：{exc}",
                parent=self,
            )
            return
        self._refresh_count()

    # -------------------------------------------------------------- window
    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
