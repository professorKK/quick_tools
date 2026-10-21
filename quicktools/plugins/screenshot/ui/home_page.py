"""Home page for the screenshot plugin control window."""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING, Callable

from quicktools.hotkey import is_wayland_session
from quicktools.ui_theme import (
    BG,
    MUTED,
    PANEL,
    TEXT,
    Fonts,
)

from ..shortcuts import shortcut_label
from .icons import IconSet
from .recent_view import RecentView
from .widgets import ModeCard

if TYPE_CHECKING:
    from ..plugin import ScreenshotPlugin

_MODES = (
    (
        "矩形截图",
        "拖拽选择任意矩形区域，适合圈定局部内容。",
        "capture_region",
        "rect",
        "#e8f0fe",
        "#2563eb",
    ),
    (
        "窗口截图",
        "选择应用窗口进行截图，减少无关内容。",
        "capture_window",
        "window",
        "#f3e8ff",
        "#7c3aed",
    ),
    (
        "自由截图",
        "截取全屏后在编辑器中套索任意形状。",
        "capture_freeform",
        "lasso",
        "#e7f8ef",
        "#15803d",
    ),
    (
        "滚动截图",
        "自动滚动并拼接长页面（Windows/X11）。",
        "capture_scroll",
        "scroll",
        "#fff1e6",
        "#ea580c",
    ),
)


class HomePage(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        plugin: "ScreenshotPlugin",
        fonts: Fonts,
        icons: IconSet,
        *,
        on_toast: Callable[[str, bool], None] | None = None,
    ) -> None:
        super().__init__(master, bg=BG)
        self.plugin = plugin
        self.fonts = fonts
        self.icons = icons
        self.grid_columnconfigure(0, weight=1)
        self.recent_view: RecentView
        self._mode_cards: list[tuple[str, ModeCard]] = []
        row = 0

        header = tk.Frame(self, bg=BG)
        header.grid(row=row, column=0, sticky="ew")
        row += 1
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(
            titles,
            text="截图助手",
            bg=BG,
            fg=TEXT,
            font=fonts.u(17, "bold"),
        ).pack(side="left")
        tk.Label(
            titles,
            text="快捷、便捷、专业的屏幕截图工具",
            bg=BG,
            fg=MUTED,
            font=fonts.u(9),
        ).pack(side="left", padx=(10, 0))

        hint = self.plugin.platform_hint()
        if hint:
            hint_row = tk.Frame(self, bg=PANEL)
            hint_row.grid(row=row, column=0, sticky="ew", pady=(10, 0))
            tk.Label(
                hint_row,
                bg=PANEL,
                image=icons.get("info", 15, MUTED),
            ).pack(side="left", padx=(10, 6), pady=6)
            tk.Label(
                hint_row,
                text=hint,
                bg=PANEL,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=680,
                font=fonts.u(9),
            ).pack(side="left", fill="x", expand=True, padx=(0, 10), pady=6)
            row += 1

        modes = tk.Frame(self, bg=BG)
        modes.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        row += 1
        for column in range(len(_MODES)):
            modes.grid_columnconfigure(column, weight=1, uniform="mode")
        for index, (
            title,
            description,
            action,
            icon_name,
            accent_bg,
            accent_fg,
        ) in enumerate(_MODES):
            card = ModeCard(
                modes,
                title=title,
                description=description,
                shortcut="",
                icon_name=icon_name,
                accent_bg=accent_bg,
                accent_fg=accent_fg,
                command=lambda value=action: self.plugin.handle_action(value),
                fonts=fonts,
                icons=icons,
            )
            card.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, 0 if index == len(_MODES) - 1 else 6),
            )
            self._mode_cards.append((action, card))

        recent = tk.Frame(self, bg=BG)
        recent.grid(row=row, column=0, sticky="nsew", pady=(14, 0))
        self.grid_rowconfigure(row, weight=1)
        self._recent_row = row
        self.recent_view = RecentView(
            recent,
            plugin,
            on_toast=on_toast,
            icons=icons,
        )
        self.recent_view.pack(fill="both", expand=True)
        self.refresh_hotkeys()

    def refresh_hotkeys(self) -> None:
        available = bool(self.plugin.settings.hotkey_enabled) and not (
            is_wayland_session()
        )
        for action, card in self._mode_cards:
            card.set_shortcut(shortcut_label(action) if available else "")

    def fixed_height(self) -> int:
        """Return the requested height of everything except the recent list."""

        total = 0
        for slave in self.grid_slaves():
            info = slave.grid_info()
            if not info or int(info.get("row", -1)) == self._recent_row:
                continue
            pady = info.get("pady", 0)
            if isinstance(pady, (tuple, list)):
                top, bottom = (list(pady) + [0, 0])[:2]
            else:
                top = bottom = pady
            total += slave.winfo_reqheight() + int(top) + int(bottom)
        return total
