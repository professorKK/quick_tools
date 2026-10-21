"""About page for the screenshot plugin."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    BUTTON,
    FlatButton,
    MUTED,
    PANEL,
    TEXT,
    Fonts,
)
from quicktools.window_pin import PinButton

from ..shortcuts import shortcut_labels
from .icons import IconSet
from .widgets import ScrollableFrame

if TYPE_CHECKING:
    from ..plugin import ScreenshotPlugin


def _plugin_version() -> str:
    manifest = Path(__file__).resolve().parent.parent / "plugin.json"
    try:
        with manifest.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return str(data.get("version") or "0.1.0")
    except Exception:
        return "0.1.0"


class AboutPage(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        plugin: "ScreenshotPlugin",
        fonts: Fonts,
        icons: IconSet,
        *,
        on_open_settings: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=BG)
        self.plugin = plugin
        self.fonts = fonts
        self.icons = icons
        self._on_open_settings = on_open_settings
        self._hotkey_var = tk.StringVar()
        self._save_dir_var = tk.StringVar()
        self._data_dir_var = tk.StringVar()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        scroll = ScrollableFrame(self, background=BG, scrollbar_bg=BG)
        scroll.grid(row=0, column=0, sticky="nsew")
        body = scroll.inner
        body.grid_columnconfigure(0, weight=1)

        header = tk.Frame(body, bg=BG)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.pin_button = PinButton(
            header, self.winfo_toplevel(), fonts
        )
        self.pin_button.pack(side="right")
        tk.Label(
            header,
            bg=BG,
            image=icons.tile(
                "camera", size=46, bg="#e8f0fe", fg=ACCENT, radius=12
            ),
        ).pack(side="left", padx=(0, 12))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text="关于截图助手",
            bg=BG,
            fg=TEXT,
            font=fonts.u(18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            titles,
            text=f"版本 {_plugin_version()} · 本地截图与标注工具",
            bg=BG,
            fg=MUTED,
            font=fonts.u(9),
        ).pack(anchor="w", pady=(3, 0))

        tk.Label(
            body,
            text=(
                "截图助手提供矩形、窗口、自由和滚动截图，并支持完整的标注编辑。"
                "所有截图和标注都在本机处理，不会上传到任何服务器。"
            ),
            bg=BG,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=700,
            font=fonts.u(10),
        ).grid(row=1, column=0, sticky="ew", pady=(0, 14))

        self._section(
            body,
            row=2,
            title="主要能力",
            lines=(
                "• 矩形、窗口、自由套索和滚动长截图",
                "• 矩形/圆形圈选、箭头、文字、序号、马赛克、贴纸、水印",
                "• 裁剪、套索裁剪、旋转、翻转、撤销/重做",
                "• 最近截图支持搜索、筛选、收藏、复制和再次编辑",
            ),
        )

        shortcut_panel = self._panel(body, row=3, title="快捷键")
        self._info_row(
            shortcut_panel, "主截图快捷键", self._hotkey_var
        )
        label_map = shortcut_labels()
        for action, label in (
            ("capture_region", "矩形截图"),
            ("capture_window", "窗口截图"),
            ("capture_freeform", "自由截图"),
            ("capture_scroll", "滚动截图"),
        ):
            value = label_map.get(action, "")
            row = tk.Frame(shortcut_panel, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=label,
                bg=PANEL,
                fg=MUTED,
                width=12,
                anchor="w",
                font=self.fonts.u(9),
            ).pack(side="left")
            tk.Label(
                row,
                text=value,
                bg=PANEL,
                fg=TEXT,
                anchor="w",
                font=self.fonts.m(9),
            ).pack(side="left")
        tk.Label(
            shortcut_panel,
            text="Wayland 会话不支持应用内全局快捷键，请在系统中绑定 quicktools --screenshot 命令。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=640,
            font=self.fonts.u(8),
        ).pack(fill="x", pady=(6, 0))

        paths_panel = self._panel(body, row=4, title="文件位置")
        self._info_row(paths_panel, "保存目录", self._save_dir_var)
        self._info_row(paths_panel, "数据目录", self._data_dir_var)

        buttons = tk.Frame(body, bg=BG)
        buttons.grid(row=5, column=0, sticky="w", pady=(14, 16))
        FlatButton(
            buttons,
            "打开保存目录",
            self.plugin.open_save_folder,
            fonts=fonts,
            font_size=9,
            padx=12,
            pady=7,
            bg=BUTTON,
            fg=TEXT,
            image=icons.get("folder", 15, TEXT),
        ).pack(side="left", padx=(0, 8))
        FlatButton(
            buttons,
            "打开设置",
            self._on_open_settings,
            fonts=fonts,
            font_size=9,
            padx=12,
            pady=7,
            bg=BUTTON,
            fg=TEXT,
            image=icons.get("gear", 15, TEXT),
        ).pack(side="left")
        self.refresh()

    def _panel(self, parent: tk.Misc, *, row: int, title: str) -> tk.Frame:
        wrapper = tk.Frame(
            parent,
            bg=BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        wrapper.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        tk.Label(
            wrapper,
            text=title,
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(11, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        return wrapper

    def _info_row(
        self, parent: tk.Misc, label: str, variable: tk.StringVar
    ) -> None:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text=label,
            bg=PANEL,
            fg=MUTED,
            width=12,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(side="left")
        tk.Label(
            row,
            textvariable=variable,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            justify="left",
            wraplength=560,
            font=self.fonts.u(9),
        ).pack(side="left", fill="x", expand=True)

    def _section(
        self, parent: tk.Misc, *, row: int, title: str, lines
    ) -> None:
        panel = self._panel(parent, row=row, title=title)
        for line in lines:
            tk.Label(
                panel,
                text=line,
                bg=PANEL,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=640,
                font=self.fonts.u(9),
            ).pack(fill="x", pady=2)

    def refresh(self) -> None:
        settings = self.plugin.settings
        if settings.hotkey_enabled:
            self._hotkey_var.set(settings.hotkey.display())
        else:
            self._hotkey_var.set("未启用")
        self._save_dir_var.set(str(settings.resolved_save_dir()))
        try:
            data_dir = self.plugin.context.data_dir
        except Exception:
            data_dir = ""
        self._data_dir_var.set(str(data_dir))
