"""Small reusable Tk widgets for the screenshot control window."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from quicktools.ui_theme import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_SOFT_HOVER,
    BG,
    BORDER,
    MUTED,
    PANEL,
    TEXT,
    Fonts,
)
from quicktools.window_frame import Tooltip

from .icons import IconSet


def bind_wheel_recursive(widget: tk.Misc, callback) -> None:
    widget.bind("<Button-4>", callback, add="+")
    widget.bind("<Button-5>", callback, add="+")
    widget.bind("<MouseWheel>", callback, add="+")
    for child in widget.winfo_children():
        bind_wheel_recursive(child, callback)


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


def bind_click_recursive(widget: tk.Misc, callback) -> None:
    """Bind a left click on ``widget`` and all of its descendants."""

    widget.bind("<Button-1>", callback)
    for child in widget.winfo_children():
        bind_click_recursive(child, callback)


def bind_hover_recursive(
    widget: tk.Misc,
    on_enter: Callable[[tk.Event], None],
    on_leave: Callable[[tk.Event], None],
) -> None:
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)
    for child in widget.winfo_children():
        bind_hover_recursive(child, on_enter, on_leave)


class NavItem(tk.Frame):
    """Sidebar navigation row with an icon and a label."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        icon_name: str,
        icons: IconSet,
        fonts: Fonts,
        command: Callable[[], None],
        *,
        active: bool = False,
        bg: str = BG,
    ) -> None:
        super().__init__(master, bg=bg, cursor="hand2")
        self._icons = icons
        self._icon_name = icon_name
        self._command = command
        self._base_bg = bg
        self._active = bool(active)
        self._hover = False
        self._icon_label = tk.Label(self, bg=bg)
        self._icon_label.pack(side="left", padx=(10, 8), pady=7)
        self._text_label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=TEXT,
            font=fonts.u(10),
            cursor="hand2",
        )
        self._text_label.pack(side="left", padx=(0, 12))
        bind_click_recursive(self, self._on_click)
        bind_hover_recursive(self, self._on_enter, self._on_leave)
        self._refresh()

    def _on_click(self, _event=None) -> None:
        self._command()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._refresh()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._refresh()

    def _refresh(self) -> None:
        if self._active:
            bg = ACCENT_SOFT
            fg = ACCENT
            icon_color = ACCENT
        elif self._hover:
            bg = ACCENT_SOFT_HOVER
            fg = TEXT
            icon_color = ACCENT
        else:
            bg = self._base_bg
            fg = TEXT
            icon_color = MUTED
        self.configure(bg=bg)
        self._icon_label.configure(
            bg=bg, image=self._icons.get(self._icon_name, 18, icon_color)
        )
        self._text_label.configure(bg=bg, fg=fg)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh()


class PlaceholderEntry(tk.Frame):
    """Entry with a search icon and a placeholder that never pollutes its var."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: Fonts,
        *,
        placeholder: str,
        textvariable: tk.StringVar,
        icons: IconSet,
        background: str = BG,
    ) -> None:
        super().__init__(
            master,
            bg=background,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        self.var = textvariable
        self._background = background
        self._fonts = fonts
        self._icon = tk.Label(
            self,
            bg=background,
            image=icons.get("search", 14, MUTED),
        )
        self._icon.pack(side="left", padx=(8, 4), pady=4)
        self.entry = tk.Entry(
            self,
            textvariable=textvariable,
            bg=background,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=fonts.u(9),
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=5)
        self._placeholder = tk.Label(
            self,
            text=placeholder,
            bg=background,
            fg=MUTED,
            font=fonts.u(9),
            cursor="xterm",
        )
        self._placeholder.place(in_=self.entry, x=3, rely=0.5, anchor="w")
        self._placeholder.bind("<Button-1>", self._focus_entry)
        self.entry.bind("<FocusIn>", self._on_focus)
        self.entry.bind("<FocusOut>", self._on_blur)
        self._trace = textvariable.trace_add(
            "write", self._on_text_changed
        )
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._update_placeholder()

    def _focus_entry(self, _event=None) -> None:
        self.entry.focus_set()
        return "break"

    def _on_focus(self, _event=None) -> None:
        self._update_placeholder()

    def _on_blur(self, _event=None) -> None:
        self._update_placeholder()

    def _on_text_changed(self, *_args) -> None:
        self._update_placeholder()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        try:
            self.var.trace_remove("write", self._trace)
        except Exception:
            pass

    def _update_placeholder(self) -> None:
        try:
            focused = self.entry.focus_get() is self.entry
        except (tk.TclError, KeyError):
            focused = False
        if not focused and not self.var.get():
            self._placeholder.place(
                in_=self.entry, x=3, rely=0.5, anchor="w"
            )
            self._placeholder.lift()
        else:
            self._placeholder.place_forget()

    def focus(self) -> None:
        self.entry.focus_set()


class ModeCard(tk.Frame):
    """Compact clickable capture-mode button for the screenshot home page.

    Only the icon, mode name and shortcut are rendered; the longer explanation
    lives in a hover tooltip so the recent screenshot list keeps the space.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        title: str,
        description: str,
        shortcut: str,
        icon_name: str,
        accent_bg: str,
        accent_fg: str,
        command: Callable[[], None],
        fonts: Fonts,
        icons: IconSet,
    ) -> None:
        super().__init__(
            master,
            bg=BG,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=8,
            pady=7,
            cursor="hand2",
        )
        self.description = description
        self._command = command
        self._hover = False
        body = tk.Frame(self, bg=BG, cursor="hand2")
        body.pack(expand=True)
        self._body = body
        self._icon = tk.Label(
            body,
            bg=BG,
            image=icons.tile(
                icon_name,
                size=30,
                bg=accent_bg,
                fg=accent_fg,
                radius=8,
            ),
            cursor="hand2",
        )
        self._icon.pack(side="left", padx=(0, 9))
        text = tk.Frame(body, bg=BG, cursor="hand2")
        text.pack(side="left")
        self._text = text
        self._title = tk.Label(
            text,
            text=title,
            bg=BG,
            fg=TEXT,
            font=fonts.u(11, "bold"),
            cursor="hand2",
        )
        self._title.pack(anchor="w")
        self._shortcut = tk.Label(
            text,
            text=shortcut,
            bg=BG,
            fg=MUTED,
            font=fonts.m(8),
            cursor="hand2",
        )
        if shortcut:
            self._shortcut.pack(anchor="w", pady=(1, 0))
        bind_click_recursive(self, self._on_click)
        bind_hover_recursive(self, self._on_enter, self._on_leave)
        self._tooltip = Tooltip(
            self,
            description,
            fonts=fonts,
            container=self,
        )

    def _on_click(self, _event=None) -> None:
        self._command()

    def _on_enter(self, _event=None) -> None:
        if self._hover:
            return
        self._hover = True
        self._refresh_hover()

    def _on_leave(self, event=None) -> None:
        if self._pointer_inside(event):
            return
        if not self._hover:
            return
        self._hover = False
        self._refresh_hover()

    def _pointer_inside(self, event) -> bool:
        if event is None:
            return False
        try:
            under = self.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return False
        current = under
        while current is not None:
            if current is self:
                return True
            parent_name = current.winfo_parent()
            if not parent_name:
                return False
            try:
                current = current.nametowidget(parent_name)
            except (KeyError, tk.TclError):
                return False
        return False

    def _refresh_hover(self) -> None:
        bg = ACCENT_SOFT if self._hover else BG
        fg = ACCENT if self._hover else TEXT
        shortcut_fg = ACCENT if self._hover else MUTED
        self.configure(
            bg=bg,
            highlightbackground=ACCENT if self._hover else BORDER,
        )
        self._body.configure(bg=bg)
        self._icon.configure(bg=bg)
        self._text.configure(bg=bg)
        self._title.configure(bg=bg, fg=fg)
        self._shortcut.configure(bg=bg, fg=shortcut_fg)

    def set_shortcut(self, text: str) -> None:
        self._shortcut.configure(text=text)
        if text:
            if not self._shortcut.winfo_manager():
                self._shortcut.pack(anchor="w", pady=(1, 0))
        else:
            self._shortcut.pack_forget()


