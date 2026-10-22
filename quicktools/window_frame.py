"""Frameless window frame shared by QuickTools plugins.

Every plugin window uses the same custom title bar instead of the operating
system caption:

* left: plugin icon and name;
* right: settings, pin, minimize, maximize and close.

``WindowFrame`` also owns the behaviour the window manager used to provide:
dragging, double-click maximize, resize grips, taskbar integration and
Windows 11 rounded corners.  Plugins only need to build their content; the
launcher attaches the frame automatically.

The module is intentionally dependency-free apart from Tk so external plugin
authors can import it safely:

    from quicktools.window_frame import WindowFrame

For a secondary window (a dialog or an editor) create the Toplevel and attach
a frame before building content:

    window = tk.Toplevel(master)
    frame = WindowFrame(
        window,
        title="编辑截图",
        icon="S",
        fonts=fonts,
        dialog=True,
        resizable=True,
        on_close=window.destroy,
    )
    tk.Frame(window).pack(fill="both", expand=True)
"""

from __future__ import annotations

import re
import sys
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from . import win32_window
from .logging_setup import get_logger
from .ui_icons import draw_gear, draw_pin, draw_symbol
from .ui_theme import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_SOFT_HOVER,
    BADGE_BG,
    BG,
    BORDER,
    BUTTON_HOVER,
    DANGER,
    MUTED,
    PANEL,
    TEXT,
    Fonts,
    pick_fonts,
    round_rect,
)

log = get_logger(__name__)

TITLEBAR_HEIGHT = 44
DIALOG_TITLEBAR_HEIGHT = 40
BUTTON_SIZE = 30
GRIP_SIZE = 5
CORNER_SIZE = 11
# Coalesce resize motion into ~60 updates per second.  Applying every raw
# mouse event makes Tk queue more geometry changes than it can repaint, and
# the window edge then visibly trails the pointer.
RESIZE_INTERVAL_MS = 15

# Button order inside the title bar, from left to right.
CAPTION_BUTTONS = ("settings", "pin", "minimize", "maximize", "close")

_GEOMETRY_SIZE = re.compile(r"^\s*(\d+)x(\d+)")

_TOOLTIPS = {
    "settings": "设置",
    "pin": "置顶",
    "minimize": "隐藏",
    "maximize": "放大",
    "restore": "还原",
    "close": "关闭",
}


# Backwards-compatible alias for the old private helper. New code should use
# ``quicktools.ui_theme.round_rect`` directly.
_round_rect = round_rect


def _iter_descendants(widget: tk.Misc):
    for child in widget.winfo_children():
        yield child
        yield from _iter_descendants(child)


