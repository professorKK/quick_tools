"""Shared dark theme helpers for Tkinter windows and plugins."""

from __future__ import annotations

import ctypes
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
ON_ACCENT = "#ffffff"
DANGER = "#c5221f"
SUCCESS = "#15803d"
BUTTON = "#f1f3f5"
BUTTON_HOVER = "#e6e9ee"
BUTTON_PRESSED = "#d9dee5"
DISABLED_BG = "#f7f8fa"
DISABLED_TEXT = "#a5abb5"


@dataclass(frozen=True)
class Fonts:
    ui: str
    mono: str

    def u(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.ui, size, weight)

    def m(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.mono, size, weight)


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
    available = set(tkfont.families(root))
    if sys.platform == "win32":
        ui_candidates = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Arial")
        mono_candidates = ("Cascadia Mono", "Consolas", "Courier New")
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
    return Fonts(ui=ui, mono=mono)


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
        **kwargs,
    ) -> None:
        self._command = command
        self._enabled = True
        self._accent = accent
        self._normal_bg = bg or (ACCENT_DARK if accent else BUTTON)
        self._normal_fg = fg or (ON_ACCENT if accent else TEXT)
        self._hover_bg = hover_bg or (ACCENT_HOVER if accent else BUTTON_HOVER)
        self._press_bg = press_bg or (ACCENT_DARK if accent else BUTTON_PRESSED)
        self._disabled_fg = disabled_fg
        self._fonts = fonts
        super().__init__(
            master,
            text=text,
            bg=self._normal_bg,
            fg=self._normal_fg,
            activebackground=self._press_bg,
            activeforeground=ON_ACCENT if accent else TEXT,
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

    def _on_enter(self, _event=None) -> None:
        if self._enabled:
            self.configure(bg=self._hover_bg)

    def _on_leave(self, _event=None) -> None:
        if self._enabled:
            self.configure(bg=self._normal_bg)

    def _on_click(self, _event=None) -> None:
        if self._enabled:
            self.configure(bg=self._press_bg)

    def _on_release(self, _event=None) -> None:
        if not self._enabled:
            return
        self.configure(bg=self._hover_bg)
        self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self.configure(
                bg=ACCENT_DARK if self._accent else self._normal_bg,
                fg=self._normal_fg,
                cursor="hand2",
            )
        else:
            self.configure(bg=DISABLED_BG, fg=self._disabled_fg, cursor="")

    def set_active(self, active: bool) -> None:
        self._accent = active
        self._normal_bg = ACCENT_DARK if active else BUTTON
        self._normal_fg = ON_ACCENT if active else TEXT
        self._hover_bg = ACCENT_HOVER if active else BUTTON_HOVER
        self._press_bg = ACCENT_DARK if active else BUTTON_PRESSED
        self.configure(
            bg=ACCENT_DARK if active else self._normal_bg,
            fg=self._normal_fg,
            activeforeground=ON_ACCENT if active else TEXT,
        )
