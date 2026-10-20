"""Basic screenshot plugin settings dialog."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from quicktools.config import HotkeySpec
from quicktools.ui_theme import (
    BG,
    BORDER,
    FlatButton,
    MUTED,
    PANEL,
    TEXT,
    center_on_screen,
    pick_fonts,
)


if TYPE_CHECKING:
    from ..plugin import ScreenshotPlugin

log = logging.getLogger(__name__)

_MODIFIER_KEYSYMS = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Super_L": "super",
    "Super_R": "super",
    "Meta_L": "super",
    "Meta_R": "super",
}
_SPECIAL_KEYSYMS = {
    "space": "space",
    "Tab": "tab",
    "Return": "enter",
    "BackSpace": "backspace",
    "Delete": "delete",
    "Insert": "insert",
    "Home": "home",
    "End": "end",
    "Prior": "pageup",
    "Next": "pagedown",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
}
_FORMATS = (("PNG", "png"), ("JPEG", "jpeg"), ("WebP", "webp"))


def _key_from_keysym(keysym: str) -> str | None:
    if keysym in _SPECIAL_KEYSYMS:
        return _SPECIAL_KEYSYMS[keysym]
    lower = keysym.lower()
    if len(lower) == 1 and lower.isascii() and lower.isalnum():
        return lower
    if lower.startswith("f") and lower[1:].isdigit():
        number = int(lower[1:])
        if 1 <= number <= 20:
            return lower
    return None


class _HotkeyRecorder(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        fonts,
        on_apply: Callable[[HotkeySpec], None],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.fonts = fonts
        self.on_apply = on_apply
        self.on_done = on_done
        self._mods: set[str] = set()
        self._candidate: HotkeySpec | None = None
        self._closed = False
        self.title("录制截图快捷键")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self._build()
        center_on_screen(self, 460, 260, parent=master)
        self.after(30, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG, padx=20, pady=18)
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell,
            text="按下新的截图快捷键",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(14, "bold"),
        ).pack(anchor="w")
        tk.Label(
            shell,
            text="必须包含至少一个 Ctrl / Alt / Shift / Super 修饰键。按 Esc 取消。",
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(anchor="w", pady=(4, 12))
        self.preview_var = tk.StringVar(value="等待按键…")
        tk.Label(
            shell,
            textvariable=self.preview_var,
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.m(15, "bold"),
            padx=16,
            pady=12,
            anchor="center",
        ).pack(fill="x")
        self.hint_var = tk.StringVar(value="")
        tk.Label(
            shell,
            textvariable=self.hint_var,
            bg=BG,
            fg="#c5221f",
            font=self.fonts.u(9),
        ).pack(anchor="w", pady=(5, 8))
        buttons = tk.Frame(shell, bg=BG)
        buttons.pack(fill="x", pady=(8, 0))
        self.apply_button = FlatButton(
            buttons,
            "使用此快捷键",
            self._apply,
            fonts=self.fonts,
            accent=True,
            font_size=10,
            padx=14,
            pady=8,
        )
        self.apply_button.pack(side="right")
        self.apply_button.set_enabled(False)
        FlatButton(
            buttons,
            "取消",
            self._cancel,
            fonts=self.fonts,
            font_size=10,
            padx=14,
            pady=8,
        ).pack(side="right", padx=(0, 8))

    def _on_key_press(self, event: tk.Event) -> str:
        keysym = event.keysym
        if keysym == "Escape":
            self._cancel()
            return "break"
        modifier = _MODIFIER_KEYSYMS.get(keysym)
        if modifier:
            self._mods.add(modifier)
            return "break"
        key = _key_from_keysym(keysym)
        if key is None:
            self.hint_var.set(f"不支持按键：{keysym}")
            self._candidate = None
            self.apply_button.set_enabled(False)
            return "break"
        if not self._mods:
            self.hint_var.set("请同时按住 Ctrl / Alt / Shift / Super 等修饰键")
            self._candidate = None
            self.apply_button.set_enabled(False)
            return "break"
        try:
            candidate = HotkeySpec(tuple(self._mods), key)
        except ValueError as exc:
            self.hint_var.set(str(exc))
            self._candidate = None
            self.apply_button.set_enabled(False)
            return "break"
        self._candidate = candidate
        self.preview_var.set(candidate.display())
        self.hint_var.set("")
        self.apply_button.set_enabled(True)
        return "break"

    def _on_key_release(self, event: tk.Event) -> str:
        modifier = _MODIFIER_KEYSYMS.get(event.keysym)
        if modifier:
            self._mods.discard(modifier)
        return "break"

    def _apply(self) -> None:
        if self._candidate is None:
            return
        try:
            self.on_apply(self._candidate)
        except Exception as exc:
            messagebox.showerror("快捷键设置失败", str(exc), parent=self)
        self._finish()

    def _cancel(self) -> None:
        self._finish()

    def _finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_done()


class SettingsDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        plugin: "ScreenshotPlugin",
        on_saved: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.plugin = plugin
        self.on_saved = on_saved
        self.fonts = pick_fonts(self)
        self.settings = plugin.settings
        self._recording = False
        self.title("截图设置 · 快捷工具")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(620, 600)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self._build()
        height = min(820, max(620, int(self.winfo_screenheight() * 0.88)))
        center_on_screen(self, 700, height, parent=master)
        self.after(30, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG, padx=22, pady=18)
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell,
            text="截图设置",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(17, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        panel = tk.Frame(
            shell, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        panel.pack(fill="x")
        body = tk.Frame(panel, bg=PANEL, padx=16, pady=14)
        body.pack(fill="x")
        body.grid_columnconfigure(1, weight=1)

        row = 0
        tk.Label(
            body, text="保存目录", bg=PANEL, fg=TEXT, font=self.fonts.u(10)
        ).grid(row=row, column=0, sticky="w", pady=4)
        self.save_dir_var = tk.StringVar(value=str(self.settings.resolved_save_dir()))
        tk.Entry(
            body,
            textvariable=self.save_dir_var,
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
            font=self.fonts.u(10),
        ).grid(row=row, column=1, sticky="ew", padx=(10, 6), pady=4)
        FlatButton(
            body,
            "浏览",
            self._browse_dir,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        ).grid(row=row, column=2, pady=4)

        row += 1
        tk.Label(
            body, text="图片格式", bg=PANEL, fg=TEXT, font=self.fonts.u(10)
        ).grid(row=row, column=0, sticky="w", pady=4)
        current_format = next(
            (label for label, value in _FORMATS if value == self.settings.image_format),
            "PNG",
        )
        self.format_var = tk.StringVar(value=current_format)
        ttk.Combobox(
            body,
            textvariable=self.format_var,
            values=[label for label, _value in _FORMATS],
            state="readonly",
            width=12,
        ).grid(row=row, column=1, sticky="w", padx=(10, 6), pady=4)

        row += 1
        tk.Label(
            body, text="JPEG 质量", bg=PANEL, fg=TEXT, font=self.fonts.u(10)
        ).grid(row=row, column=0, sticky="w", pady=4)
        self.quality_var = tk.StringVar(value=str(self.settings.jpeg_quality))
        ttk.Spinbox(
            body, from_=50, to=100, textvariable=self.quality_var, width=8
        ).grid(row=row, column=1, sticky="w", padx=(10, 6), pady=4)

        row += 1
        tk.Label(
            body, text="最近截图上限", bg=PANEL, fg=TEXT, font=self.fonts.u(10)
        ).grid(row=row, column=0, sticky="w", pady=4)
        self.recent_var = tk.StringVar(value=str(self.settings.recent_limit))
        ttk.Spinbox(
            body, from_=10, to=5000, textvariable=self.recent_var, width=8
        ).grid(row=row, column=1, sticky="w", padx=(10, 6), pady=4)

        row += 1
        tk.Label(
            body, text="截图快捷键", bg=PANEL, fg=TEXT, font=self.fonts.u(10)
        ).grid(row=row, column=0, sticky="w", pady=4)
        hotkey_row = tk.Frame(body, bg=PANEL)
        hotkey_row.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4)
        self.hotkey_var = tk.StringVar(value=self.settings.hotkey.display())
        tk.Label(
            hotkey_row,
            textvariable=self.hotkey_var,
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.m(11, "bold"),
        ).pack(side="left")
        FlatButton(
            hotkey_row,
            "录制",
            self._record_hotkey,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        ).pack(side="left", padx=(10, 0))
        self.hotkey_enabled_var = tk.BooleanVar(
            value=self.settings.hotkey_enabled
        )
        ttk.Checkbutton(
            hotkey_row,
            text="启用",
            variable=self.hotkey_enabled_var,
        ).pack(side="left", padx=(10, 0))

        scroll_panel = tk.Frame(
            shell, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        scroll_panel.pack(fill="x", pady=(10, 0))
        scroll_body = tk.Frame(scroll_panel, bg=PANEL, padx=16, pady=12)
        scroll_body.pack(fill="x")
        scroll_body.grid_columnconfigure(1, weight=1)
        tk.Label(
            scroll_body,
            text="滚动截图（Windows/X11）",
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.u(10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        scroll_fields = (
            ("滚动格数", "scroll_notches", self.settings.scroll_notches, 1, 20),
            (
                "每帧等待（毫秒）",
                "scroll_delay_ms",
                self.settings.scroll_delay_ms,
                50,
                3000,
            ),
            (
                "最大高度（像素）",
                "scroll_max_height",
                self.settings.scroll_max_height,
                1000,
                100000,
            ),
            (
                "忽略顶部（像素）",
                "scroll_ignore_top",
                self.settings.scroll_ignore_top,
                0,
                1000,
            ),
            (
                "忽略底部（像素）",
                "scroll_ignore_bottom",
                self.settings.scroll_ignore_bottom,
                0,
                1000,
            ),
        )
        self._scroll_vars: dict[str, tk.StringVar] = {}
        for index, (label, key, value, low, high) in enumerate(scroll_fields, start=1):
            tk.Label(
                scroll_body, text=label, bg=PANEL, fg=TEXT, font=self.fonts.u(9)
            ).grid(row=index, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(value))
            self._scroll_vars[key] = var
            ttk.Spinbox(
                scroll_body,
                from_=low,
                to=high,
                textvariable=var,
                width=8,
            ).grid(row=index, column=1, sticky="w", padx=(10, 0), pady=3)

        tk.Label(
            shell,
            text=(
                "Wayland 下应用内全局快捷键不可用，请把系统快捷键绑定到 "
                "quicktools --screenshot region。"
            ),
            bg=BG,
            fg=MUTED,
            justify="left",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(anchor="w", pady=(10, 0))

        buttons = tk.Frame(shell, bg=BG)
        buttons.pack(fill="x", pady=(18, 0))
        FlatButton(
            buttons,
            "保存",
            self._save,
            fonts=self.fonts,
            accent=True,
            font_size=10,
            padx=16,
            pady=8,
        ).pack(side="right")
        FlatButton(
            buttons,
            "取消",
            self.close,
            fonts=self.fonts,
            font_size=10,
            padx=16,
            pady=8,
        ).pack(side="right", padx=(0, 8))

    def _browse_dir(self) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            title="选择截图保存目录",
            initialdir=self.save_dir_var.get() or None,
        )
        if selected:
            self.save_dir_var.set(selected)

    def _record_hotkey(self) -> None:
        if self._recording:
            return
        self._recording = True
        self.plugin.suspend_hotkey()

        def apply(spec: HotkeySpec) -> None:
            self.plugin.update_settings(hotkey=spec)
            self.hotkey_var.set(spec.display())

        def done() -> None:
            self._recording = False
            self.plugin.resume_hotkey()

        _HotkeyRecorder(self, self.fonts, apply, done)

    def _save(self) -> None:
        format_value = next(
            (value for label, value in _FORMATS if label == self.format_var.get()),
            "png",
        )
        try:
            quality = int(self.quality_var.get())
            recent = int(self.recent_var.get())
            scroll_values = {
                key: int(var.get()) for key, var in self._scroll_vars.items()
            }
        except ValueError:
            messagebox.showerror(
                "设置错误", "质量、最近截图上限和滚动参数必须是整数。", parent=self
            )
            return
        try:
            self.plugin.update_settings(
                save_dir=self.save_dir_var.get().strip(),
                image_format=format_value,
                jpeg_quality=quality,
                recent_limit=recent,
                hotkey_enabled=bool(self.hotkey_enabled_var.get()),
                **scroll_values,
            )
        except Exception as exc:
            log.exception("保存截图设置失败")
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.on_saved()
        self.close()

    def close(self) -> None:
        if self._recording:
            self.plugin.resume_hotkey()
            self._recording = False
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