class Tooltip:
    """Small delayed tooltip used by title bar buttons and compact cards.

    Pass ``container`` to bind the whole widget tree of a composite control to
    one tooltip: hovering any child keeps the tip visible instead of flickering
    when the pointer moves between the container and its children.
    """

    def __init__(
        self,
        widget: tk.Misc,
        text: str,
        *,
        delay_ms: int = 480,
        fonts: Fonts | None = None,
        container: tk.Misc | None = None,
    ) -> None:
        self.widget = widget
        self.container = container or widget
        self.text = text
        self.delay_ms = delay_ms
        self.fonts = fonts or pick_fonts(widget)
        self._job: str | None = None
        self._tip: tk.Toplevel | None = None
        targets = [self.container]
        if container is not None:
            targets.extend(_iter_descendants(container))
        for target in targets:
            target.bind("<Enter>", self._schedule, add="+")
            target.bind("<Leave>", self._on_leave, add="+")
            target.bind("<ButtonPress>", self.hide, add="+")
            target.bind("<Unmap>", self.hide, add="+")
            target.bind("<Destroy>", self._on_destroy, add="+")

    def _schedule(self, _event=None) -> None:
        if self._tip is not None:
            return
        self.hide()
        try:
            self._job = self.widget.after(self.delay_ms, self.show)
        except tk.TclError:
            self._job = None

    def schedule(self) -> None:
        """Start the hover delay, e.g. for a lazily created tooltip."""
        self._schedule()

    def _pointer_inside(self, event) -> bool:
        if event is None:
            return False
        try:
            under = self.widget.winfo_containing(
                event.x_root, event.y_root
            )
        except tk.TclError:
            return False
        current = under
        while current is not None:
            if current is self.container:
                return True
            parent_name = current.winfo_parent()
            if not parent_name:
                return False
            try:
                current = current.nametowidget(parent_name)
            except (KeyError, tk.TclError):
                return False
        return False

    def _on_leave(self, event) -> None:
        if self._pointer_inside(event):
            return
        self.hide()

    def show(self) -> None:
        self._job = None
        if self._tip is not None or not self.text:
            return
        try:
            if not self.widget.winfo_viewable():
                return
        except tk.TclError:
            return
        try:
            tip = tk.Toplevel(self.widget)
            tip.withdraw()
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tip.configure(bg=BORDER)
            win32_window.prepare_tool_window(tip)
            label = tk.Label(
                tip,
                text=self.text,
                bg=PANEL,
                fg=TEXT,
                padx=9,
                pady=5,
                font=self.fonts.u(9),
            )
            label.pack(padx=1, pady=1)
            tip.update_idletasks()
            width = tip.winfo_reqwidth()
            height = tip.winfo_reqheight()
            x = self.widget.winfo_rootx() + (self.widget.winfo_width() - width) // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            screen_w = tip.winfo_screenwidth()
            screen_h = tip.winfo_screenheight()
            x = max(4, min(x, screen_w - width - 4))
            y = max(4, min(y, screen_h - height - 4))
            tip.geometry(f"+{x}+{y}")
            tip.deiconify()
            self._tip = tip
        except tk.TclError:
            log.debug("显示提示失败", exc_info=True)
            self.hide()

    def hide(self, _event=None) -> None:
        job = self._job
        self._job = None
        if job is not None:
            try:
                self.widget.after_cancel(job)
            except tk.TclError:
                pass
        tip = self._tip
        self._tip = None
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.widget or event.widget is self.container:
            self.hide()


class TitleBarButton(tk.Canvas):
    """Icon-only title bar button that never takes keyboard focus."""

    def __init__(
        self,
        master: tk.Misc,
        command: Callable[[], None],
        *,
        kind: str,
        fonts: Fonts,
        size: int = BUTTON_SIZE,
        danger: bool = False,
        tooltip: str | None = None,
    ) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            bg=PANEL,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._command = command
        self._kind = kind
        self._fonts = fonts
        self._size = size
        self._danger = danger
        self._hover = False
        self._pressed = False
        self._active = False
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.tooltip = Tooltip(
            self, tooltip or _TOOLTIPS.get(kind, ""), fonts=fonts
        )

    # --------------------------------------------------------------- paint
    def _colors(self) -> tuple[str, str]:
        if self._active:
            if self._hover:
                return ACCENT_SOFT_HOVER, ACCENT
            return ACCENT_SOFT, ACCENT
        if self._pressed:
            return (DANGER if self._danger else BUTTON_HOVER), (
                "#ffffff" if self._danger else TEXT
            )
        if self._hover:
            return (DANGER if self._danger else BUTTON_HOVER), (
                "#ffffff" if self._danger else TEXT
            )
        return PANEL, MUTED

    def _draw(self) -> None:
        bg, fg = self._colors()
        self.configure(bg=bg)
        self.delete("all")
        size = self._size
        x = y = size / 2
        line = max(1.4, size / 20)
        pad = size * 0.32
        try:
            if self._kind == "minimize":
                self.create_line(
                    pad,
                    size / 2,
                    size - pad,
                    size / 2,
                    fill=fg,
                    width=line,
                )
            elif self._kind == "maximize":
                self.create_rectangle(
                    pad,
                    pad,
                    size - pad,
                    size - pad,
                    outline=fg,
                    width=line,
                )
            elif self._kind == "restore":
                shift = size * 0.1
                self.create_rectangle(
                    pad,
                    pad + shift,
                    size - pad - shift,
                    size - pad,
                    outline=fg,
                    width=line,
                )
                self.create_line(
                    pad + shift,
                    pad + shift,
                    pad + shift,
                    pad,
                    size - pad,
                    pad,
                    size - pad,
                    size - pad - shift,
                    fill=fg,
                    width=line,
                )
            elif self._kind == "close":
                self.create_line(
                    pad, pad, size - pad, size - pad, fill=fg, width=line
                )
                self.create_line(
                    size - pad, pad, pad, size - pad, fill=fg, width=line
                )
            elif self._kind == "pin":
                if not draw_symbol(
                    self,
                    "pin",
                    cx=x,
                    cy=y,
                    size=size,
                    fg=fg,
                    fonts=self._fonts,
                ):
                    draw_pin(self, size, fg)
            elif self._kind == "settings":
                if not draw_symbol(
                    self,
                    "settings",
                    cx=x,
                    cy=y,
                    size=size,
                    fg=fg,
                    fonts=self._fonts,
                ):
                    draw_gear(self, size, fg, bg, cx=x, cy=y)
        except tk.TclError:
            pass

    # ------------------------------------------------------------- events
    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, _event=None) -> None:
        self._pressed = True
        self._draw()

    def _on_release(self, _event=None) -> None:
        pressed = self._pressed
        self._pressed = False
        self._hover = True
        self._draw()
        if pressed:
            self._command()

    def set_active(self, active: bool) -> None:
        if self._active != bool(active):
            self._active = bool(active)
            self._draw()

    def set_kind(self, kind: str) -> None:
        if self._kind != kind:
            self._kind = kind
            self.tooltip.text = _TOOLTIPS.get(kind, self.tooltip.text)
            self._draw()


