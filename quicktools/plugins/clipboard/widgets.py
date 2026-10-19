"""Reusable Tk widgets for the clipboard plugin."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from quicktools.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    BUTTON,
    BUTTON_HOVER,
    MUTED,
    PANEL,
    ROW_ACTIVE,
    TEXT,
    Fonts,
)

from .models import ClipboardKind

TYPE_STYLES: dict[ClipboardKind, tuple[str, str, str]] = {
    ClipboardKind.TEXT: ("#e8f0fe", "#2563eb", "T"),
    ClipboardKind.IMAGE: ("#e6f4ea", "#15803d", "P"),
    ClipboardKind.FILES: ("#fff7e0", "#b45309", "F"),
}


class TypeBadge(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        kind: ClipboardKind,
        *,
        size: int = 40,
        fonts: Fonts,
    ) -> None:
        try:
            kind = ClipboardKind(kind.value)
        except (AttributeError, ValueError):
            pass
        background, foreground, glyph = TYPE_STYLES.get(
            kind, TYPE_STYLES[ClipboardKind.TEXT]
        )
        super().__init__(master, bg=background, width=size, height=size)
        self.pack_propagate(False)
        self.label = tk.Label(
            self,
            text=glyph,
            bg=background,
            fg=foreground,
            font=fonts.u(max(11, size // 3), "bold"),
        )
        self.label.pack(fill="both", expand=True)


class NavItem(tk.Frame):
    """Sidebar navigation row with an optional count label."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        glyph: str,
        fonts: Fonts,
        command: Callable[[], None],
        count_var: tk.StringVar | None = None,
        *,
        indent: bool = True,
    ) -> None:
        super().__init__(
            master,
            bg=PANEL,
            cursor="hand2",
            padx=10 if indent else 0,
            pady=8,
        )
        self._fonts = fonts
        self._command = command
        self._selected = False
        self._hover_bg = BUTTON_HOVER
        self._widgets: list[tk.Widget] = []

        self.glyph_label = tk.Label(
            self,
            text=glyph,
            bg=PANEL,
            fg=MUTED,
            width=2,
            anchor="center",
            font=fonts.u(12),
            cursor="hand2",
        )
        self.glyph_label.pack(side="left")
        self.text_label = tk.Label(
            self,
            text=text,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            font=fonts.u(11),
            cursor="hand2",
        )
        self.text_label.pack(side="left", fill="x", expand=True)
        self.count_label = None
        if count_var is not None:
            self.count_label = tk.Label(
                self,
                textvariable=count_var,
                bg=PANEL,
                fg=MUTED,
                anchor="e",
                font=fonts.u(10),
                cursor="hand2",
            )
            self.count_label.pack(side="right")
        self._widgets = [
            self,
            self.glyph_label,
            self.text_label,
        ]
        if self.count_label is not None:
            self._widgets.append(self.count_label)
        for widget in self._widgets:
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    def _on_click(self, _event=None) -> None:
        self._command()

    def _on_enter(self, _event=None) -> None:
        if not self._selected:
            self._apply_bg(BUTTON)

    def _on_leave(self, _event=None) -> None:
        if not self._selected:
            self._apply_bg(PANEL)

    def _apply_bg(self, background: str) -> None:
        for widget in self._widgets:
            try:
                widget.configure(bg=background)
            except tk.TclError:
                pass

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            self._apply_bg(ROW_ACTIVE)
            self.text_label.configure(
                fg=ACCENT, font=self._fonts.u(11, "bold")
            )
            self.glyph_label.configure(fg=ACCENT)
            if self.count_label is not None:
                self.count_label.configure(fg=ACCENT)
        else:
            self._apply_bg(PANEL)
            self.text_label.configure(fg=TEXT, font=self._fonts.u(11))
            self.glyph_label.configure(fg=MUTED)
            if self.count_label is not None:
                self.count_label.configure(fg=MUTED)


class PlaceholderEntry(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        fonts: Fonts,
        *,
        placeholder: str,
        background: str = PANEL,
    ) -> None:
        super().__init__(
            master,
            bg=background,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self._background = background
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self,
            textvariable=self.var,
            bg=background,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=fonts.u(11),
        )
        self.entry.pack(fill="both", expand=True, padx=9, pady=8)
        self._placeholder = tk.Label(
            self,
            text=placeholder,
            bg=background,
            fg=MUTED,
            font=fonts.u(11),
            cursor="xterm",
        )
        self._placeholder.place(x=10, rely=0.5, anchor="w")
        self._placeholder.bind("<Button-1>", lambda _e: self.focus())
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.var.trace_add("write", self._on_change)

    def _on_focus_in(self, _event=None) -> None:
        if not self.var.get():
            self._placeholder.place_forget()

    def _on_focus_out(self, _event=None) -> None:
        if not self.var.get():
            self._placeholder.place(x=10, rely=0.5, anchor="w")

    def _on_change(self, *_args) -> None:
        if self.var.get():
            self._placeholder.place_forget()
        else:
            try:
                if self.entry.focus_get() is not self.entry:
                    self._placeholder.place(x=10, rely=0.5, anchor="w")
            except (tk.TclError, AttributeError):
                pass

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)

    def focus(self) -> None:
        self.entry.focus_set()
        self.entry.selection_range(0, tk.END)


class ScrollableFrame(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        background: str = BG,
        scrollbar_bg: str = BG,
    ) -> None:
        super().__init__(master, bg=background)
        self.canvas = tk.Canvas(
            self,
            bg=background,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            bg=BORDER,
            troughcolor=scrollbar_bg,
            activebackground=ACCENT,
            bd=0,
            relief="flat",
            width=10,
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=background)
        self._window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        bind_wheel_recursive(self.canvas, self._on_wheel)
        bind_wheel_recursive(self.inner, self._on_wheel)

    def _on_inner_configure(self, _event=None) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            units = -3 if getattr(event, "delta", 0) > 0 else 3
        self.canvas.yview_scroll(units, "units")
        return "break"

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def bind_wheel(self, widget: tk.Misc) -> None:
        bind_wheel_recursive(widget, self._on_wheel)


def bind_wheel_recursive(widget: tk.Misc, callback) -> None:
    widget.bind("<Button-4>", callback, add="+")
    widget.bind("<Button-5>", callback, add="+")
    widget.bind("<MouseWheel>", callback, add="+")
    for child in widget.winfo_children():
        bind_wheel_recursive(child, callback)


def horizontal_divider(master: tk.Misc) -> tk.Frame:
    return tk.Frame(master, bg=BORDER, height=1)


def vertical_divider(master: tk.Misc) -> tk.Frame:
    return tk.Frame(master, bg=BORDER, width=1)
