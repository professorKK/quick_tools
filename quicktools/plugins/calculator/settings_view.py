"""Calculator settings panel embedded in the shared plugin settings dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from quicktools.plugins.calculator.settings import (
    MAX_MAX_RECORDS,
    MAX_RESULT_GROUP_SIZE,
    MIN_MAX_RECORDS,
    MIN_RESULT_GROUP_SIZE,
)
from quicktools.settings_widgets import Card, SectionHeader, SettingsRow
from quicktools.ui_theme import (
    ACCENT,
    CARD_BG,
    DANGER,
    MUTED,
    SURFACE,
    TEXT,
    FlatButton,
    Fonts,
    pick_fonts,
)

if TYPE_CHECKING:
    from quicktools.plugins.calculator.view import CalculatorView


class CalculatorSettingsPanel(tk.Frame):
    """Settings page for scratchpad memory limits and result grouping."""

    def __init__(self, master: tk.Misc, view: "CalculatorView") -> None:
        super().__init__(master, bg=SURFACE)
        self.view = view
        self.fonts: Fonts = pick_fonts(self)
        self.max_var = tk.StringVar(value=str(view.max_records))
        self.group_var = tk.StringVar(value=str(view.result_group_size))
        self.count_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self._build()
        self._refresh_count()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        SectionHeader(
            self,
            "草稿纸记忆",
            "草稿纸会自动保存每一行表达式，重新打开计算器后恢复。",
            bg=SURFACE,
            fonts=self.fonts,
            wraplength=560,
        ).pack(fill="x", pady=(0, 10))

        card = Card(self)
        card.pack(fill="x", pady=(0, 12))
        body = card.body

        summary = tk.Frame(body, bg=CARD_BG)
        summary.pack(fill="x", pady=(0, 8))
        tk.Label(
            summary,
            text="当前记忆",
            bg=CARD_BG,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="left")
        tk.Label(
            summary,
            textvariable=self.count_var,
            bg=CARD_BG,
            fg=TEXT,
            font=self.fonts.u(10, "bold"),
        ).pack(side="left", padx=(8, 0))

        max_row = SettingsRow(
            body,
            "最多保存条数",
            description="只保存非空行；调小上限会立即删除最早的记录。",
            bg=CARD_BG,
            fonts=self.fonts,
        )
        max_row.pack(fill="x")
        spinbox = ttk.Spinbox(
            max_row.control,
            from_=MIN_MAX_RECORDS,
            to=MAX_MAX_RECORDS,
            increment=10,
            width=8,
            textvariable=self.max_var,
            font=self.fonts.u(10),
        )
        spinbox.pack()
        spinbox.bind("<Return>", lambda _event: self._save())

        group_row = SettingsRow(
            body,
            "结果分隔位数",
            description=(
                "0 表示不分隔；3 表示 1,000。仅十进制结果显示，"
                "小数只分隔整数部分。"
            ),
            bg=CARD_BG,
            fonts=self.fonts,
            last=True,
        )
        group_row.pack(fill="x")
        group_spinbox = ttk.Spinbox(
            group_row.control,
            from_=MIN_RESULT_GROUP_SIZE,
            to=MAX_RESULT_GROUP_SIZE,
            increment=1,
            width=8,
            textvariable=self.group_var,
            font=self.fonts.u(10),
        )
        group_spinbox.pack()
        group_spinbox.bind("<Return>", lambda _event: self._save())

        tk.Label(
            body,
            text="提示：草稿纸每行右侧的 × 可以删除单条记录。",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=540,
            font=self.fonts.u(8),
        ).pack(fill="x", pady=(8, 0))

        self._status_label = tk.Label(
            self,
            textvariable=self.status_var,
            bg=SURFACE,
            fg=ACCENT,
            anchor="w",
            font=self.fonts.u(9),
        )
        self._status_label.pack(fill="x", pady=(2, 0))

        buttons = tk.Frame(self, bg=SURFACE)
        buttons.pack(fill="x", pady=(12, 0))
        FlatButton(
            buttons,
            "保存设置",
            self._save,
            fonts=self.fonts,
            accent=True,
            font_size=10,
            padx=16,
            pady=8,
        ).pack(side="right")
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

    # -------------------------------------------------------------- actions
    def _refresh_count(self) -> None:
        count = self.view.scratchpad_record_count()
        self.count_var.set(f"{count} 条")
        self.clear_button.set_enabled(count > 0)

    def _status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        try:
            self._status_label.configure(fg=DANGER if error else ACCENT)
        except tk.TclError:
            pass
        host = self.winfo_toplevel()
        setter = getattr(host, "set_status", None)
        if callable(setter):
            try:
                setter(message, error=error)
            except Exception:
                pass

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
                parent=self.winfo_toplevel(),
            )
            return
        raw_group = self.group_var.get().strip()
        try:
            group_size = int(raw_group)
        except ValueError:
            group_size = -1
        if not (
            MIN_RESULT_GROUP_SIZE
            <= group_size
            <= MAX_RESULT_GROUP_SIZE
        ):
            messagebox.showerror(
                "设置错误",
                f"结果分隔位数必须是 {MIN_RESULT_GROUP_SIZE} 到 "
                f"{MAX_RESULT_GROUP_SIZE} 之间的整数（0 表示不分隔）。",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            self.view.apply_max_records(value, focus=False)
            self.view.apply_result_group_size(group_size)
        except Exception as exc:
            messagebox.showerror(
                "保存失败",
                f"无法保存计算器设置：{exc}",
                parent=self.winfo_toplevel(),
            )
            return
        self._refresh_count()
        self._status("计算器设置已保存")

    def _clear_all(self) -> None:
        count = self.view.scratchpad_record_count()
        if count <= 0:
            return
        if not messagebox.askyesno(
            "清空草稿纸",
            f"确定要清空全部 {count} 条草稿记录吗？此操作无法撤销。",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            self.view.clear_scratchpad(focus=False)
        except Exception as exc:
            messagebox.showerror(
                "清空失败",
                f"无法清空草稿纸记忆：{exc}",
                parent=self.winfo_toplevel(),
            )
            return
        self._refresh_count()
        self._status("草稿纸记录已清空")
