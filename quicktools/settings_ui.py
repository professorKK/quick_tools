"""Settings window and global-shortcut recorder."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING, Callable

from . import __version__, autostart, paths
from .config import HotkeySpec
from .ui_theme import (
    ACCENT,
    BG,
    BORDER,
    DANGER,
    MUTED,
    PANEL,
    ROW,
    TEXT,
    FlatButton,
    Fonts,
    center_on_screen,
    open_in_file_manager,
    pick_fonts,
)

if TYPE_CHECKING:
    from .app import QuickToolsApp


_MODIFIER_KEYSYMS = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Super_L": "super",
    "Super_R": "super",
    "Win_L": "super",
    "Win_R": "super",
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
    "Page_Up": "pageup",
    "Next": "pagedown",
    "Page_Down": "pagedown",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
}


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


class HotkeyRecorder(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        app: "QuickToolsApp",
        fonts: Fonts,
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.app = app
        self.fonts = fonts
        self.on_done = on_done
        self.candidate: HotkeySpec | None = None
        self._mods: set[str] = set()
        self._closed = False

        self.title("录制快捷键")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<KeyPress>", self._on_key_press)
        self.bind("<KeyRelease>", self._on_key_release)

        app.begin_hotkey_capture()
        self._build()
        center_on_screen(self, 440, 250, parent=master)
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
            text="按下新的快捷键组合",
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
        ).pack(anchor="w", pady=(4, 14))

        self.preview_var = tk.StringVar(value="等待按键…")
        preview = tk.Frame(self, bg=BG)
        preview.pack(fill="x", padx=20)
        tk.Label(
            preview,
            textvariable=self.preview_var,
            bg=PANEL,
            fg=ACCENT,
            font=self.fonts.m(15, "bold"),
            padx=16,
            pady=12,
            anchor="center",
        ).pack(fill="x", padx=0)

        self.hint_var = tk.StringVar(value="")
        tk.Label(
            self,
            textvariable=self.hint_var,
            bg=BG,
            fg=DANGER,
            font=self.fonts.u(9),
        ).pack(anchor="w", padx=20, pady=(5, 8))

        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x", padx=20, pady=(0, 14))
        self.apply_button = FlatButton(
            buttons,
            "使用此快捷键",
            self._apply,
            fonts=self.fonts,
            font_size=10,
            padx=14,
            pady=8,
            accent=True,
        )
        self.apply_button.pack(side="right")
        FlatButton(
            buttons,
            "取消",
            self._cancel,
            fonts=self.fonts,
            font_size=10,
            padx=14,
            pady=8,
        ).pack(side="right", padx=(0, 8))
        self.apply_button.set_enabled(False)

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
            self.candidate = None
            self.apply_button.set_enabled(False)
            return "break"
        if not self._mods:
            self.hint_var.set("请同时按住 Ctrl / Alt / Shift / Super 等修饰键")
            self.candidate = None
            self.apply_button.set_enabled(False)
            self.preview_var.set(key.upper())
            return "break"
        try:
            candidate = HotkeySpec(tuple(self._mods), key)
        except ValueError as exc:
            self.hint_var.set(str(exc))
            self.candidate = None
            self.apply_button.set_enabled(False)
            return "break"
        self.candidate = candidate
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
        if self.candidate is None:
            return
        candidate = self.candidate
        ok, message = self.app.set_hotkey(candidate)
        if not ok:
            messagebox.showerror("快捷键设置失败", message, parent=self)
        self._finish()
        self.on_done()

    def _cancel(self) -> None:
        if self._closed:
            return
        self.app.cancel_hotkey_capture()
        self._finish()
        self.on_done()

    def _finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class SettingsWindow(tk.Toplevel):
    def __init__(self, app: "QuickToolsApp", root: tk.Tk) -> None:
        super().__init__(root)
        self.app = app
        self.fonts = pick_fonts(root)
        self._closed = False
        self.title("快捷工具 · 设置")
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.minsize(620, 600)
        self._build()
        center_on_screen(self, 700, 740)
        self.after(50, self.focus_force)
        self._refresh_plugin_section()

    def _panel(self, parent: tk.Misc) -> tk.Frame:
        outer = tk.Frame(parent, bg=BORDER)
        outer.pack(fill="x", pady=(0, 12))
        inner = tk.Frame(outer, bg=PANEL, padx=16, pady=14)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return inner

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG, padx=20, pady=16)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        FlatButton(
            header,
            "← 返回启动器",
            self.close,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left", padx=(0, 12))
        tk.Label(
            header,
            text="设置",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(18, "bold"),
        ).pack(side="left")

        hotkey_panel = self._panel(shell)
        tk.Label(
            hotkey_panel,
            text="全局快捷键",
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.u(11, "bold"),
        ).pack(anchor="w")
        self.hotkey_var = tk.StringVar()
        tk.Label(
            hotkey_panel,
            textvariable=self.hotkey_var,
            bg=PANEL,
            fg=ACCENT,
            font=self.fonts.m(14, "bold"),
        ).pack(anchor="w", pady=(6, 4))
        self.hotkey_status_var = tk.StringVar()
        self.hotkey_status_label = tk.Label(
            hotkey_panel,
            textvariable=self.hotkey_status_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.u(9),
        )
        self.hotkey_status_label.pack(anchor="w", fill="x", pady=(0, 8))

        hotkey_buttons = tk.Frame(hotkey_panel, bg=PANEL)
        hotkey_buttons.pack(fill="x")
        FlatButton(
            hotkey_buttons,
            "录制新快捷键",
            self._record_hotkey,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left")
        FlatButton(
            hotkey_buttons,
            f"恢复默认 {HotkeySpec.default().display()}",
            self._reset_hotkey,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            hotkey_panel,
            text=(
                "Linux 默认 Ctrl+Alt+Space；Windows 默认 Ctrl+Space。"
                "Windows 使用原生 RegisterHotKey，组合键会被独占；"
                "若 Ctrl+Space 影响输入法切换，请改绑 Ctrl+Alt+Space。"
                "X11/Windows 下修改后立即生效。"
            ),
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(anchor="w", fill="x", pady=(8, 0))
        self._refresh_hotkey_section()

        autostart_panel = self._panel(shell)
        autostart_row = tk.Frame(autostart_panel, bg=PANEL)
        autostart_row.pack(fill="x")
        tk.Label(
            autostart_row,
            text="开机启动",
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.u(11, "bold"),
        ).pack(side="left")
        self.autostart_var = tk.BooleanVar(value=False)
        self.autostart_check = tk.Checkbutton(
            autostart_row,
            text="登录系统时自动启动 QuickTools（后台运行）",
            variable=self.autostart_var,
            command=self._toggle_autostart,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=PANEL,
            anchor="w",
            font=self.fonts.u(10),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.autostart_check.pack(side="left", padx=(16, 0))
        self.autostart_hint_var = tk.StringVar()
        tk.Label(
            autostart_panel,
            textvariable=self.autostart_hint_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(anchor="w", fill="x", pady=(4, 0))

        plugin_panel = self._panel(shell)
        tk.Label(
            plugin_panel,
            text="插件",
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.u(11, "bold"),
        ).pack(anchor="w")
        self.plugin_path_var = tk.StringVar(value=str(paths.user_plugins_dir()))
        tk.Label(
            plugin_panel,
            textvariable=self.plugin_path_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.m(9),
        ).pack(anchor="w", fill="x", pady=(4, 6))
        plugin_buttons = tk.Frame(plugin_panel, bg=PANEL)
        plugin_buttons.pack(fill="x")
        FlatButton(
            plugin_buttons,
            "打开插件目录",
            self._open_plugin_dir,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left")
        FlatButton(
            plugin_buttons,
            "重新扫描插件",
            self._reload_plugins,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left", padx=(8, 0))
        self.plugin_info_var = tk.StringVar()
        tk.Label(
            plugin_panel,
            textvariable=self.plugin_info_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            font=self.fonts.u(9),
        ).pack(anchor="w", fill="x", pady=(8, 0))
        self.error_text = tk.Text(
            plugin_panel,
            height=4,
            bg=ROW,
            fg=DANGER,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            font=self.fonts.m(9),
            wrap="word",
        )
        self.error_text.pack(fill="x", pady=(6, 0))
        self.error_text.configure(state="disabled")
        tk.Label(
            plugin_panel,
            text="插件运行在主进程内，拥有与主程序相同的权限；只安装可信插件。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(anchor="w", fill="x", pady=(6, 0))

        footer = tk.Frame(shell, bg=BG)
        footer.pack(fill="x", side="bottom", pady=(4, 0))
        tk.Label(
            footer,
            text=f"QuickTools v{__version__}",
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="left")
        FlatButton(
            footer,
            "退出快捷工具",
            self._quit_app,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="right")

        self._refresh_autostart_section()

    def _refresh_hotkey_section(self) -> None:
        self.hotkey_var.set(self.app.settings.hotkey.display())
        status = self.app.hotkey_status_text()
        self.hotkey_status_var.set(status)
        self.hotkey_status_label.configure(
            fg=DANGER if self.app.hotkey_status_warning() else MUTED
        )

    def _refresh_plugin_section(self) -> None:
        self.plugin_path_var.set(str(paths.user_plugins_dir()))
        count, errors = self.app.reload_plugins()
        self.plugin_info_var.set(f"已发现 {count} 个可用插件。")
        self.error_text.configure(state="normal")
        self.error_text.delete("1.0", "end")
        if errors:
            self.error_text.insert("1.0", "\n".join(errors))
            self.error_text.configure(fg=DANGER)
        else:
            self.error_text.insert("1.0", "未发现插件加载错误。")
            self.error_text.configure(fg=MUTED)
        self.error_text.configure(state="disabled")
        self._refresh_hotkey_section()

    def _refresh_autostart_section(self) -> None:
        if not autostart.is_supported():
            self.autostart_var.set(False)
            self.autostart_check.configure(state="disabled")
            self.autostart_hint_var.set("当前平台不支持开机启动。")
            return
        try:
            enabled = autostart.is_enabled()
        except OSError as exc:
            self.autostart_var.set(False)
            self.autostart_check.configure(state="disabled")
            self.autostart_hint_var.set(f"无法读取开机启动状态：{exc}")
            return
        self.autostart_check.configure(state="normal")
        self.autostart_var.set(enabled)
        self.autostart_hint_var.set(autostart.mechanism_hint())

    def _toggle_autostart(self) -> None:
        wanted = bool(self.autostart_var.get())
        try:
            if wanted:
                autostart.enable()
            else:
                autostart.disable()
        except (OSError, RuntimeError) as exc:
            self.autostart_var.set(not wanted)
            messagebox.showerror("开机启动设置失败", str(exc), parent=self)
            return
        self._refresh_autostart_section()

    def _record_hotkey(self) -> None:
        HotkeyRecorder(self, self.app, self.fonts, on_done=self._refresh_hotkey_section)

    def _reset_hotkey(self) -> None:
        ok, message = self.app.set_hotkey(HotkeySpec.default())
        if not ok:
            messagebox.showerror("快捷键设置失败", message, parent=self)
        self._refresh_hotkey_section()

    def _open_plugin_dir(self) -> None:
        try:
            open_in_file_manager(paths.user_plugins_dir())
        except Exception as exc:
            messagebox.showerror("无法打开插件目录", str(exc), parent=self)

    def _reload_plugins(self) -> None:
        self._refresh_plugin_section()

    def _quit_app(self) -> None:
        if messagebox.askyesno(
            "退出快捷工具",
            "退出后全局快捷键将停止工作。确定退出吗？",
            parent=self,
        ):
            self.app.quit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.app.settings_closed(self)
        try:
            self.destroy()
        except tk.TclError:
            pass