class ActionLink(tk.Frame):
    """Compact icon-above-label action used in recent screenshot rows."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        icon_name: str,
        text: str,
        command: Callable[[], None],
        fonts: Fonts,
        icons: IconSet,
        bg: str = BG,
        color: str = MUTED,
        hover_color: str = ACCENT,
    ) -> None:
        super().__init__(master, bg=bg, cursor="hand2")
        self._icons = icons
        self._icon_name = icon_name
        self._command = command
        self._color = color
        self._hover_color = hover_color
        self._bg = bg
        self._icon = tk.Label(
            self,
            bg=bg,
            image=icons.get(icon_name, 17, color),
            cursor="hand2",
        )
        self._icon.pack()
        self._label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=color,
            font=fonts.u(9),
            cursor="hand2",
        )
        self._label.pack()
        bind_click_recursive(self, self._on_click)
        bind_hover_recursive(self, self._on_enter, self._on_leave)

    def _on_click(self, _event=None) -> None:
        self._command()

    def _on_enter(self, _event=None) -> None:
        self._icon.configure(
            image=self._icons.get(
                self._icon_name, 17, self._hover_color
            )
        )
        self._label.configure(fg=self._hover_color)

    def _on_leave(self, _event=None) -> None:
        self._icon.configure(
            image=self._icons.get(self._icon_name, 17, self._color)
        )
        self._label.configure(fg=self._color)


class ColorSwatch(tk.Canvas):
    """Round color swatch with an accent ring when selected."""

    def __init__(
        self,
        master: tk.Misc,
        color: str,
        command: Callable[[], None],
        *,
        bg: str = PANEL,
        size: int = 20,
    ) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._size = size
        self._color = color
        self._selected = False
        self._shape = self.create_oval(
            3, 3, size - 3, size - 3,
            fill=color,
            outline=BORDER,
            width=1,
        )
        self.bind("<Button-1>", lambda _event: command())

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        if self._selected:
            self.itemconfigure(
                self._shape,
                outline=ACCENT,
                width=2,
                fill=self._color,
            )
        else:
            self.itemconfigure(
                self._shape,
                outline=BORDER,
                width=1,
                fill=self._color,
            )


class FilterMenu:
    """Single-select popup menu backed by a ``StringVar``."""

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.StringVar,
        options,
        on_change: Callable[[], None],
    ) -> None:
        self.variable = variable
        self._on_change = on_change
        self.menu = tk.Menu(
            master,
            tearoff=0,
            bg=BG,
            fg=TEXT,
            activebackground=ACCENT_SOFT,
            activeforeground=ACCENT,
            bd=1,
            relief="solid",
        )
        for option in options:
            if option is None:
                self.menu.add_separator()
                continue
            label, value = option
            self.menu.add_radiobutton(
                label=label,
                value=value,
                variable=variable,
                command=self._on_change,
            )

    def popup(self, anchor: tk.Misc) -> None:
        try:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 4
            self.menu.tk_popup(x, y)
        finally:
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass
