"""Card, row and toggle widgets used by the shared plugin settings dialog.

Tk has no rounded containers, so a ``Card`` paints its rounded background and
a soft bottom shadow on a Canvas and packs a regular frame on top of it.  The
inset is larger than the corner radius, which keeps the square corners of the
child frame invisible inside the painted card.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from .ui_icons import draw_gear, draw_info, draw_symbol
from .ui_theme import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_SOFT_HOVER,
    BADGE_BG,
    CARD_BG,
    CARD_BORDER,
    DIVIDER,
    MUTED,
    SURFACE,
    TEXT,
    Fonts,
    pick_fonts,
    round_rect,
)

CARD_INSET_X = 14
CARD_INSET_Y = 12
CARD_SHADOW = 4


class Card(tk.Frame):
    """White rounded panel with a soft shadow, wrapping ``self.body``."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        background: str = SURFACE,
        background_color: str = CARD_BG,
        radius: int = 12,
        padding: tuple[int, int] = (18, 16),
        shadow: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(master, bg=background, **kwargs)
        self.background = background
        self.card_bg = background_color
        self.radius = radius
        self._shadow = shadow
        self._canvas = tk.Canvas(
            self,
            bg=background,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(
            self,
            bg=background_color,
            padx=padding[0],
            pady=padding[1],
        )
        self.body.pack(
            fill="both",
            expand=True,
            padx=CARD_INSET_X,
            pady=(CARD_INSET_Y, CARD_INSET_Y + CARD_SHADOW),
        )
        self.bind("<Configure>", self._redraw)

    def _redraw(self, _event=None) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        if width < CARD_INSET_X * 2 + 8 or height < CARD_INSET_Y * 2 + 8:
            return
        canvas = self._canvas
        try:
            canvas.delete("all")
            if self._shadow:
                # Two low-contrast layers give the impression of a blurred
                # shadow without needing alpha compositing in Tk.
                round_rect(
                    canvas,
                    6,
                    7,
                    width - 4,
                    height - 2,
                    self.radius,
                    "#e0e5ee",
                )
                round_rect(
                    canvas,
                    5,
                    5,
                    width - 5,
                    height - 5,
                    self.radius,
                    "#eaedf4",
                )
            round_rect(
                canvas,
                4,
                3,
                width - 6,
                height - 9,
                self.radius,
                CARD_BORDER,
            )
            round_rect(
                canvas,
                5,
                4,
                width - 7,
                height - 10,
                max(0, self.radius - 1),
                self.card_bg,
            )
            canvas.lower()
        except tk.TclError:
            pass


class IconBadge(tk.Canvas):
    """Rounded accent tile with a one or two character plugin icon."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        *,
        size: int = 44,
        background: str = CARD_BG,
        fonts: Fonts | None = None,
    ) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            bg=background,
            highlightthickness=0,
            bd=0,
        )
        self._size = size
        self._fonts = fonts or pick_fonts(master)
        self._font: tkfont.Font | None = None
        self._text = text
        self._draw()

    def _draw(self) -> None:
        size = self._size
        try:
            self.delete("all")
            round_rect(
                self,
                1,
                1,
                size - 1,
                size - 1,
                max(6, size // 4),
                BADGE_BG,
            )
            font = tkfont.Font(
                family=self._fonts.ui,
                size=max(10, int(size * (0.40 if len(self._text) > 1 else 0.50))),
                weight="bold",
            )
            self._font = font
            self.create_text(
                size / 2,
                size / 2,
                text=self._text,
                fill=ACCENT,
                font=font,
            )
        except tk.TclError:
            pass

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._draw()


class SectionHeader(tk.Frame):
    """Bold section title with an accent bar and optional description."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        description: str = "",
        *,
        bg: str = CARD_BG,
        fonts: Fonts | None = None,
        wraplength: int = 520,
    ) -> None:
        super().__init__(master, bg=bg)
        self.fonts = fonts or pick_fonts(master)
        head = tk.Frame(self, bg=bg)
        head.pack(fill="x")
        bar = tk.Frame(head, bg=ACCENT, width=3, height=15)
        bar.pack(side="left", padx=(0, 8))
        bar.pack_propagate(False)
        self.title_label = tk.Label(
            head,
            text=title,
            bg=bg,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(13, "bold"),
        )
        self.title_label.pack(side="left", fill="x", expand=True)
        self.description_label: tk.Label | None = None
        if description:
            self.description_label = tk.Label(
                self,
                text=description,
                bg=bg,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=wraplength,
                font=self.fonts.u(9),
            )
            self.description_label.pack(
                fill="x", padx=(11, 0), pady=(4, 0)
            )
            self.bind("<Configure>", self._on_configure, add="+")

    def _on_configure(self, event: tk.Event) -> None:
        if self.description_label is None or event.widget is not self:
            return
        try:
            self.description_label.configure(
                wraplength=max(180, event.width - 11)
            )
        except tk.TclError:
            pass


