"""Shared light theme helpers for Tkinter windows and plugins."""

from __future__ import annotations

import ctypes
import re
import shutil
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BG = "#ffffff"
PANEL = "#f6f7f9"
PANEL_ALT = "#ffffff"
ROW = "#ffffff"
ROW_ACTIVE = "#eef4ff"
BORDER = "#d8dde5"
TEXT = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#2563eb"
ACCENT_HOVER = "#3b82f6"
ACCENT_DARK = "#1d4ed8"
ACCENT_SOFT = "#eef4ff"
ACCENT_SOFT_HOVER = "#dbeafe"
BADGE_BG = "#e3edff"
BADGE_BG_HOVER = "#d6e4ff"
ON_ACCENT = "#ffffff"
DANGER = "#c5221f"
SUCCESS = "#15803d"
BUTTON = "#f1f3f5"
BUTTON_HOVER = "#e6e9ee"
BUTTON_PRESSED = "#d9dee5"
DISABLED_BG = "#f7f8fa"
DISABLED_TEXT = "#a5abb5"
# Settings surfaces: a soft page canvas with white rounded cards on top.
SURFACE = "#f3f5f9"
CARD_BG = "#ffffff"
CARD_BORDER = "#e4e8ef"
DIVIDER = "#eef1f5"


@dataclass(frozen=True)
class Fonts:
    ui: str
    mono: str
    # Bundled Material Icons family used for title bar pin/settings glyphs;
    # empty when the font could not be loaded and callers should draw the
    # Canvas fallback.
    symbol: str = ""

    def u(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.ui, size, weight)

    def m(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.mono, size, weight)


def round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    fill: str,
    *,
    outline: str = "",
    width: int = 1,
) -> int:
    """Draw a smooth rounded rectangle on a Canvas and return its item id."""
    radius = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(
        points,
        smooth=True,
        splinesteps=18,
        fill=fill,
        outline=outline,
        width=width,
    )


def enable_high_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


def pick_fonts(root: tk.Misc) -> Fonts:
    # Register the bundled icon font before enumerating families so Tk sees
    # it on both Windows and X11. Both platforms then use the same glyphs.
    bundled_symbol = ""
    try:
        from .icon_font import ensure_loaded

        bundled_symbol = ensure_loaded()
    except Exception:
        pass
    available = set(tkfont.families(root))
    symbol_candidates: tuple[str, ...] = ()
    if sys.platform == "win32":
        ui_candidates = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial")
        mono_candidates = ("Cascadia Mono", "Consolas", "Courier New")
        # Only used if the bundled font could not be loaded (e.g. a broken
        # package), so a Windows install still gets real glyphs.
        symbol_candidates = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
    else:
        ui_candidates = (
            "Noto Sans CJK SC",
            "Noto Sans CJK HK",
            "WenQuanYi Micro Hei",
            "Ubuntu",
            "DejaVu Sans",
        )
        mono_candidates = (
            "JetBrains Mono",
            "Noto Sans Mono",
            "Ubuntu Mono",
            "DejaVu Sans Mono",
            "Liberation Mono",
        )
    ui = next((name for name in ui_candidates if name in available), "TkDefaultFont")
    mono = next(
        (name for name in mono_candidates if name in available),
        tkfont.nametofont("TkFixedFont").actual("family"),
    )
    if bundled_symbol and bundled_symbol in available:
        symbol = bundled_symbol
    else:
        symbol = next(
            (name for name in symbol_candidates if name in available), ""
        )
    return Fonts(ui=ui, mono=mono, symbol=symbol)


