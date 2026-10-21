"""A small always-on-top pin used by plugin windows."""

from __future__ import annotations

import sys
import tkinter as tk

from .logging_setup import get_logger
from .ui_theme import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_SOFT_HOVER,
    BG,
    BUTTON,
    MUTED,
    FlatButton,
    Fonts,
)

log = get_logger(__name__)


class PinButton(FlatButton):
    """Toggle ``-topmost`` on ``window`` and show the current state.

    The button is a ``FlatButton`` (a Label), so clicking it never steals
    focus from an Entry inside the plugin window.
    """

    def __init__(
        self,
        master: tk.Misc,
        window: tk.Toplevel | tk.Tk,
        fonts: Fonts,
        *,
        font_size: int = 12,
    ) -> None:
        self.window = window
        # Tk's -topmost attribute is ignored for overrideredirect windows on
        # X11 (the WM does not manage them) and reads back False, so keep the
        # user's choice ourselves there.
        self._pinned = False
        # Windows renders the color pin glyph; Linux CJK fonts often lack it,
        # so use a short text label there instead of showing a tofu box.
        label = "📌" if sys.platform == "win32" else "置顶"
        super().__init__(
            master,
            label,
            self.toggle,
            fonts=fonts,
            font_size=font_size,
            padx=4,
            pady=2,
            bg=BG,
            fg=MUTED,
            hover_bg=BUTTON,
            active_bg=ACCENT_SOFT,
            active_fg=ACCENT,
            active_hover_bg=ACCENT_SOFT_HOVER,
        )
        self.refresh()

    @property
    def pinned(self) -> bool:
        if sys.platform.startswith("linux"):
            return self._pinned
        try:
            return str(self.window.attributes("-topmost")) in {"1", "true", "True"}
        except tk.TclError:
            return False

    def refresh(self) -> None:
        """Synchronize the visual state with the window's actual state."""
        try:
            self.set_active(self.pinned)
        except tk.TclError:
            pass

    def toggle(self) -> None:
        pinned = not self.pinned
        self._pinned = pinned
        try:
            self.window.attributes("-topmost", pinned)
            if pinned:
                self.window.lift()
            self.set_active(pinned)
        except tk.TclError:
            return
        log.info("窗口置顶：%s", "已开启" if pinned else "已取消")