class SettingsRow(tk.Frame):
    """One labelled setting row with a control area on the right."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        *,
        description: str = "",
        bg: str = CARD_BG,
        fonts: Fonts | None = None,
        last: bool = False,
        padding: tuple[int, int] = (0, 10),
    ) -> None:
        super().__init__(master, bg=bg)
        self.fonts = fonts or pick_fonts(master)
        self._bg = bg
        inner = tk.Frame(self, bg=bg)
        inner.pack(
            fill="x", pady=padding
        )
        text = tk.Frame(inner, bg=bg)
        text.pack(side="left", fill="x", expand=True)
        self.title_label = tk.Label(
            text,
            text=title,
            bg=bg,
            fg=TEXT,
            anchor="w",
            justify="left",
            font=self.fonts.u(10),
        )
        self.title_label.pack(fill="x")
        self.description_label: tk.Label | None = None
        if description:
            self.description_label = tk.Label(
                text,
                text=description,
                bg=bg,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=380,
                font=self.fonts.u(9),
            )
            self.description_label.pack(fill="x", pady=(2, 0))
        self.control = tk.Frame(inner, bg=bg)
        self.control.pack(side="right", padx=(18, 0))
        if not last:
            tk.Frame(self, bg=DIVIDER, height=1).pack(fill="x")
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event: tk.Event) -> None:
        if self.description_label is None or event.widget is not self:
            return
        try:
            control_width = self.control.winfo_reqwidth()
            width = self.winfo_width() - control_width - 28
            self.description_label.configure(wraplength=max(180, width))
        except tk.TclError:
            pass


class ToggleSwitch(tk.Canvas):
    """Small modern on/off switch bound to a ``BooleanVar``."""

    WIDTH = 42
    HEIGHT = 24
    TRACK_OFF = "#d7dde7"
    KNOB = "#ffffff"

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
        *,
        bg: str = CARD_BG,
    ) -> None:
        super().__init__(
            master,
            width=self.WIDTH,
            height=self.HEIGHT,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.variable = variable
        self._command = command
        self._value = bool(variable.get())
        self._trace = variable.trace_add("write", self._on_variable)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._draw()

    def _on_variable(self, *_args) -> None:
        value = bool(self.variable.get())
        if value != self._value:
            self._value = value
            self._draw()

    def _draw(self) -> None:
        try:
            self.delete("all")
            track = ACCENT if self._value else self.TRACK_OFF
            round_rect(
                self,
                1,
                2,
                self.WIDTH - 1,
                self.HEIGHT - 2,
                (self.HEIGHT - 4) / 2,
                track,
            )
            radius = self.HEIGHT / 2 - 4
            center_x = (
                self.WIDTH - radius - 4
                if self._value
                else radius + 4
            )
            center_y = self.HEIGHT / 2
            self.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                fill=self.KNOB,
                outline="",
            )
        except tk.TclError:
            pass

    def _on_click(self, _event=None) -> None:
        self.variable.set(not bool(self.variable.get()))
        if self._command is not None:
            self._command()

    def toggle(self) -> None:
        self._on_click()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        try:
            self.variable.trace_remove("write", self._trace)
        except Exception:
            pass


class ToggleRow(SettingsRow):
    """Settings row whose control is a toggle switch; labels are clickable."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        variable: tk.BooleanVar,
        *,
        description: str = "",
        command: Callable[[], None] | None = None,
        bg: str = CARD_BG,
        fonts: Fonts | None = None,
        last: bool = False,
    ) -> None:
        super().__init__(
            master,
            title,
            description=description,
            bg=bg,
            fonts=fonts,
            last=last,
            padding=(0, 9),
        )
        self.switch = ToggleSwitch(
            self.control, variable, command, bg=bg
        )
        self.switch.pack()
        for widget in (self.title_label, self.description_label):
            if widget is None:
                continue
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _event: self.switch.toggle())


class NavItem(tk.Frame):
    """Sidebar navigation row with a small symbol icon."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        kind: str,
        command: Callable[[], None],
        *,
        fonts: Fonts,
        active: bool = False,
        bg: str = CARD_BG,
    ) -> None:
        super().__init__(master, bg=bg, cursor="hand2")
        self._fonts = fonts
        self._kind = kind
        self._command = command
        self._base_bg = bg
        self._active = bool(active)
        self._hover = False
        self._bar = tk.Frame(self, bg=bg, width=3)
        self._bar.pack(side="left", fill="y")
        self._bar.pack_propagate(False)
        self._icon = tk.Canvas(
            self,
            width=20,
            height=20,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self._icon.pack(side="left", padx=(8, 7), pady=7)
        self._label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=TEXT,
            anchor="w",
            font=fonts.u(10),
            cursor="hand2",
        )
        self._label.pack(side="left", fill="x", expand=True, padx=(0, 10))
        for widget in (self, self._icon, self._label):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
        self._refresh()

    def _on_click(self, _event=None) -> None:
        self._command()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._refresh()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._refresh()

    def _draw_icon(self, color: str) -> None:
        try:
            self._icon.delete("all")
            size = 20
            self._icon.configure(bg=self._bg())
            if not draw_symbol(
                self._icon,
                self._kind,
                cx=size / 2,
                cy=size / 2,
                size=size,
                fg=color,
                fonts=self._fonts,
            ):
                if self._kind == "settings":
                    draw_gear(
                        self._icon,
                        size,
                        color,
                        self._bg(),
                    )
                else:
                    draw_info(self._icon, size, color)
        except tk.TclError:
            pass

    def _bg(self) -> str:
        if self._active:
            return ACCENT_SOFT
        if self._hover:
            return ACCENT_SOFT_HOVER
        return self._base_bg

    def _refresh(self) -> None:
        try:
            background = self._bg()
            color = ACCENT if (self._active or self._hover) else MUTED
            self.configure(bg=background)
            self._bar.configure(bg=ACCENT if self._active else background)
            self._label.configure(
                bg=background,
                fg=ACCENT if self._active else TEXT,
                font=self._fonts.u(10, "bold" if self._active else "normal"),
            )
            self._draw_icon(color)
        except tk.TclError:
            pass

    def set_active(self, active: bool) -> None:
        if self._active != bool(active):
            self._active = bool(active)
            self._refresh()
