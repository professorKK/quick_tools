"""Settings window and global-shortcut recorder."""

from __future__ import annotations

import json
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

from . import __version__, autostart, paths
from .config import HotkeySpec
from .data_migration import (
    MigrationProgress,
    find_plugin_data_conflicts,
    normalize_plugin_data_root,
)
from .modal_dialogs import open_native_file_dialog, run_modal_dialog
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
from .window_frame import WindowFrame

if TYPE_CHECKING:
    from .app import QuickToolsApp

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
        self.frame = WindowFrame(
            self,
            title="录制快捷键",
            icon="K",
            fonts=fonts,
            dialog=True,
            pin=False,
            minimize=False,
            maximize=False,
            resizable=False,
            on_close=self._cancel,
        )

        app.begin_hotkey_capture()
        self._build()
        center_on_screen(self, 460, 300, parent=master)
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
            run_modal_dialog(
                self,
                lambda **kwargs: messagebox.showerror(
                    "快捷键设置失败", message, **kwargs
                ),
            )
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
        self._migration_busy = False
        self._migration_queue: queue.Queue | None = None
        self._migration_poll_job: str | None = None
        self.title("快捷工具 · 设置")
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        self.minsize(620, 600)
        self.frame = WindowFrame(
            self,
            title="快捷工具 · 设置",
            icon="Q",
            fonts=self.fonts,
            dialog=False,
            pin=False,
            minimize=True,
            maximize=False,
            resizable=True,
            on_close=self.close,
        )
        self._build()
        center_on_screen(self, 700, 780)
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
            text="应用设置",
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
        self._record_hotkey_button = FlatButton(
            hotkey_buttons,
            "录制新快捷键",
            self._record_hotkey,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        )
        self._record_hotkey_button.pack(side="left")
        self._reset_hotkey_button = FlatButton(
            hotkey_buttons,
            f"恢复默认 {HotkeySpec.default().display()}",
            self._reset_hotkey,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        )
        self._reset_hotkey_button.pack(side="left", padx=(8, 0))
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

        data_panel = self._panel(shell)
        tk.Label(
            data_panel,
            text="插件数据",
            bg=PANEL,
            fg=TEXT,
            font=self.fonts.u(11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            data_panel,
            text="所有插件的数据都保存在这个根目录下（每个插件一个子目录）。"
            "修改后会停止并重启插件，并把已有数据迁移到新位置。留空表示默认目录。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.u(9),
        ).pack(anchor="w", fill="x", pady=(4, 6))
        root_row = tk.Frame(data_panel, bg=PANEL)
        root_row.pack(fill="x")
        self.data_root_var = tk.StringVar(
            value=str(self.app.current_plugin_data_root())
        )
        self.data_root_entry = tk.Entry(
            root_row,
            textvariable=self.data_root_var,
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
            font=self.fonts.m(9),
        )
        self.data_root_entry.pack(
            side="left", fill="x", expand=True, ipady=4
        )
        self._browse_root_button = FlatButton(
            root_row,
            "浏览…",
            self._browse_data_root,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        )
        self._browse_root_button.pack(side="left", padx=(6, 0))
        data_buttons = tk.Frame(data_panel, bg=PANEL)
        data_buttons.pack(fill="x", pady=(8, 0))
        self._open_root_button = FlatButton(
            data_buttons,
            "打开当前目录",
            self._open_data_root,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        )
        self._open_root_button.pack(side="left")
        self._apply_root_button = FlatButton(
            data_buttons,
            "应用并迁移数据",
            self._apply_data_root,
            fonts=self.fonts,
            font_size=9,
            padx=10,
            pady=5,
        )
        self._apply_root_button.pack(side="left", padx=(8, 0))
        self._migration_status_var = tk.StringVar(value="")
        self._migration_status = tk.Label(
            data_panel,
            textvariable=self._migration_status_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            anchor="w",
            wraplength=600,
            font=self.fonts.u(9),
        )
        self._migration_progress = ttk.Progressbar(
            data_panel, mode="determinate", maximum=100
        )
        self._migration_progress.pack(
            fill="x", pady=(8, 0)
        )
        self._migration_progress.pack_forget()
        self._migration_status.pack(fill="x", pady=(4, 0))

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
        self._reload_plugins_button = FlatButton(
            plugin_buttons,
            "重新扫描插件",
            self._reload_plugins,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        )
        self._reload_plugins_button.pack(side="left", padx=(8, 0))
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
        self._quit_button = FlatButton(
            footer,
            "退出快捷工具",
            self._quit_app,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        )
        self._quit_button.pack(side="right")

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
        self.autostart_check.configure(
            state="disabled" if self._migration_busy else "normal"
        )
        self.autostart_var.set(enabled)
        self.autostart_hint_var.set(autostart.mechanism_hint())

    def _toggle_autostart(self) -> None:
        if self._migration_busy:
            return
        wanted = bool(self.autostart_var.get())
        try:
            if wanted:
                autostart.enable()
            else:
                autostart.disable()
        except (OSError, RuntimeError) as exc:
            self.autostart_var.set(not wanted)
            self._show_error("开机启动设置失败", str(exc))
            return
        self._refresh_autostart_section()

    def _record_hotkey(self) -> None:
        if self._migration_busy:
            return
        HotkeyRecorder(self, self.app, self.fonts, on_done=self._refresh_hotkey_section)

    def _reset_hotkey(self) -> None:
        if self._migration_busy:
            return
        ok, message = self.app.set_hotkey(HotkeySpec.default())
        if not ok:
            self._show_error("快捷键设置失败", message)
        self._refresh_hotkey_section()

    # ------------------------------------------------------ plugin data root
    def _show_error(self, title: str, message: str) -> None:
        run_modal_dialog(
            self,
            lambda **kwargs: messagebox.showerror(
                title, message, **kwargs
            ),
        )

    def _ask_yes_no(self, title: str, message: str) -> bool:
        return bool(
            run_modal_dialog(
                self,
                lambda **kwargs: messagebox.askyesno(
                    title, message, **kwargs
                ),
            )
        )

    def _browse_data_root(self) -> None:
        if self._migration_busy:
            return
        selected = open_native_file_dialog(
            self,
            filedialog.askdirectory,
            title="选择插件数据目录",
            initialdir=(
                self.data_root_var.get().strip()
                or str(paths.default_plugin_data_root())
            ),
        )
        if selected:
            self.data_root_var.set(selected)

    def _open_data_root(self) -> None:
        try:
            open_in_file_manager(self.app.current_plugin_data_root())
        except Exception as exc:
            self._show_error("无法打开插件数据目录", str(exc))

    @staticmethod
    def _screenshot_save_dir_within(root: Path) -> Path | None:
        """Return the screenshot save dir when it lives inside ``root``."""
        try:
            data = json.loads(
                (root / "screenshot" / "settings.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, ValueError):
            return None
        raw = data.get("save_dir") if isinstance(data, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            save_dir = Path(raw.strip()).expanduser().resolve()
            save_dir.relative_to(root.resolve())
        except (OSError, ValueError):
            return None
        return save_dir

    def _set_migration_busy(self, busy: bool) -> None:
        self._migration_busy = busy
        state = "disabled" if busy else "normal"
        try:
            self.data_root_entry.configure(state=state)
        except tk.TclError:
            pass
        if busy:
            if autostart.is_supported():
                try:
                    self.autostart_check.configure(state="disabled")
                except tk.TclError:
                    pass
        else:
            self._refresh_autostart_section()
        for button in (
            self._browse_root_button,
            self._open_root_button,
            self._apply_root_button,
            self._record_hotkey_button,
            self._reset_hotkey_button,
            self._reload_plugins_button,
            self._quit_button,
        ):
            button.set_enabled(not busy)
        if busy:
            self._migration_progress.pack(fill="x", pady=(8, 0))
            self._migration_progress.configure(value=0)
        else:
            self._migration_progress.pack_forget()

    def _apply_data_root(self) -> None:
        if self._migration_busy:
            return
        try:
            _stored, effective = normalize_plugin_data_root(
                self.data_root_var.get(),
                default_root=paths.default_plugin_data_root(),
            )
        except ValueError as exc:
            self._show_error("插件数据目录无效", str(exc))
            return
        current = self.app.current_plugin_data_root().resolve()
        if effective == current:
            self.data_root_var.set(str(current))
            self._migration_status_var.set(
                "当前使用的就是该目录，无需迁移。"
            )
            return
        if effective.exists() and not effective.is_dir():
            self._show_error(
                "插件数据目录无效", "目标路径已存在但不是目录。"
            )
            return
        try:
            conflicts = find_plugin_data_conflicts(current, effective)
        except OSError as exc:
            self._show_error(
                "无法检查目标目录", f"读取插件数据目录失败：{exc}"
            )
            return
        merge = False
        if conflicts:
            names = "、".join(conflicts)
            merge = self._ask_yes_no(
                "目标目录已有插件数据",
                f"目标目录中已存在以下插件数据：{names}。\n\n"
                "继续会合并：目标目录中的同名文件保留，只补充缺失文件。"
                "是否继续？",
            )
            if not merge:
                self._migration_status_var.set("已取消迁移。")
                return
        warning = ""
        save_dir_inside = self._screenshot_save_dir_within(current)
        if save_dir_inside is not None:
            warning = (
                "\n\n注意：截图保存目录\n"
                f"{save_dir_inside}\n"
                "位于旧插件数据目录内，迁移后它也会被移动到新位置。"
                "请迁移完成后到截图插件设置中更新“保存目录”。"
            )
        if not self._ask_yes_no(
            "迁移插件数据",
            "将停止并重启所有插件，并把插件数据从\n"
            f"{current}\n迁移到\n{effective}\n\n是否继续？{warning}",
        ):
            return

        self._set_migration_busy(True)
        self.app.begin_data_migration()
        self._migration_status_var.set("正在停止插件…")
        base_settings = self.app.settings
        try:
            self.app.suspend_plugins_for_data_root_change()
        except Exception as exc:
            # The launcher may already be partially suspended; restore the
            # old root and restart whatever was stopped.
            try:
                self.app.resume_plugins_after_data_root_change(None)
            except Exception:
                log.exception("停止插件失败后恢复插件失败")
            self.app.end_data_migration()
            self._set_migration_busy(False)
            self._show_error("停止插件失败", str(exc))
            return
        self._migration_queue = queue.Queue()

        def worker() -> None:
            try:
                result, new_settings = self.app.migrate_plugin_data_root(
                    base_settings,
                    str(effective),
                    merge=merge,
                    progress=self._migration_queue.put,
                )
                self._migration_queue.put(
                    ("done", result, new_settings, str(effective))
                )
            except Exception as exc:
                self._migration_queue.put(("error", exc))

        try:
            threading.Thread(
                target=worker, name="plugin-data-migration", daemon=True
            ).start()
            self._migration_poll_job = self.after(
                100, self._poll_data_root_migration
            )
        except Exception as exc:
            log.exception("启动插件数据迁移线程失败")
            self._migration_queue = None
            try:
                self.app.resume_plugins_after_data_root_change(None)
            except Exception:
                log.exception("迁移线程启动失败后恢复插件失败")
            self.app.end_data_migration()
            self._set_migration_busy(False)
            self._show_error("插件数据迁移失败", str(exc))

    def _poll_data_root_migration(self) -> None:
        self._migration_poll_job = None
        queue_obj = self._migration_queue
        if queue_obj is None:
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        while True:
            try:
                item = queue_obj.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, MigrationProgress):
                total = max(
                    1, item.bytes_total or item.files_total or 1
                )
                done = (
                    item.bytes_done
                    if item.bytes_total
                    else item.files_done
                )
                try:
                    self._migration_progress.configure(
                        value=min(100, int(done / total * 100))
                    )
                except tk.TclError:
                    pass
                self._migration_status_var.set(
                    f"正在迁移 {item.plugin_id}："
                    f"{item.files_done}/{item.files_total} 个文件…"
                )
            elif item[0] == "done":
                result, new_settings, effective = (
                    item[1],
                    item[2],
                    item[3],
                )
                self._migration_queue = None
                try:
                    self.app.resume_plugins_after_data_root_change(
                        new_settings
                    )
                except Exception:
                    log.exception("迁移后重启插件失败")
                finally:
                    self.app.end_data_migration()
                self.data_root_var.set(
                    str(self.app.current_plugin_data_root())
                )
                self._set_migration_busy(False)
                self._refresh_plugin_section()
                count = len(result.migrated) + len(result.merged)
                self._migration_status_var.set(
                    f"迁移完成：{count} 个插件，数据目录 {effective}。"
                )
                return
            elif item[0] == "error":
                self._migration_queue = None
                try:
                    self.app.resume_plugins_after_data_root_change(None)
                except Exception:
                    log.exception("迁移失败后重启插件失败")
                finally:
                    self.app.end_data_migration()
                self._set_migration_busy(False)
                self._migration_status_var.set(
                    "迁移失败，已恢复原数据目录。"
                )
                self._show_error(
                    "插件数据迁移失败", str(item[1])
                )
                return
        self._migration_poll_job = self.after(
            100, self._poll_data_root_migration
        )

    def _open_plugin_dir(self) -> None:
        try:
            open_in_file_manager(paths.user_plugins_dir())
        except Exception as exc:
            self._show_error("无法打开插件目录", str(exc))

    def _reload_plugins(self) -> None:
        if self._migration_busy:
            return
        self._refresh_plugin_section()

    def _quit_app(self) -> None:
        if self._migration_busy:
            self._migration_status_var.set(
                "正在迁移插件数据，请等待完成后再退出。"
            )
            return
        if self._ask_yes_no(
            "退出快捷工具",
            "退出后全局快捷键将停止工作。确定退出吗？",
        ):
            self.app.quit()

    def close(self) -> None:
        if self._migration_busy:
            self._migration_status_var.set(
                "正在迁移插件数据，请等待完成后再关闭设置。"
            )
            return
        if self._closed:
            return
        self._closed = True
        self.app.settings_closed(self)
        try:
            self.destroy()
        except tk.TclError:
            pass
