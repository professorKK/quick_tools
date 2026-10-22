"""Annotation toolbar for the screenshot editor."""

from __future__ import annotations

import logging
import tkinter as tk

from quicktools.ui_theme import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    BUTTON,
    BUTTON_HOVER,
    BUTTON_PRESSED,
    FlatButton,
    MUTED,
    ON_ACCENT,
    PANEL,
    TEXT,
    Fonts,
)

from ..ui.icons import IconSet
from ..ui.widgets import ColorSwatch
from .annotations import Tool
from .canvas import AnnotationCanvas

log = logging.getLogger(__name__)

_COLORS = (
    "#e53935",
    "#fb8c00",
    "#fdd835",
    "#43a047",
    "#1e88e5",
    "#8e24aa",
    "#111827",
    "#ffffff",
)
_TOOLS = (
    ("选择", Tool.SELECT, "select"),
    ("矩形", Tool.RECT, "rect"),
    ("圆形", Tool.ELLIPSE, "ellipse"),
    ("箭头", Tool.ARROW, "arrow"),
    ("画笔", Tool.BRUSH, "brush"),
    ("文字", Tool.TEXT, "text"),
    ("序号", Tool.NUMBER, "number"),
    ("马赛克", Tool.MOSAIC, "mosaic"),
    ("贴纸", Tool.STICKER, "sticker"),
    ("水印", Tool.WATERMARK, "watermark"),
    ("裁剪", Tool.CROP, "crop"),
    ("套索裁剪", Tool.LASSO, "lasso"),
)


class AnnotationToolbar(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        canvas: AnnotationCanvas,
        fonts: Fonts,
        *,
        icons: IconSet | None = None,
    ) -> None:
        super().__init__(master, bg=PANEL, padx=8, pady=7)
        self.canvas = canvas
        self.fonts = fonts
        self.icons = icons or IconSet(self)
        self._tool_buttons: dict[Tool, FlatButton] = {}
        self._swatches: dict[str, ColorSwatch] = {}
        self.canvas.on_tool_change = self._sync_tool
        self._build()
        self._set_color(self.canvas.style.color)
        self._select_tool(Tool.SELECT)

    def _build(self) -> None:
        tools = tk.Frame(self, bg=PANEL)
        tools.pack(fill="x")
        for label, tool, icon_name in _TOOLS:
            button = FlatButton(
                tools,
                label,
                lambda value=tool: self._select_tool(value),
                fonts=self.fonts,
                font_size=9,
                padx=7,
                pady=4,
                bg=PANEL,
                fg=TEXT,
                hover_bg=BUTTON_HOVER,
                press_bg=BUTTON_PRESSED,
                image=self.icons.get(icon_name, 21, TEXT),
                active_image=self.icons.get(icon_name, 21, ON_ACCENT),
                active_bg=ACCENT,
                active_fg=ON_ACCENT,
                active_hover_bg=ACCENT_HOVER,
                compound="top",
            )
            button.pack(side="left", padx=(0, 3))
            self._tool_buttons[tool] = button

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(7, 6))

        style_row = tk.Frame(self, bg=PANEL)
        style_row.pack(fill="x")
        tk.Label(
            style_row,
            text="颜色",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="left", padx=(2, 6))
        for color in _COLORS:
            swatch = ColorSwatch(
                style_row,
                color,
                lambda value=color: self._set_color(value),
                bg=PANEL,
            )
            swatch.pack(side="left", padx=(0, 3))
            self._swatches[color] = swatch

        tk.Label(
            style_row,
            text="线宽",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="left", padx=(12, 5))
        self.width_var = tk.StringVar(value=str(self.canvas.style.width))
        width_box = tk.Spinbox(
            style_row,
            from_=1,
            to=30,
            width=3,
            textvariable=self.width_var,
            font=self.fonts.u(9),
            bg="#ffffff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            justify="center",
            command=self._apply_width,
        )
        width_box.pack(side="left", ipady=2)
        self.width_var.trace_add("write", lambda *_args: self._apply_width())

        tk.Label(
            style_row,
            text="字号",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="left", padx=(12, 5))
        self.font_size_var = tk.StringVar(value=str(self.canvas.style.font_size))
        font_box = tk.Spinbox(
            style_row,
            from_=8,
            to=120,
            width=4,
            textvariable=self.font_size_var,
            font=self.fonts.u(9),
            bg="#ffffff",
            fg=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            justify="center",
            command=self._apply_font_size,
        )
        font_box.pack(side="left", ipady=2)
        self.font_size_var.trace_add(
            "write", lambda *_args: self._apply_font_size()
        )
        for label, delta in (("A-", -2), ("A+", 2)):
            FlatButton(
                style_row,
                label,
                lambda value=delta: self._bump_font_size(value),
                fonts=self.fonts,
                font_size=8,
                padx=5,
                pady=2,
                bg=BUTTON,
                fg=TEXT,
            ).pack(side="left", padx=(3, 0))

        actions = tk.Frame(style_row, bg=PANEL)
        actions.pack(side="right")
        for (
            label,
            icon_name,
            command,
        ) in (
            ("撤销", "undo", self.canvas.undo),
            ("重做", "redo", self._redo_or_reset),
            ("重置", "reset", self.canvas.reset_to_original),
            ("左转", "rotate-left", lambda: self.canvas.rotate(False)),
            ("右转", "rotate-right", lambda: self.canvas.rotate(True)),
            ("翻转", "flip", lambda: self.canvas.flip(True)),
        ):
            FlatButton(
                actions,
                label,
                command,
                fonts=self.fonts,
                font_size=8,
                padx=6,
                pady=3,
                bg=PANEL,
                fg=MUTED,
                hover_bg=BUTTON_HOVER,
                image=self.icons.get(icon_name, 15, MUTED),
            ).pack(side="left", padx=(0, 3))

        tk.Label(
            self,
            text="矩形/圆形为空心圈选 · 滚轮缩放 · 空格+拖动或中键平移",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(8),
            anchor="w",
        ).pack(fill="x", pady=(6, 0))

    def _select_tool(self, tool: Tool) -> None:
        self.canvas.set_tool(tool)
        self._sync_tool(tool)
        if tool is Tool.STICKER:
            # Sticker flow: open the picker immediately and insert the image
            # at the center; the canvas returns to SELECT afterwards.
            self.canvas.add_sticker_at_center()

    def _sync_tool(self, tool: Tool) -> None:
        for item, button in self._tool_buttons.items():
            try:
                button.set_active(item is tool)
            except Exception:
                pass

    def _set_color(self, color: str) -> None:
        self.canvas.set_style(color=color)
        selected = color.lower()
        for value, swatch in self._swatches.items():
            swatch.set_selected(value.lower() == selected)

    def _apply_width(self) -> None:
        try:
            value = int(self.width_var.get())
        except ValueError:
            return
        self.canvas.set_style(width=max(1, min(30, value)))

    def _apply_font_size(self) -> None:
        try:
            value = int(self.font_size_var.get())
        except ValueError:
            return
        self.canvas.set_style(font_size=max(8, min(120, value)))

    def _redo_or_reset(self) -> None:
        if not self.canvas.redo():
            self.canvas.reset_to_original()

    def _bump_font_size(self, delta: int) -> None:
        try:
            value = int(self.font_size_var.get())
        except ValueError:
            value = self.canvas.style.font_size
        self.font_size_var.set(str(max(8, min(120, value + delta))))