class ResizeGrips:
    """Eight invisible edge grips that provide native-feeling resizing."""

    _CURSORS = {
        "nw": ("top_left_corner", "size_nw_se"),
        "ne": ("top_right_corner", "size_ne_sw"),
        "sw": ("bottom_left_corner", "size_ne_sw"),
        "se": ("bottom_right_corner", "size_nw_se"),
        "n": ("sb_v_double_arrow", "size_ns"),
        "s": ("sb_v_double_arrow", "size_ns"),
        "w": ("sb_h_double_arrow", "size_we"),
        "e": ("sb_h_double_arrow", "size_we"),
    }

    def __init__(
        self, window: tk.Misc, *, background: str | None = None
    ) -> None:
        self.window = window
        self._background = background
        self._grips: list[tuple[tk.Frame, dict]] = []
        self._start = (0, 0, 0, 0, 0, 0)
        self._direction = ""
        self._pending: tuple[int, int] | None = None
        self._resize_job: str | None = None
        self._build()

    def _build(self) -> None:
        # (direction, place options, background). Edge grips span the whole
        # edge; corner grips are created last so they sit above the edges.
        specs = [
            ("n", {"x": 0, "y": 0, "relwidth": 1.0, "height": GRIP_SIZE}, PANEL),
            (
                "s",
                {"x": 0, "rely": 1.0, "y": -GRIP_SIZE, "relwidth": 1.0,
                 "height": GRIP_SIZE},
                BG,
            ),
            (
                "w",
                {"x": 0, "y": 0, "relheight": 1.0, "width": GRIP_SIZE},
                BG,
            ),
            (
                "e",
                {"relx": 1.0, "x": -GRIP_SIZE, "y": 0, "relheight": 1.0,
                 "width": GRIP_SIZE},
                BG,
            ),
            ("nw", {"x": 0, "y": 0, "width": CORNER_SIZE, "height": CORNER_SIZE}, PANEL),
            (
                "ne",
                {"relx": 1.0, "x": -CORNER_SIZE, "y": 0, "width": CORNER_SIZE,
                 "height": CORNER_SIZE},
                PANEL,
            ),
            (
                "sw",
                {"x": 0, "rely": 1.0, "y": -CORNER_SIZE, "width": CORNER_SIZE,
                 "height": CORNER_SIZE},
                BG,
            ),
            (
                "se",
                {"relx": 1.0, "x": -CORNER_SIZE, "rely": 1.0,
                 "y": -CORNER_SIZE, "width": CORNER_SIZE,
                 "height": CORNER_SIZE},
                BG,
            ),
        ]
        for direction, options, background in specs:
            grip = tk.Frame(
                self.window,
                bg=self._background or background,
                cursor=self._cursor(direction),
            )
            grip.place(**options)
            grip.bind(
                "<ButtonPress-1>",
                lambda event, d=direction: self._on_press(event, d),
            )
            grip.bind("<B1-Motion>", self._on_motion)
            grip.bind("<ButtonRelease-1>", self._on_release)
            self._grips.append((grip, options))

    def _cursor(self, direction: str) -> str:
        names = self._CURSORS.get(direction, ("", ""))
        for name in (names[1], names[0]):
            if not name:
                continue
            try:
                # Validate the cursor against this Tk build.
                tk.Canvas(self.window, cursor=name).destroy()
                return name
            except tk.TclError:
                continue
        return ""

    def raise_grips(self) -> None:
        for grip, _options in self._grips:
            try:
                grip.lift()
            except tk.TclError:
                pass

    def set_enabled(self, enabled: bool) -> None:
        for grip, options in self._grips:
            try:
                if enabled:
                    grip.place(**options)
                else:
                    grip.place_forget()
            except tk.TclError:
                pass
        if enabled:
            self.raise_grips()

    # ------------------------------------------------------------- resize
    def _on_press(self, event: tk.Event, direction: str) -> None:
        self._cancel_resize_job()
        self._pending = None
        try:
            self._direction = direction
            self._start = (
                event.x_root,
                event.y_root,
                self.window.winfo_x(),
                self.window.winfo_y(),
                self.window.winfo_width(),
                self.window.winfo_height(),
            )
        except tk.TclError:
            pass

    def _on_motion(self, event: tk.Event) -> None:
        if not self._direction:
            return
        self._pending = (event.x_root, event.y_root)
        if self._resize_job is not None:
            return
        try:
            self._resize_job = self.window.after(
                RESIZE_INTERVAL_MS, self._flush_resize
            )
        except tk.TclError:
            self._resize_job = None
            self._flush_resize()

    def _cancel_resize_job(self) -> None:
        job = self._resize_job
        self._resize_job = None
        if job is not None:
            try:
                self.window.after_cancel(job)
            except tk.TclError:
                pass

    def _flush_resize(self) -> None:
        self._resize_job = None
        pending = self._pending
        self._pending = None
        if pending is None or not self._direction:
            return
        self._apply_geometry(*pending)

    def _apply_geometry(self, x_root: int, y_root: int) -> None:
        start_x, start_y, x, y, width, height = self._start
        dx = x_root - start_x
        dy = y_root - start_y
        min_width, min_height = self._min_size()
        left, top = x, y
        right, bottom = x + width, y + height
        if "e" in self._direction:
            right = x + max(min_width, width + dx)
        if "s" in self._direction:
            bottom = y + max(min_height, height + dy)
        if "w" in self._direction:
            left = x + min(dx, width - min_width)
        if "n" in self._direction:
            top = y + min(dy, height - min_height)
        try:
            self.window.geometry(
                f"{max(1, right - left)}x{max(1, bottom - top)}"
                f"+{left}+{top}"
            )
        except tk.TclError:
            pass

    def _on_release(self, _event=None) -> None:
        self._cancel_resize_job()
        pending = self._pending
        self._pending = None
        if pending is not None and self._direction:
            # Apply the last pointer position so the window edge finishes
            # exactly under the cursor.
            self._apply_geometry(*pending)
        self._direction = ""

    def _min_size(self) -> tuple[int, int]:
        try:
            width, height = self.window.wm_minsize()
            return max(1, int(width)), max(1, int(height))
        except tk.TclError:
            return 1, 1


