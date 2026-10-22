"""Shared light theme helpers for Tkinter windows and plugins."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path

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


def center_on_screen(
    window: tk.Toplevel | tk.Tk, width: int, height: int, parent: tk.Misc | None = None
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
                x = max(0, min(x, window.winfo_screenwidth() - width))
                y = max(0, min(y, window.winfo_screenheight() - height))
                window.geometry(f"{width}x{height}+{x}+{y}")
                return
        except tk.TclError:
            pass
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
