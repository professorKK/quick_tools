"""Clipboard settings page embedded in the shared plugin settings dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from quicktools.settings_widgets import (
    Card,
    SectionHeader,
    SettingsRow,
    ToggleRow,
)
from quicktools.ui_theme import (
    CARD_BG,
    DANGER,
    MUTED,
    SUCCESS,
    SURFACE,
    TEXT,
    FlatButton,
    Fonts,
    pick_fonts,
)

from .models import ClipboardError
from .platform_utils import open_directory

if TYPE_CHECKING:
    from .view import ClipboardView


class ClipboardSettingsPanel(tk.Frame):
    """Record filters, capacity limits and maintenance actions."""

    def __init__(self, master: tk.Misc, view: "ClipboardView") -> None:
        super().__init__(master, bg=SURFACE)
        self.view = view
        self.service = view.service
        self.fonts: Fonts = getattr(view, "fonts", None) or pick_fonts(self)
        self.status_var = tk.StringVar(value="")
        self.recording_var = tk.BooleanVar(value=False)
        self.images_var = tk.BooleanVar(value=False)
        self.files_var = tk.BooleanVar(value=False)
        self.entries_var = tk.StringVar(value="500")
        self.image_mb_var = tk.StringVar(value="200")
        self._settings = None
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        SectionHeader(
            self,
            "记录与容量",
            "控制后台监听、保存的内容类型和历史上限。修改后点击保存生效。",
            bg=SURFACE,
            fonts=self.fonts,
            wraplength=560,
        ).pack(fill="x", pady=(0, 10))

        service = self.service
        if service is None:
            card = Card(self)
            card.pack(fill="x", pady=(0, 12))
            tk.Label(
                card.body,
                text=self.view._startup_error or "剪贴板后台服务未启动。",
                bg=CARD_BG,
                fg=DANGER,
                anchor="w",
                justify="left",
                wraplength=520,
                font=self.fonts.u(10),
            ).pack(fill="x", pady=(4, 6))
            return

        self._settings = service.settings
        self.recording_var.set(self._settings.recording)
        self.images_var.set(self._settings.capture_images)
        self.files_var.set(self._settings.capture_files)
        self.entries_var.set(str(self._settings.max_entries))
        self.image_mb_var.set(str(self._settings.max_image_mb))

        card = Card(self)
        card.pack(fill="x", pady=(0, 12))
        body = card.body

        status = service.backend_status
        status_row = tk.Frame(body, bg=CARD_BG)
        status_row.pack(fill="x", pady=(0, 4))
        tk.Label(
            status_row,
            text="●",
            bg=CARD_BG,
            fg=SUCCESS if status.available else DANGER,
            font=self.fonts.u(9),
        ).pack(side="left", anchor="n", padx=(0, 7), pady=(2, 0))
        status_text = tk.Frame(status_row, bg=CARD_BG)
        status_text.pack(side="left", fill="x", expand=True)
        tk.Label(
            status_text,
            text=f"监听模式：{status.mode if status.available else status.detail}",
            bg=CARD_BG,
            fg=TEXT if status.available else DANGER,
            anchor="w",
            justify="left",
            wraplength=520,
            font=self.fonts.u(10, "bold"),
        ).pack(fill="x")
        if status.detail and status.available:
            tk.Label(
                status_text,
                text=status.detail,
                bg=CARD_BG,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=520,
                font=self.fonts.u(9),
            ).pack(fill="x", pady=(2, 0))
        if status.install_hint:
            tk.Label(
                status_text,
                text=status.install_hint,
                bg=CARD_BG,
                fg="#b45309",
                anchor="w",
                justify="left",
                wraplength=520,
                font=self.fonts.u(9),
            ).pack(fill="x", pady=(2, 0))

        tk.Frame(body, bg="#eef1f5", height=1).pack(
            fill="x", pady=(10, 2)
        )
        ToggleRow(
            body,
            "启用自动记录",
            self.recording_var,
            description="后台监听系统剪贴板，发现新内容就加入历史。",
            bg=CARD_BG,
            fonts=self.fonts,
        ).pack(fill="x")
        ToggleRow(
            body,
            "记录复制的图片",
            self.images_var,
            description="图片保存在插件数据目录，并按总容量自动清理。",
            bg=CARD_BG,
            fonts=self.fonts,
        ).pack(fill="x")
        ToggleRow(
            body,
            "记录复制的文件列表",
            self.files_var,
            description="只记录原始路径，不复制文件内容。",
            bg=CARD_BG,
            fonts=self.fonts,
            last=True,
        ).pack(fill="x")

        tk.Label(
            body,
            text="容量",
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        ).pack(fill="x", pady=(12, 2))
        entries_row = SettingsRow(
            body,
            "历史记录上限（条）",
            description="超过上限时自动删除最旧的记录。",
            bg=CARD_BG,
            fonts=self.fonts,
        )
        entries_row.pack(fill="x")
        ttk.Spinbox(
            entries_row.control,
            from_=50,
            to=5000,
            increment=50,
            width=8,
            textvariable=self.entries_var,
            font=self.fonts.u(10),
        ).pack()
        image_row = SettingsRow(
            body,
            "图片总容量上限（MB）",
            description="达到上限后先删除最旧的图片记录。",
            bg=CARD_BG,
            fonts=self.fonts,
            last=True,
        )
        image_row.pack(fill="x")
        ttk.Spinbox(
            image_row.control,
            from_=10,
            to=2000,
            increment=10,
            width=8,
            textvariable=self.image_mb_var,
            font=self.fonts.u(10),
        ).pack()

        tk.Label(
            body,
            text=(
                "X11 下需要 XFixes 支持；Wayland 需要安装 wl-clipboard，"
                "且部分合成器限制后台读取。"
            ),
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
            fg=MUTED,
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
        FlatButton(
            buttons,
            "清空全部历史",
            self._clear_history,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=8,
            fg=DANGER,
        ).pack(side="left")
        FlatButton(
            buttons,
            "打开数据目录",
            self._open_data_dir,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=8,
        ).pack(side="left", padx=(8, 0))

    # ---------------------------------------------------------------- actions
    def _status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        try:
            self._status_label.configure(fg=DANGER if error else MUTED)
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
        service = self.service
        if service is None:
            return
        try:
            max_entries = int(self.entries_var.get())
            max_image_mb = int(self.image_mb_var.get())
        except ValueError:
            messagebox.showerror(
                "设置无效",
                "容量必须是整数。",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            service.update_settings(
                recording=self.recording_var.get(),
                capture_images=self.images_var.get(),
                capture_files=self.files_var.get(),
                max_entries=max_entries,
                max_image_mb=max_image_mb,
            )
        except Exception as exc:
            messagebox.showerror(
                "保存设置失败", str(exc), parent=self.winfo_toplevel()
            )
            return
        flash = getattr(self.view, "_flash", None)
        if callable(flash):
            flash("设置已保存")
        refresh = getattr(self.view, "refresh", None)
        if callable(refresh):
            refresh()
        self._status("剪贴板设置已保存")

    def _clear_history(self) -> None:
        service = self.service
        if service is None:
            return
        if not messagebox.askyesno(
            "清空历史",
            "确定要清空全部剪贴板历史吗？此操作无法撤销。\n"
            "（不会删除任何原始文件）",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            removed = service.clear_history()
        except Exception as exc:
            messagebox.showerror(
                "清空失败", str(exc), parent=self.winfo_toplevel()
            )
            return
        if hasattr(self.view, "_selected_id"):
            self.view._selected_id = None
        flash = getattr(self.view, "_flash", None)
        if callable(flash):
            flash(f"已清空 {removed} 条记录")
        refresh = getattr(self.view, "refresh", None)
        if callable(refresh):
            refresh()
        self._status(f"已清空 {removed} 条记录")

    def _open_data_dir(self) -> None:
        service = self.service
        if service is None:
            return
        try:
            open_directory(service.data_dir)
        except ClipboardError as exc:
            messagebox.showerror(
                "无法打开目录", str(exc), parent=self.winfo_toplevel()
            )
            return
        self._status(f"已打开数据目录：{service.data_dir}")