def make_frameless(
    window: tk.Misc,
    *,
    app_window: bool = True,
    rounded: bool = True,
) -> None:
    """Remove native decorations and restore taskbar/round-corner behaviour."""
    try:
        window.overrideredirect(True)
    except tk.TclError:
        return
    if app_window:
        win32_window.prepare_top_level(window)
    else:
        win32_window.prepare_tool_window(window)
    if rounded:
        win32_window.enable_rounded_corners(window)


def enable_drag(
    widget: tk.Misc,
    window: tk.Misc,
    *,
    on_double_click: Callable[[], None] | None = None,
) -> None:
    """Drag ``window`` by pressing and moving the given widget."""
    state: dict[str, int] = {}

    def press(event: tk.Event) -> None:
        try:
            state["x"] = event.x_root
            state["y"] = event.y_root
            state["wx"] = window.winfo_x()
            state["wy"] = window.winfo_y()
        except tk.TclError:
            state.clear()

    def motion(event: tk.Event) -> None:
        if "x" not in state:
            return
        try:
            x = state["wx"] + event.x_root - state["x"]
            y = state["wy"] + event.y_root - state["y"]
            window.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def release(_event=None) -> None:
        state.clear()

    widget.bind("<ButtonPress-1>", press, add="+")
    widget.bind("<B1-Motion>", motion, add="+")
    widget.bind("<ButtonRelease-1>", release, add="+")
    if on_double_click is not None:
        widget.bind("<Double-Button-1>", lambda _e: on_double_click(), add="+")


