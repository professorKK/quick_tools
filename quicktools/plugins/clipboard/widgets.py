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
    BUTTON_PRESSED,
    DANGER,
    DISABLED_TEXT,
    MUTED,
    PANEL,
    ROW_ACTIVE,
    TEXT,
    Fonts,
    round_rect,
)
from quicktools.window_frame import Tooltip

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


class CardAction:
    """Logical action occupying one hit zone of ``CardActionBar``."""

    def __init__(
        self,
        bar: "CardActionBar",
        kind: str,
        command: Callable[[], None],
        tooltip: str,
        *,
        enabled: bool = True,
        danger: bool = False,
    ) -> None:
        self.kind = kind
        self._bar = bar
        self._command = command
        self.tooltip = tooltip
        self._enabled = enabled
        self._danger = danger

    def invoke(self) -> None:
        if self._enabled:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._bar._draw()


class CardActionBar(tk.Canvas):
    """Three icon actions painted in a single canvas.

    One canvas per history row instead of three keeps opening a large
    clipboard history fast: Tk widget creation dominates list rendering.
    """

    SIZE = 26
    GAP = 2
    KIND_ORDER = ("copy", "reveal", "delete")

    def __init__(
        self,
        master: tk.Misc,
        handlers: dict[str, Callable[[], None]],
        *,
        fonts: Fonts,
        bg: str = PANEL,
        reveal_enabled: bool = True,
        reveal_tooltip: str = "打开位置",
        size: int = SIZE,
    ) -> None:
        stride = size + self.GAP
        width = stride * len(self.KIND_ORDER) - self.GAP
        super().__init__(
            master,
            width=width,
            height=size,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self._size = size
        self._stride = stride
        self._fonts = fonts
        self._idle_bg = bg
        self._hover_bg = BUTTON_HOVER
        self._press_bg = BUTTON_PRESSED
        self._hovered: str | None = None
        self._pressed: str | None = None
        self._tooltip: Tooltip | None = None
        self.actions = {
            "copy": CardAction(
                self, "copy", handlers["copy"], "二次复制"
            ),
            "reveal": CardAction(
                self,
                "reveal",
                handlers["reveal"],
                reveal_tooltip,
                enabled=reveal_enabled,
            ),
            "delete": CardAction(
                self,
                "delete",
                handlers["delete"],
                "删除该记录",
                danger=True,
            ),
        }
        self._draw()
        self.bind("<Enter>", self._on_pointer)
        self.bind("<Motion>", self._on_pointer)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # --------------------------------------------------------------- paint
    def _zone_x(self, kind: str) -> float:
        return self.KIND_ORDER.index(kind) * self._stride

    def _kind_at(self, x: float) -> str | None:
        if x < 0:
            return None
        index = int(x // self._stride)
        if not 0 <= index < len(self.KIND_ORDER):
            return None
        if x - index * self._stride >= self._size:
            return None
        return self.KIND_ORDER[index]

    def _surface(self, kind: str) -> str:
        if self._pressed == kind:
            return self._press_bg
        if self._hovered == kind:
            return self._hover_bg
        return self._idle_bg

    def _xy(
        self, x: float, y: float, dx: float = 0.0
    ) -> tuple[float, float]:
        scale = self._size / 24
        return dx + x * scale, y * scale

    def _line(self, points, fg: str, width: float, dx: float = 0.0) -> None:
        coords: list[float] = []
        for x, y in points:
            coords.extend(self._xy(x, y, dx))
        self.create_line(
            coords,
            fill=fg,
            width=width,
            capstyle="round",
            joinstyle="round",
        )

    def _draw(self) -> None:
        self.delete("all")
        width = self._size / 14
        for kind in self.KIND_ORDER:
            action = self.actions[kind]
            dx = self._zone_x(kind)
            surface = self._surface(kind)
            if action._enabled and (self._hovered == kind or self._pressed == kind):
                round_rect(
                    self,
                    dx + 1,
                    1,
                    dx + self._size - 1,
                    self._size - 1,
                    radius=6,
                    fill=surface,
                )
            if not action._enabled:
                fg = DISABLED_TEXT
            elif action._danger:
                fg = DANGER
            else:
                fg = MUTED
            if kind == "copy":
                self._draw_copy(fg, width, surface, dx)
            elif kind == "reveal":
                self._draw_reveal(fg, width, dx)
            else:
                self._draw_delete(fg, width, dx)

    def _draw_copy(
        self, fg: str, width: float, surface: str, dx: float
    ) -> None:
        scale = self._size / 24
        radius = max(2, 2 * scale)
        x1, y1 = self._xy(9, 3.5, dx)
        x2, y2 = self._xy(20.5, 15, dx)
        round_rect(
            self, x1, y1, x2, y2, radius, fill="", outline=fg, width=width
        )
        x1, y1 = self._xy(3.5, 9, dx)
        x2, y2 = self._xy(15, 20.5, dx)
        round_rect(
            self,
            x1,
            y1,
            x2,
            y2,
            radius,
            fill=surface,
            outline=fg,
            width=width,
        )

    def _draw_reveal(self, fg: str, width: float, dx: float) -> None:
        points = [(3, 7), (9, 7), (11, 9), (21, 9), (21, 19), (3, 19)]
        self._line(points + [points[0]], fg, width, dx)

    def _draw_delete(self, fg: str, width: float, dx: float) -> None:
        self._line([(4, 7), (20, 7)], fg, width, dx)
        self._line([(9, 7), (9, 4), (15, 4), (15, 7)], fg, width, dx)
        self._line([(6, 7), (7, 20), (17, 20), (18, 7)], fg, width, dx)
        self._line([(10, 10), (10.5, 17)], fg, width, dx)
        self._line([(14, 10), (13.5, 17)], fg, width, dx)

    # ---------------------------------------------------------------- state
    def _on_pointer(self, event: tk.Event) -> None:
        self._set_hovered(self._kind_at(event.x))

    def _set_hovered(self, kind: str | None) -> None:
        if kind == self._hovered:
            return
        self._hovered = kind
        self.configure(
            cursor="hand2" if kind and self.actions[kind]._enabled else ""
        )
        self._draw()
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        kind = self._hovered
        if kind is None:
            if self._tooltip is not None:
                self._tooltip.hide()
            return
        text = self.actions[kind].tooltip
        if self._tooltip is None:
            # Created on first hover so opening a big history does not pay
            # for one Tooltip object per row.
            self._tooltip = Tooltip(self, text, fonts=self._fonts)
        else:
            self._tooltip.hide()
            self._tooltip.text = text
        self._tooltip.schedule()

    def _on_leave(self, _event=None) -> None:
        self._pressed = None
        self._set_hovered(None)
        self.configure(cursor="")

    def _on_press(self, event: tk.Event) -> None:
        kind = self._kind_at(event.x)
        if kind is not None and self.actions[kind]._enabled:
            self._pressed = kind
            self._draw()

    def _on_release(self, event: tk.Event) -> None:
        kind = self._kind_at(event.x)
        pressed = self._pressed
        self._pressed = None
        self._draw()
        if pressed is not None and kind == pressed:
            self.actions[pressed].invoke()

    def set_background(self, bg: str) -> None:
        self._idle_bg = bg
        self.configure(bg=bg)
        self._draw()


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
        # A window created while the plugin Toplevel is withdrawn can receive
        # its final <Configure> before mapping. Tk then embeds ``inner`` at its
        # requested width on the first map and never sends another <Configure>,
        # which clips right-aligned row actions. Re-apply the width on <Map>.
        self.canvas.bind("<Map>", self._on_canvas_map, add="+")
        bind_wheel_recursive(self.canvas, self._on_wheel)
        bind_wheel_recursive(self.inner, self._on_wheel)

    def _on_inner_configure(self, _event=None) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_canvas_map(self, _event=None) -> None:
        width = self.canvas.winfo_width()
        if width > 1:
            self.canvas.itemconfigure(self._window, width=width)

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
