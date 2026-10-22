"""Screenshot plugin settings embedded in the shared settings dialog."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from quicktools.config import HotkeySpec
from quicktools.settings_widgets import (
    Card,
    SectionHeader,
    SettingsRow,
    ToggleRow,
)
from quicktools.ui_theme import (
    ACCENT,
    CARD_BG,
    DANGER,
    MUTED,
    SURFACE,
    TEXT,
    FlatButton,
    center_on_screen,
    pick_fonts,
)
from quicktools.window_frame import WindowFrame

from quicktools.modal_dialogs import open_native_file_dialog

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
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)
        self.frame = WindowFrame(
            self,
            title="录制截图快捷键",
            icon="K",
            fonts=fonts,
            dialog=True,
            pin=False,
            minimize=False,
            maximize=False,
            resizable=False,
            on_close=self._cancel,
        )
        self._build()
        center_on_screen(self, 520, 400, parent=master)
        self.after(30, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _build(self) -> None:
        shell = tk.Frame(self, bg=SURFACE, padx=20, pady=18)
        shell.pack(fill="both", expand=True)
        SectionHeader(
            shell,
            "按下新的截图快捷键",
            "必须包含至少一个 Ctrl / Alt / Shift / Super 修饰键。按 Esc 取消。",
            bg=SURFACE,
            fonts=self.fonts,
            wraplength=430,
        ).pack(fill="x", pady=(0, 10))

        card = Card(shell)
        card.pack(fill="x")
        self.preview_var = tk.StringVar(value="等待按键…")
        tk.Label(
            card.body,
            textvariable=self.preview_var,
            bg=CARD_BG,
            fg=TEXT,
            font=self.fonts.m(15, "bold"),
            padx=16,
            pady=12,
            anchor="center",
        ).pack(fill="x")
        self.hint_var = tk.StringVar(value="")
        tk.Label(
            card.body,
            textvariable=self.hint_var,
            bg=CARD_BG,
            fg=DANGER,
            anchor="w",
            font=self.fonts.u(9),
        ).pack(fill="x", pady=(6, 0))

        buttons = tk.Frame(shell, bg=SURFACE)
        buttons.pack(fill="x", pady=(12, 0))
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


class ScreenshotSettingsPanel(tk.Frame):
    """Screenshot settings page embedded in the shared plugin dialog."""

    def __init__(
        self,
        master: tk.Misc,
        plugin: "ScreenshotPlugin",
        on_saved: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=SURFACE)
        self.plugin = plugin
        self.on_saved = on_saved
        self.fonts = pick_fonts(self.winfo_toplevel())
        self.settings = plugin.settings
        self._recording = False
        self.status_var = tk.StringVar(value="")
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._recording:
            self.plugin.resume_hotkey()
            self._recording = False

    def _build(self) -> None:
        SectionHeader(
            self,
            "截图与保存",
            "设置截图保存位置、图片格式和快捷键。修改后点击保存生效。",
            bg=SURFACE,
            fonts=self.fonts,
            wraplength=560,
        ).pack(fill="x", pady=(0, 10))

        save_card = Card(self)
        save_card.pack(fill="x", pady=(0, 12))
        save_body = save_card.body
        tk.Label(
            save_body,
            text="保存位置与格式",
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        ).pack(fill="x", pady=(0, 2))

        save_dir_row = SettingsRow(
            save_body,
            "保存目录",
            description="截图和最近记录都保存在这个目录下。",
            bg=CARD_BG,
            fonts=self.fonts,
        )
        save_dir_row.pack(fill="x")
        self.save_dir_var = tk.StringVar(
            value=str(self.settings.resolved_save_dir())
        )
        control = save_dir_row.control
        tk.Entry(
            control,
            textvariable=self.save_dir_var,
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground="#d8dde5",
            highlightthickness=1,
            width=30,
            font=self.fonts.u(9),
        ).pack(side="left")
        FlatButton(
            control,
            "浏览",
            self._browse_dir,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        ).pack(side="left", padx=(6, 0))

        format_row = SettingsRow(
            save_body,
            "图片格式",
            bg=CARD_BG,
            fonts=self.fonts,
        )
        format_row.pack(fill="x")
        current_format = next(
            (
                label
                for label, value in _FORMATS
                if value == self.settings.image_format
            ),
            "PNG",
        )
        self.format_var = tk.StringVar(value=current_format)
        ttk.Combobox(
            format_row.control,
            textvariable=self.format_var,
            values=[label for label, _value in _FORMATS],
            state="readonly",
            width=12,
        ).pack()

        quality_row = SettingsRow(
            save_body,
            "JPEG 质量",
            description="仅 JPEG 格式使用，数值越高文件越大。",
            bg=CARD_BG,
            fonts=self.fonts,
            last=True,
        )
        quality_row.pack(fill="x")
        self.quality_var = tk.StringVar(value=str(self.settings.jpeg_quality))
        ttk.Spinbox(
            quality_row.control,
            from_=50,
            to=100,
            textvariable=self.quality_var,
            width=8,
        ).pack()

        hotkey_card = Card(self)
        hotkey_card.pack(fill="x", pady=(0, 12))
        hotkey_body = hotkey_card.body
        tk.Label(
            hotkey_body,
            text="快捷键",
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        ).pack(fill="x", pady=(0, 2))
        hotkey_row = SettingsRow(
            hotkey_body,
            "截图快捷键",
            description="按下组合键后立即开始矩形截图。",
            bg=CARD_BG,
            fonts=self.fonts,
        )
        hotkey_row.pack(fill="x")
        self.hotkey_var = tk.StringVar(
            value=self.settings.hotkey.display()
        )
        tk.Label(
            hotkey_row.control,
            textvariable=self.hotkey_var,
            bg=CARD_BG,
            fg=ACCENT,
            font=self.fonts.m(11, "bold"),
        ).pack(side="left", padx=(0, 8))
        FlatButton(
            hotkey_row.control,
            "录制",
            self._record_hotkey,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        ).pack(side="left")
        self.hotkey_enabled_var = tk.BooleanVar(
            value=self.settings.hotkey_enabled
        )
        ToggleRow(
            hotkey_body,
            "启用全局快捷键",
            self.hotkey_enabled_var,
            description="关闭后仍可在截图助手中点击按钮截图。",
            bg=CARD_BG,
            fonts=self.fonts,
            last=True,
        ).pack(fill="x")

        window_card = Card(self)
        window_card.pack(fill="x", pady=(0, 12))
        window_body = window_card.body
        tk.Label(
            window_body,
            text="窗口截图（Windows/X11）",
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        ).pack(fill="x", pady=(0, 2))
        margin_row = SettingsRow(
            window_body,
            "窗口外扩边距（像素）",
            description="向所选窗口四周额外扩展的像素数；0 表示严格按窗口边界截图。仅原生窗口截图生效。",
            bg=CARD_BG,
            fonts=self.fonts,
            last=True,
        )
        margin_row.pack(fill="x")
        self.margin_var = tk.StringVar(
            value=str(self.settings.window_margin_px)
        )
        ttk.Spinbox(
            margin_row.control,
            from_=0,
            to=500,
            textvariable=self.margin_var,
            width=8,
        ).pack()

        scroll_card = Card(self)
        scroll_card.pack(fill="x", pady=(0, 12))
        scroll_body = scroll_card.body
        tk.Label(
            scroll_body,
            text="滚动截图（Windows/X11）",
            bg=CARD_BG,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(10, "bold"),
        ).pack(fill="x")
        tk.Label(
            scroll_body,
            text="滚动截图是尽力而为的拼接，低置信度时会提前停止。",
            bg=CARD_BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=520,
            font=self.fonts.u(8),
        ).pack(fill="x", pady=(2, 4))
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
        for index, (label, key, value, low, high) in enumerate(scroll_fields):
            row = SettingsRow(
                scroll_body,
                label,
                bg=CARD_BG,
                fonts=self.fonts,
                last=index == len(scroll_fields) - 1,
                padding=(0, 6),
            )
            row.pack(fill="x")
            var = tk.StringVar(value=str(value))
            self._scroll_vars[key] = var
            ttk.Spinbox(
                row.control,
                from_=low,
                to=high,
                textvariable=var,
                width=8,
            ).pack()

        tk.Label(
            self,
            text=(
                "Wayland 下应用内全局快捷键不可用，请把系统快捷键绑定到 "
                "quicktools --screenshot region。"
            ),
            bg=SURFACE,
            fg=MUTED,
            justify="left",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(anchor="w", pady=(2, 0))

        self._status_label = tk.Label(
            self,
            textvariable=self.status_var,
            bg=SURFACE,
            fg=ACCENT,
            anchor="w",
            font=self.fonts.u(9),
        )
        self._status_label.pack(anchor="w", fill="x", pady=(8, 0))

        buttons = tk.Frame(self, bg=SURFACE)
        buttons.pack(fill="x", pady=(12, 0))
        FlatButton(
            buttons,
            "保存设置",
            self._save,
            fonts=self.fonts,
            accent=True,
            font_size=10,
            padx=16,
            pady=8,
        ).pack(side="right")

    def _browse_dir(self) -> None:
        selected = open_native_file_dialog(
            self,
            filedialog.askdirectory,
            title="选择截图保存目录",
            initialdir=self.save_dir_var.get() or None,
        )
        if selected:
            log.info("用户操作：选择截图保存目录 %s", selected)
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

        _HotkeyRecorder(self.winfo_toplevel(), self.fonts, apply, done)

    def _status(self, message: str, *, error: bool = False) -> None:
        self.status_var.set(message)
        try:
            self._status_label.configure(fg=DANGER if error else ACCENT)
        except tk.TclError:
            pass
        host = self.winfo_toplevel()
        setter = getattr(host, "set_status", None)
        if callable(setter):
            try:
                setter(message, error=error)
            except Exception:
                pass

    def _save(self) -> None:
        format_value = next(
            (
                value
                for label, value in _FORMATS
                if label == self.format_var.get()
            ),
            "png",
        )
        try:
            quality = int(self.quality_var.get())
            margin = int(self.margin_var.get())
            scroll_values = {
                key: int(var.get()) for key, var in self._scroll_vars.items()
            }
        except ValueError:
            messagebox.showerror(
                "设置错误",
                "质量、外扩边距和滚动参数必须是整数。",
                parent=self.winfo_toplevel(),
            )
            return
        try:
            self.plugin.update_settings(
                save_dir=self.save_dir_var.get().strip(),
                image_format=format_value,
                jpeg_quality=quality,
                window_margin_px=margin,
                hotkey_enabled=bool(self.hotkey_enabled_var.get()),
                **scroll_values,
            )
        except Exception as exc:
            log.exception("保存截图设置失败")
            messagebox.showerror(
                "保存失败", str(exc), parent=self.winfo_toplevel()
            )
            self._status(f"保存失败：{exc}", error=True)
            return
        self.on_saved()
        self._status("截图设置已保存")