class WindowFrame:
    """Attach the QuickTools title bar and frameless behaviour to a Toplevel."""

    def __init__(
        self,
        window: tk.Toplevel,
        *,
        title: str,
        icon: str = "◆",
        fonts: Fonts | None = None,
        subtitle: str = "",
        on_settings: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        pin: bool = True,
        minimize: bool = True,
        maximize: bool = True,
        resizable: bool = True,
        dialog: bool = False,
    ) -> None:
        self.window = window
        self.fonts = fonts or pick_fonts(window)
        self._title = title
        self._subtitle = subtitle
        self._on_settings = on_settings
        self._on_close = on_close
        self._dialog = dialog
        self._pin_enabled = pin
        self._minimize_enabled = minimize
        self._maximize_enabled = maximize
        self._resizable = resizable
        self._maximized = False
        # Tk's -topmost attribute is ignored for overrideredirect windows on
        # X11, so track the user's choice instead of reading it back.
        self._pinned = False
        self._restore_geometry: str | None = None
        self._raise_job: str | None = None
        self._tooltips: list[Tooltip] = []
        self._build_buttons: dict[str, TitleBarButton] = {}

        make_frameless(
            window, app_window=not dialog, rounded=True
        )
        self._build_titlebar()
        self._grips = ResizeGrips(window) if resizable else None
        self._install_events(icon)

    # --------------------------------------------------------------- build
    def _build_titlebar(self) -> None:
        height = (
            DIALOG_TITLEBAR_HEIGHT if self._dialog else TITLEBAR_HEIGHT
        )
        self.bar = tk.Frame(self.window, bg=PANEL, height=height)
        self.bar.pack(side="top", fill="x")
        self.bar.pack_propagate(False)

        self._bar_inner = tk.Frame(self.bar, bg=PANEL)
        self._bar_inner.pack(fill="both", expand=True, padx=(10, 6))

        self._icon_canvas = tk.Canvas(
            self._bar_inner,
            width=26,
            height=26,
            bg=PANEL,
            highlightthickness=0,
            bd=0,
        )
        self._icon_canvas.pack(side="left", padx=(0, 8))
        self._icon_text = ""
        self._icon_font: tkfont.Font | None = None

        titles = tk.Frame(self._bar_inner, bg=PANEL)
        titles.pack(side="left", fill="x", expand=True)
        self._titles = titles
        self.title_label = tk.Label(
            titles,
            text=self._title,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(11, "bold"),
        )
        self.title_label.pack(side="left")
        self.subtitle_label: tk.Label | None = None
        if self._subtitle:
            self.subtitle_label = tk.Label(
                titles,
                text=self._subtitle,
                bg=PANEL,
                fg=MUTED,
                anchor="w",
                font=self.fonts.u(9),
            )
            self.subtitle_label.pack(side="left", padx=(8, 0))

        self._buttons = tk.Frame(self._bar_inner, bg=PANEL)
        self._buttons.pack(side="right", padx=(8, 0))

        self.close_button: TitleBarButton | None = None
        self.maximize_button: TitleBarButton | None = None
        self.minimize_button: TitleBarButton | None = None
        self.pin_button: TitleBarButton | None = None
        self.settings_button: TitleBarButton | None = None

        # Packed right-to-left so CAPTION_BUTTONS reads left-to-right.
        self.close_button = self._add_button(
            "close", self.close, danger=True
        )
        if self._maximize_enabled and not self._dialog:
            self.maximize_button = self._add_button(
                "maximize", self.toggle_maximize
            )
        if self._minimize_enabled and not self._dialog:
            self.minimize_button = self._add_button(
                "minimize", self.minimize
            )
        if self._pin_enabled:
            self.pin_button = self._add_button("pin", self.toggle_pin)
        if self._on_settings is not None:
            self.settings_button = self._add_button(
                "settings", self.open_settings
            )

        self._bar_border = tk.Frame(self.window, bg=BORDER, height=1)
        self._bar_border.pack(side="top", fill="x")

    def _add_button(
        self,
        kind: str,
        command: Callable[[], None],
        *,
        danger: bool = False,
    ) -> TitleBarButton:
        button = TitleBarButton(
            self._buttons,
            command,
            kind=kind,
            fonts=self.fonts,
            danger=danger,
        )
        button.pack(side="right", padx=(2, 0))
        self._build_buttons[kind] = button
        self._tooltips.append(button.tooltip)
        return button

    def _install_events(self, icon: str) -> None:
        self.set_icon(icon)
        # Dragging and double-click maximize only apply to the bar itself;
        # the buttons keep their own click bindings.
        for widget in (
            self.bar,
            self._bar_inner,
            self._titles,
            self.title_label,
            self._icon_canvas,
        ):
            enable_drag(
                widget,
                self.window,
                on_double_click=(
                    self.toggle_maximize
                    if self._maximize_enabled and not self._dialog
                    else None
                ),
            )
        self.window.bind("<Map>", self._on_map, add="+")
        self.window.bind("<Destroy>", self._on_destroy, add="+")
        self.window.bind("<Alt-F4>", lambda _e: self.close(), add="+")
        self._schedule_grip_raise()

    def _schedule_grip_raise(self) -> None:
        self._raise_job = None
        try:
            self._raise_job = self.window.after_idle(self.raise_grips)
        except tk.TclError:
            self._raise_job = None

    def _on_map(self, event: tk.Event) -> None:
        if event.widget is not self.window:
            return
        # Tk may recreate the wrapper window when a withdrawn Toplevel is
        # mapped again; re-apply the taskbar/tool-window style to be safe.
        if self._dialog:
            win32_window.prepare_tool_window(self.window)
        else:
            win32_window.prepare_top_level(self.window)
        win32_window.enable_rounded_corners(self.window)
        self.refresh_pin()
        self.raise_grips()
        self._schedule_grip_raise()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.window:
            return
        job = self._raise_job
        self._raise_job = None
        if job is not None:
            try:
                self.window.after_cancel(job)
            except tk.TclError:
                pass
        for tooltip in self._tooltips:
            tooltip.hide()
    # --------------------------------------------------------------- state
    def set_icon(self, icon: str) -> None:
        self._icon_text = icon
        try:
            self._icon_canvas.delete("all")
            _round_rect(
                self._icon_canvas, 1, 1, 25, 25, 7, BADGE_BG
            )
            font = tkfont.Font(
                family=self.fonts.ui,
                size=10 if len(icon) > 1 else 13,
                weight="bold",
            )
            # Keep the named Tk font alive; otherwise Tk deletes it while the
            # canvas item still references it.
            self._icon_font = font
            self._icon_canvas.create_text(
                13,
                13,
                text=icon,
                fill=ACCENT,
                font=font,
            )
        except tk.TclError:
            pass

    def set_title(self, title: str) -> None:
        self._title = title
        try:
            self.title_label.configure(text=title)
        except tk.TclError:
            pass

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle = subtitle
        try:
            if self.subtitle_label is None:
                self.subtitle_label = tk.Label(
                    self._titles,
                    text=subtitle,
                    bg=PANEL,
                    fg=MUTED,
                    anchor="w",
                    font=self.fonts.u(9),
                )
                self.subtitle_label.pack(side="left", padx=(8, 0))
            else:
                self.subtitle_label.configure(text=subtitle)
        except tk.TclError:
            pass

    @property
    def pinned(self) -> bool:
        if sys.platform.startswith("linux"):
            return self._pinned
        try:
            return str(self.window.attributes("-topmost")) in {
                "1",
                "true",
                "True",
            }
        except tk.TclError:
            return False

    def refresh_pin(self) -> None:
        if self.pin_button is not None:
            self.pin_button.set_active(self.pinned)

    def toggle_pin(self) -> None:
        pinned = not self.pinned
        self._pinned = pinned
        try:
            self.window.attributes("-topmost", pinned)
            if pinned:
                self.window.lift()
        except tk.TclError:
            pass
        log.info(
            "插件窗口置顶：%s（%s）",
            "已开启" if pinned else "已取消",
            self._title,
        )
        self.refresh_pin()

    # ------------------------------------------------------------- actions
    def open_settings(self) -> None:
        if self._on_settings is not None:
            try:
                self._on_settings()
            except Exception:
                log.exception("打开插件设置失败")

    def minimize(self) -> None:
        for tooltip in self._tooltips:
            tooltip.hide()
        if win32_window.minimize(self.window):
            log.info("插件窗口已隐藏：%s", self._title)
            return
        iconified = False
        try:
            self.window.iconify()
            iconified = True
        except tk.TclError:
            # Tk rejects iconify() for overrideredirect windows ("override-
            # redirect flag is set"), and every QuickTools window is built
            # that way on X11.  Never return here: the title bar button is
            # labelled "隐藏", so it must still withdraw the window.
            iconified = False

        def hide_if_unmanaged() -> None:
            try:
                if self.window.winfo_viewable():
                    # Override-redirect windows are not managed by many X11
                    # window managers; withdrawing is the only fallback.
                    self.window.withdraw()
                    log.info("插件窗口已隐藏：%s", self._title)
            except tk.TclError:
                pass

        if not iconified:
            hide_if_unmanaged()
            return
        try:
            self.window.after(120, hide_if_unmanaged)
        except tk.TclError:
            pass

    def toggle_maximize(self) -> None:
        if self._maximized:
            self.restore()
        else:
            self.maximize()

    def maximize(self) -> None:
        if self._maximized or not self._maximize_enabled or self._dialog:
            return
        try:
            self._restore_geometry = self.window.geometry()
            area = win32_window.work_area(self.window)
            if area is None:
                x, y = 0, 0
                width = self.window.winfo_screenwidth()
                height = self.window.winfo_screenheight()
            else:
                x, y, width, height = area
            self._maximized = True
            self.window.geometry(f"{width}x{height}+{x}+{y}")
            if self.maximize_button is not None:
                self.maximize_button.set_kind("restore")
            if self._grips is not None:
                self._grips.set_enabled(False)
        except tk.TclError:
            self._maximized = False
            self._restore_geometry = None

    def restore(self) -> None:
        if not self._maximized:
            return
        geometry = self._restore_geometry
        self._maximized = False
        self._restore_geometry = None
        try:
            if geometry:
                self.window.geometry(geometry)
            if self.maximize_button is not None:
                self.maximize_button.set_kind("maximize")
            if self._grips is not None:
                self._grips.set_enabled(True)
        except tk.TclError:
            pass

    @property
    def maximized(self) -> bool:
        return self._maximized

    def normal_size(self) -> tuple[int, int] | None:
        """Return the size the window uses when not maximized.

        Used by the launcher to persist plugin window sizes.  While maximized
        the current geometry is the monitor work area, so the saved restore
        geometry is the useful value.
        """
        try:
            geometry = (
                self._restore_geometry
                if self._maximized and self._restore_geometry
                else self.window.wm_geometry()
            )
        except tk.TclError:
            return None
        match = _GEOMETRY_SIZE.match(geometry or "")
        if match is not None:
            width, height = int(match.group(1)), int(match.group(2))
        else:
            try:
                width = self.window.winfo_width()
                height = self.window.winfo_height()
            except tk.TclError:
                return None
        if width <= 1 or height <= 1:
            return None
        return width, height

    def close(self) -> None:
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                log.exception("关闭窗口失败")
                try:
                    self.window.destroy()
                except tk.TclError:
                    pass
            return
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def raise_grips(self) -> None:
        self._raise_job = None
        # The bar must stay above plugin content, but the invisible resize
        # grips must stay above the bar so the top edge/corners remain
        # draggable.
        try:
            self.bar.lift()
        except tk.TclError:
            pass
        if self._grips is not None:
            self._grips.raise_grips()