def _x11_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Best-effort XRandR monitor list, without importing python-xlib."""
    if not sys.platform.startswith("linux"):
        return []
    xrandr = shutil.which("xrandr")
    if not xrandr:
        return []
    try:
        result = subprocess.run(
            [xrandr, "--listmonitors"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    rectangles: list[tuple[int, int, int, int]] = []
    pattern = re.compile(
        r"^\s*\d+:\s+[+*]*\S+\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)"
    )
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        width, height, x, y = (int(value) for value in match.groups())
        rectangles.append((x, y, width, height))
    return rectangles


_x11_monitor_cache: tuple[float, list[tuple[int, int, int, int]]] = (0.0, [])


def work_area_for_point(
    point: tuple[int, int] | None,
) -> tuple[int, int, int, int] | None:
    """Return the monitor work area containing ``point`` when known.

    The fallback is None so callers keep using Tk's primary-screen bounds.
    """
    if point is None:
        return None
    if sys.platform == "win32":
        try:
            from .win32_window import work_area_at_point

            return work_area_at_point(*point)
        except Exception:
            return None
    if sys.platform.startswith("linux"):
        global _x11_monitor_cache
        now = time.monotonic()
        cached_at, rectangles = _x11_monitor_cache
        if now - cached_at > 5.0:
            rectangles = _x11_monitor_rects()
            _x11_monitor_cache = (now, rectangles)
        for x, y, width, height in rectangles:
            if x <= point[0] < x + width and y <= point[1] < y + height:
                return (x, y, width, height)
    return None


def center_on_screen(
    window: tk.Toplevel | tk.Tk,
    width: int,
    height: int,
    parent: tk.Misc | None = None,
    *,
    anchor_point: tuple[int, int] | None = None,
) -> None:
    window.update_idletasks()
    if parent is not None:
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            if pw > 10 and ph > 10:
                x = px + (pw - width) // 2
                y = py + (ph - height) // 2
                area = work_area_for_point((px, py)) or (
                    0,
                    0,
                    window.winfo_screenwidth(),
                    window.winfo_screenheight(),
                )
                left, top, area_width, area_height = area
                x = max(left, min(x, left + max(0, area_width - width)))
                y = max(top, min(y, top + max(0, area_height - height)))
                window.geometry(f"{width}x{height}+{x}+{y}")
                return
        except tk.TclError:
            pass
    point = anchor_point
    if point is None:
        try:
            point = (window.winfo_pointerx(), window.winfo_pointery())
        except tk.TclError:
            point = None
    area = work_area_for_point(point)
    if area is not None:
        left, top, area_width, area_height = area
        x = left + max(0, (area_width - width) // 2)
        y = top + max(0, (area_height - height) // 2)
    else:
        x = max(0, (window.winfo_screenwidth() - width) // 2)
        y = max(0, (window.winfo_screenheight() - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def open_in_file_manager(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import os

        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_url(url: str) -> bool:
    """Open ``url`` in the platform default browser.

    Returns ``False`` when no browser could be launched (for example on a
    headless machine) so callers can show a manual fallback instead of
    crashing the UI.
    """
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def reveal_in_file_manager(path: Path) -> None:
    """Open the file manager with ``path`` selected where the platform allows.

    Windows Explorer supports ``/select,``; Linux desktops that implement
    ``org.freedesktop.FileManager1`` can select the item via DBus. Otherwise
    fall back to opening the containing folder.
    """
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"文件已移动或删除：{target}")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{target}"])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
        return

    dbus_send = shutil.which("dbus-send")
    if dbus_send:
        try:
            result = subprocess.run(
                [
                    dbus_send,
                    "--session",
                    "--dest=org.freedesktop.FileManager1",
                    "--type=method_call",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:{target.resolve().as_uri()}",
                    "string:",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    open_in_file_manager(target.parent)


class FlatButton(tk.Label):
    """A focus-free button so keypad clicks never steal the Entry caret."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        *,
        fonts: Fonts | None = None,
        accent: bool = False,
        font_size: int = 12,
        padx: int = 10,
        pady: int = 8,
        bg: str | None = None,
        fg: str | None = None,
        hover_bg: str | None = None,
        press_bg: str | None = None,
        disabled_fg: str = DISABLED_TEXT,
        image=None,
        active_image=None,
        disabled_image=None,
        active_bg: str | None = None,
        active_fg: str | None = None,
        active_hover_bg: str | None = None,
        **kwargs,
    ) -> None:
        self._command = command
        self._enabled = True
        self._pressed = False
        self._accent = accent
        self._active = bool(accent)
        self._idle_bg = bg or (ACCENT_DARK if accent else BUTTON)
        self._idle_fg = fg or (ON_ACCENT if accent else TEXT)
        self._idle_hover_bg = hover_bg or (
            ACCENT_HOVER if accent else BUTTON_HOVER
        )
        self._idle_press_bg = press_bg or (
            ACCENT_DARK if accent else BUTTON_PRESSED
        )
        self._active_bg = active_bg or ACCENT_DARK
        self._active_fg = active_fg or ON_ACCENT
        self._active_hover_bg = active_hover_bg or ACCENT_HOVER
        self._idle_image = image
        self._active_image = active_image
        self._disabled_image = disabled_image
        self._disabled_fg = disabled_fg
        self._fonts = fonts
        if image is not None and "compound" not in kwargs:
            kwargs["compound"] = "left"
        super().__init__(
            master,
            text=text,
            image=image,
            bg=self._current_bg(),
            fg=self._current_fg(),
            activebackground=self._current_press_bg(),
            activeforeground=self._current_fg(),
            font=(fonts or Fonts("TkDefaultFont", "TkFixedFont")).u(font_size),
            padx=padx,
            pady=pady,
            cursor="hand2",
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _current_bg(self) -> str:
        return self._active_bg if self._active else self._idle_bg

    def _current_fg(self) -> str:
        return self._active_fg if self._active else self._idle_fg

    def _current_hover_bg(self) -> str:
        return self._active_hover_bg if self._active else self._idle_hover_bg

    def _current_press_bg(self) -> str:
        return self._active_bg if self._active else self._idle_press_bg

    def _current_image(self):
        if self._active and self._active_image is not None:
            return self._active_image
        return self._idle_image

    def _apply_style(self) -> None:
        self.configure(
            bg=self._current_bg(),
            fg=self._current_fg(),
            activebackground=self._current_press_bg(),
            activeforeground=self._current_fg(),
            image=self._current_image() if self._current_image() is not None else "",
        )

    def _on_enter(self, _event=None) -> None:
        if self._enabled:
            self.configure(bg=self._current_hover_bg())

    def _on_leave(self, _event=None) -> None:
        self._pressed = False
        if self._enabled:
            self.configure(bg=self._current_bg())

    def _on_click(self, _event=None) -> None:
        if self._enabled:
            self._pressed = True
            self.configure(bg=self._current_press_bg())

    def _on_release(self, _event=None) -> None:
        # A window opened on ButtonPress (for example a launcher card) can
        # receive the ButtonRelease under the pointer. Only act when this
        # widget saw the matching press; otherwise a stray release would
        # trigger phantom clicks in the newly opened window.
        pressed = self._pressed
        self._pressed = False
        if not self._enabled:
            return
        self.configure(bg=self._current_hover_bg())
        if pressed:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._pressed = False
        if enabled:
            self._apply_style()
            self.configure(cursor="hand2")
        else:
            image = self._disabled_image or self._idle_image
            self.configure(
                bg=DISABLED_BG,
                fg=self._disabled_fg,
                cursor="",
                image=image if image is not None else "",
            )

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._accent = self._active
        if self._enabled:
            self._apply_style()

    def set_face(self, *, image=None, text: str = "") -> None:
        """Switch between an icon and a text glyph without changing colors."""
        self._idle_image = image
        self._active_image = None
        self._disabled_image = None
        self.configure(text=text)
        if self._enabled:
            self._apply_style()
        else:
            self.configure(
                bg=DISABLED_BG,
                fg=self._disabled_fg,
                image=image if image is not None else "",
            )

    def set_idle_colors(
        self,
        *,
        bg: str | None = None,
        fg: str | None = None,
        hover_bg: str | None = None,
        press_bg: str | None = None,
    ) -> None:
        """Update the non-active palette, e.g. when a row changes background."""
        if bg is not None:
            self._idle_bg = bg
        if fg is not None:
            self._idle_fg = fg
        if hover_bg is not None:
            self._idle_hover_bg = hover_bg
        if press_bg is not None:
            self._idle_press_bg = press_bg
        if self._enabled:
            self._apply_style()


class LinkLabel(tk.Label):
    """A focus-free text link that underlines on hover and opens on click.

    Used for external addresses (such as the GitHub repository) that must be
    visible as plain text and clickable without stealing the keyboard focus
    from entries in the same window.
    """

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        fonts: Fonts | None = None,
        font_size: int = 9,
        fg: str = ACCENT,
        bg: str = BG,
        active_fg: str = ACCENT_DARK,
        **kwargs,
    ) -> None:
        self._command = command
        self._enabled = True
        self._pressed = False
        family, size, weight = (
            fonts or Fonts("TkDefaultFont", "TkFixedFont")
        ).u(font_size)
        self._idle_font = (family, size, weight)
        style = " ".join(
            part for part in (weight, "underline") if part and part != "normal"
        )
        self._hover_font = (family, size, style or "underline")
        super().__init__(
            master,
            text=text,
            bg=bg,
            fg=fg,
            activeforeground=active_fg,
            font=self._idle_font,
            bd=0,
            highlightthickness=0,
            takefocus=0,
            cursor="hand2",
            **kwargs,
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def invoke(self) -> None:
        if self._enabled:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._pressed = False
        self.configure(cursor="hand2" if self._enabled else "")

    def _on_enter(self, _event=None) -> None:
        if self._enabled:
            self.configure(font=self._hover_font)

    def _on_leave(self, _event=None) -> None:
        self._pressed = False
        self.configure(font=self._idle_font)

    def _on_press(self, _event=None) -> None:
        if self._enabled:
            self._pressed = True

    def _on_release(self, _event=None) -> None:
        # Only react to a release that follows a press on this link, so a
        # window opening under the pointer cannot leave a phantom click.
        pressed = self._pressed
        self._pressed = False
        if pressed and self._enabled:
            self.invoke()
