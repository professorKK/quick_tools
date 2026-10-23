"""The QuickTools plugin launcher window."""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Callable

from . import paths
from .logging_setup import get_logger
from .plugin_api import (
    PluginActions,
    PluginBase,
    PluginContext,
    PluginError,
    PluginMeta,
)
from .ui_theme import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BORDER,
    BUTTON,
    BADGE_BG,
    BADGE_BG_HOVER,
    DANGER,
    MUTED,
    PANEL,
    PANEL_ALT,
    TEXT,
    FlatButton,
    Fonts,
    center_on_screen,
    pick_fonts,
)
from .win32_window import (
    enable_rounded_corners,
    prepare_top_level,
    restore as restore_window,
)
from .window_frame import (
    ResizeGrips,
    WindowFrame,
    enable_drag,
    make_frameless,
)
from .window_state import WindowStateStore

if sys.platform == "win32":
    from .win32_focus import force_foreground, is_foreground

    # Windows always exposes a foreground window.
    _HAS_NATIVE_FOCUS = True
elif sys.platform.startswith("linux"):
    from .x11_focus import force_foreground, is_foreground
    from .x11_focus import supported as _x11_focus_supported

    # False under Wayland: the compositor owns focus, so keep the legacy
    # event-based behaviour instead of trusting an unverifiable answer.
    _HAS_NATIVE_FOCUS = _x11_focus_supported()
else:  # pragma: no cover - 其他平台的空实现

    def force_foreground(_window: tk.Misc) -> bool:
        return False

    def is_foreground(_window: tk.Misc) -> bool:
        return True

    _HAS_NATIVE_FOCUS = False

if TYPE_CHECKING:
    from .app import QuickToolsApp

log = get_logger(__name__)

# Delay before re-checking focus after the launcher loses it. The window
# manager can take a few milliseconds to hand focus to the next window, so
# hiding immediately would misfire on transient focus changes.
_AUTO_HIDE_DELAY_MS = 150

# A background process may need more than one attempt before Windows hands it
# the foreground: SetForegroundWindow is asynchronous across input queues and
# the Tk window may still be finishing its first map. Retry briefly instead of
# leaving a visible-but-inactive launcher behind.
_FOCUS_RETRY_DELAYS_MS = (0, 20, 60, 120)


class Launcher:
    def __init__(
        self,
        app: "QuickToolsApp",
        root: tk.Tk,
        *,
        window_states: WindowStateStore | None = None,
        plugin_data_root: Path | None = None,
    ) -> None:
        self.app = app
        self.root = root
        self.plugin_data_root = (
            Path(plugin_data_root) if plugin_data_root is not None else None
        )
        # Set while plugin data is being moved. Opening/restarting a plugin in
        # that window would recreate databases and files inside the old root
        # while it is being renamed or copied.
        self._plugins_suspended = False
        self.fonts: Fonts = pick_fonts(root)
        self.loader = app.loader
        self.plugins: list[PluginMeta] = []
        self._errors: list[str] = []
        self._plugin_windows: dict[str, tk.Toplevel] = {}
        self._plugin_frames: dict[str, WindowFrame] = {}
        self._window_states = window_states or WindowStateStore()
        self._window_state_jobs: dict[str, str] = {}
        self._background_plugins: dict[str, tuple[PluginMeta, PluginBase]] = {}
        self._background_failures: dict[str, tuple[str, str]] = {}
        self._cards: list[tk.Frame] = []
        self._search_job: str | None = None
        self._tray_popup: tk.Toplevel | None = None
        # "Click outside to hide" only applies to launcher instances woken by
        # the toggle command (hotkey or --toggle).
        self._auto_hide = False
        self._auto_hide_job: str | None = None
        self._plugin_refresh_job: str | None = None
        self._focus_job: str | None = None
        self._had_focus = False
        self._showing = False
        self._auto_hide_requested = False
        self._show_started_at = 0.0
        self._header_logo = None
        self._first_run_hint: tk.Frame | None = None
        self._selected_card_index = -1
        try:
            self._header_logo = tk.PhotoImage(
                master=root, file=str(paths.assets_dir() / "launcher.png")
            )
        except Exception as exc:
            log.warning("启动器 Logo 加载失败：%s", exc)

        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title("快捷工具")
        self.app.apply_window_icon(self.window)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<Escape>", self._on_escape)
        self.window.bind("<FocusIn>", self._on_launcher_focus_in)
        self.window.bind("<FocusOut>", self._on_launcher_focus_out)
        self.window.minsize(720, 480)
        self.window.attributes("-topmost", True)
        # The launcher has no system caption: its header doubles as the drag
        # handle and the only chrome is the content itself.
        make_frameless(self.window)
        self.window.bind("<Map>", self._on_launcher_map, add="+")
        self._build()
        # The launcher has no window-manager border either, so reuse the same
        # edge grips plugin windows use. The grip frames are direct children
        # of the launcher and must blend with the launcher background.
        self._grips = ResizeGrips(self.window, background=BG)
        self.reload_plugins()
        # Lay out while still hidden so the first hotkey show only has to map
        # an already-built window, not run the whole geometry pass on screen.
        self.window.geometry("860x560")
        self.window.update_idletasks()

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        shell = tk.Frame(self.window, bg=BG, padx=20, pady=16)
        shell.pack(fill="both", expand=True)
        self._shell = shell

        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        self._header = header
        drag_widgets: list[tk.Misc] = [header]
        if self._header_logo is not None:
            logo = tk.Label(
                header,
                image=self._header_logo,
                bg=BG,
                bd=0,
            )
            logo.pack(side="left", padx=(0, 10))
            drag_widgets.append(logo)
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        drag_widgets.append(titles)
        title_label = tk.Label(
            titles,
            text="快捷工具",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(20, "bold"),
        )
        title_label.pack(anchor="w")
        subtitle_label = tk.Label(
            titles,
            text="选择要启动的插件",
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(10),
        )
        subtitle_label.pack(anchor="w", pady=(2, 0))
        drag_widgets.extend((title_label, subtitle_label))
        for widget in drag_widgets:
            enable_drag(widget, self.window)

        actions = tk.Frame(header, bg=BG)
        actions.pack(side="right")
        FlatButton(
            actions,
            "设置",
            self._open_settings,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left", padx=(0, 6))
        FlatButton(
            actions,
            "隐藏",
            self.hide,
            fonts=self.fonts,
            font_size=10,
            padx=12,
            pady=7,
        ).pack(side="left")

        search_row = tk.Frame(shell, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        search_row.pack(fill="x", pady=(0, 12))
        tk.Label(
            search_row,
            text="搜索",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(10),
        ).pack(side="left", padx=(12, 6), pady=8)
        tk.Label(
            search_row,
            text="↑↓ 选择 · Enter 打开",
            bg=PANEL,
            fg=MUTED,
            font=self.fonts.u(8),
        ).pack(side="right", padx=(6, 12), pady=8)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search_entry = tk.Entry(
            search_row,
            textvariable=self.search_var,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=ACCENT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=self.fonts.u(11),
        )
        self.search_entry.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=8)
        self.search_entry.bind("<Return>", self._on_search_enter)
        self.search_entry.bind("<Down>", lambda _event: self._move_selection(1))
        self.search_entry.bind("<Up>", lambda _event: self._move_selection(-1))

        cards_border = tk.Frame(shell, bg=BORDER)
        cards_border.pack(fill="both", expand=True)
        self._cards_border = cards_border
        self.cards_holder = tk.Frame(cards_border, bg=BG)
        self.cards_holder.pack(fill="both", expand=True, padx=1, pady=1)
        self.cards_canvas = tk.Canvas(
            self.cards_holder,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self.cards_scrollbar = tk.Scrollbar(
            self.cards_holder,
            orient="vertical",
            command=self.cards_canvas.yview,
            bg=BORDER,
            troughcolor=BG,
            activebackground=ACCENT,
            bd=0,
            relief="flat",
            width=10,
        )
        self.cards_canvas.configure(yscrollcommand=self.cards_scrollbar.set)
        self._scrollbar_visible = True
        self.cards_scrollbar.pack(side="right", fill="y")
        self.cards_canvas.pack(side="left", fill="both", expand=True)
        self.cards_frame = tk.Frame(self.cards_canvas, bg=BG)
        self._cards_window = self.cards_canvas.create_window(
            (0, 0), window=self.cards_frame, anchor="nw"
        )
        self.cards_frame.grid_columnconfigure(0, weight=1, uniform="card")
        self.cards_frame.grid_columnconfigure(1, weight=1, uniform="card")
        self.cards_frame.bind("<Configure>", self._on_cards_configure)
        self.cards_canvas.bind("<Configure>", self._on_cards_canvas_configure)
        for widget in (self.cards_canvas, self.cards_frame):
            self._bind_wheel(widget)

        footer = tk.Frame(shell, bg=BG)
        footer.pack(fill="x", pady=(10, 0))
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            footer,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=620,
            font=self.fonts.u(9),
        )
        self.status_label.pack(side="left", fill="x", expand=True)
        tk.Label(
            footer,
            text="关闭后仍驻留后台 · 状态栏图标可唤出",
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(9),
        ).pack(side="right")

    # --------------------------------------------------------------- window
    def _on_launcher_map(self, event: tk.Event) -> None:
        if event.widget is not self.window:
            return
        # Keep taskbar integration, rounded corners and topmost styling after
        # a withdraw/deiconify cycle.
        prepare_top_level(self.window)
        enable_rounded_corners(self.window)
        grips = getattr(self, "_grips", None)
        if grips is not None:
            grips.raise_grips()

    def _window_size(self) -> tuple[int, int]:
        """Return the launcher size, preserving a user-resized window."""
        try:
            width = self.window.winfo_width()
            height = self.window.winfo_height()
            max_width = self.window.winfo_screenwidth()
            max_height = self.window.winfo_screenheight()
        except tk.TclError:
            return 860, 560
        if width <= 1 or height <= 1:
            return 860, 560
        return (
            min(max(720, width), max_width),
            min(max(480, height), max_height),
        )

    def show(self, *, auto_hide: bool = False) -> None:
        self._cancel_focus_job()
        self._showing = True
        self._had_focus = False
        self._show_started_at = time.perf_counter()
        self._auto_hide_requested = auto_hide
        width, height = self._window_size()
        try:
            if sys.platform.startswith("linux"):
                # X11: position the window while it is still withdrawn. The
                # first mapped override-redirect Toplevel can ignore a
                # position request that races with the initial map, leaving
                # the launcher at 0,0 (partly under the desktop top bar and
                # hard to grab for dragging).
                center_on_screen(self.window, width, height)
                self.window.deiconify()
            else:
                self.window.deiconify()
                center_on_screen(self.window, width, height)
            self.window.lift()
            self._focus_search()
            self._activate_window()
            self._set_auto_hide(auto_hide)
            self.search_var.set("")
            self._maybe_show_first_run_hint()
            # Focus and paint the launcher before doing filesystem/plugin
            # work. On Windows, delaying activation until after
            # reload_plugins() leaves the window visibly inactive while that
            # work runs; that is the "grey text for a second" symptom.
            self._focus_search()
            self._schedule_plugin_refresh()
            log.info("启动器已显示")
        finally:
            self._showing = False
        self._verify_foreground(0)

    def _maybe_show_first_run_hint(self) -> None:
        """Show the one-time welcome banner for new users."""
        settings = getattr(self.app, "settings", None)
        if settings is None or getattr(settings, "first_run_seen", True):
            return
        if self._first_run_hint is not None:
            return
        hint = tk.Frame(
            self._shell,
            bg=ACCENT_SOFT,
            highlightbackground="#c7dcff",
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        try:
            hotkey = settings.hotkey.display()
        except Exception:
            hotkey = "全局快捷键"
        tk.Label(
            hint,
            text=(
                f"按 {hotkey} 随时唤出；关闭窗口后仍在后台，"
                "状态栏/托盘菜单可退出。"
            ),
            bg=ACCENT_SOFT,
            fg=TEXT,
            justify="left",
            anchor="w",
            wraplength=560,
            font=self.fonts.u(9),
        ).pack(side="left", fill="x", expand=True)
        FlatButton(
            hint,
            "知道了",
            self._dismiss_first_run_hint,
            fonts=self.fonts,
            font_size=9,
            padx=9,
            pady=3,
            bg=ACCENT_SOFT,
            fg=ACCENT,
            hover_bg="#dbeafe",
            press_bg="#c7dcff",
        ).pack(side="right", padx=(10, 0))
        hint.pack(fill="x", pady=(0, 10), before=self._cards_border)
        self._first_run_hint = hint
        log.info("首次使用：已显示启动器欢迎提示")

    def _dismiss_first_run_hint(self) -> None:
        hint = self._first_run_hint
        self._first_run_hint = None
        if hint is not None:
            try:
                hint.destroy()
            except tk.TclError:
                pass
        mark = getattr(self.app, "mark_first_run_seen", None)
        if callable(mark):
            try:
                mark()
            except Exception:
                log.exception("保存首次使用提示状态失败")

    def _schedule_plugin_refresh(self) -> None:
        job = self._plugin_refresh_job
        if job is not None:
            try:
                self.window.after_cancel(job)
            except tk.TclError:
                pass
        try:
            self._plugin_refresh_job = self.window.after_idle(
                self._refresh_plugins_after_show
            )
        except tk.TclError:
            self._plugin_refresh_job = None

    def _refresh_plugins_after_show(self) -> None:
        self._plugin_refresh_job = None
        if not self._exists(self.window):
            return
        # Pick up plugins copied into the user directory since the last show.
        self.reload_plugins()

    def hide(self) -> None:
        self._cancel_focus_job()
        self._auto_hide_requested = False
        self._had_focus = False
        self._set_auto_hide(False)
        self.window.withdraw()
        log.info("启动器已隐藏")

    def toggle(self) -> None:
        if self.window.winfo_viewable():
            self.hide()
        else:
            self.show(auto_hide=True)

    def _focus_search(self) -> None:
        try:
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, tk.END)
        except tk.TclError:
            pass

    def _activate_window(self) -> bool:
        """Bring the launcher to the foreground and give it keyboard focus.

        A process woken from the background (hotkey or ``--toggle`` while an
        instance already runs) is not allowed to call SetForegroundWindow
        unless it owns the foreground input queue. The Windows backend
        receives ``WM_HOTKEY`` on this thread, which grants that right; the
        AttachThreadInput helper is the fallback for pynput/legacy paths.
        """
        activated = False
        if sys.platform == "win32":
            try:
                activated = force_foreground(self.window)
            except Exception:
                log.debug("强制前台激活失败，回退到 focus_force()", exc_info=True)
        try:
            # focus_force() also sets Tk's focus model to the launcher even
            # when Windows refuses the foreground change.
            self.window.focus_force()
        except tk.TclError:
            return activated
        if sys.platform.startswith("linux"):
            # Tk's focus_force() only updates Tk's own focus model for an
            # overrideredirect window; the X server never receives the focus.
            # Without X input focus the launcher cannot receive keystrokes or
            # a <FocusOut> when the user clicks elsewhere.
            try:
                activated = force_foreground(self.window) or activated
            except Exception:
                log.debug("设置 X11 原生焦点失败", exc_info=True)
            return activated
        if sys.platform == "win32":
            return activated or is_foreground(self.window)
        return True

    def _verify_foreground(self, attempt: int = 0) -> None:
        """Check (and briefly retry) that the OS really activated the window.

        SetForegroundWindow is asynchronous across input queues, so a single
        call can return before the window is active. Arming auto-hide during
        that gap makes the launcher hide itself ~150 ms after being shown.
        """
        self._focus_job = None
        if not self._exists(self.window):
            return
        try:
            if not self.window.winfo_viewable():
                return
        except tk.TclError:
            return
        if _HAS_NATIVE_FOCUS and not is_foreground(self.window):
            next_attempt = attempt + 1
            if next_attempt < len(_FOCUS_RETRY_DELAYS_MS):
                self._activate_window()
                delay = _FOCUS_RETRY_DELAYS_MS[next_attempt]
                try:
                    self._focus_job = self.window.after(
                        delay, lambda: self._verify_foreground(next_attempt)
                    )
                except tk.TclError:
                    self._focus_job = None
                return
            log.warning("启动器未能取得前台焦点，保持显示")
            # Never self-hide a window the user has not been able to focus.
            self._set_auto_hide(False)
            return
        self._had_focus = True
        self._focus_search()
        if self._show_started_at:
            elapsed = (time.perf_counter() - self._show_started_at) * 1000
            log.info("启动器已取得前台焦点（%.0fms）", elapsed)
            self._show_started_at = 0.0
        if self._auto_hide_requested:
            self._set_auto_hide(True)

    def _cancel_focus_job(self) -> None:
        job = self._focus_job
        self._focus_job = None
        if job is None:
            return
        try:
            self.window.after_cancel(job)
        except tk.TclError:
            pass

    # ------------------------------------------------------- auto-hide
    def _set_auto_hide(self, enabled: bool) -> None:
        self._auto_hide = enabled
        self._cancel_auto_hide_job()

    def _cancel_auto_hide_job(self) -> None:
        job = self._auto_hide_job
        self._auto_hide_job = None
        if job is None:
            return
        try:
            self.window.after_cancel(job)
        except tk.TclError:
            pass

    def _on_launcher_focus_in(self, _event=None) -> None:
        # Tk's focus model can move to the search box while the OS still
        # considers another window active (Windows), or before the X11 focus
        # request lands. Only a real foreground activation counts as
        # "the launcher has been focused".
        if _HAS_NATIVE_FOCUS and not is_foreground(self.window):
            return
        self._had_focus = True
        if self._auto_hide_requested and not self._auto_hide:
            self._set_auto_hide(True)

    def _on_launcher_focus_out(self, _event=None) -> None:
        if not self._auto_hide or not self._had_focus or self._showing:
            return
        self._cancel_auto_hide_job()
        try:
            self._auto_hide_job = self.window.after(
                _AUTO_HIDE_DELAY_MS, self._hide_if_clicked_outside
            )
        except tk.TclError:
            pass

    def _hide_if_clicked_outside(self) -> None:
        self._auto_hide_job = None
        if not self._auto_hide or not self._had_focus or not self._exists(self.window):
            return
        try:
            if not self.window.winfo_viewable():
                return
        except tk.TclError:
            return
        # On X11 a <FocusOut> can be delivered while the search box trades
        # focus with its own toplevel; Tk's focus_get() is briefly None even
        # though the OS focus never left the launcher. Trust the native focus
        # first when it is available.
        if _HAS_NATIVE_FOCUS and is_foreground(self.window):
            return
        if self._focus_within(self.window):
            return
        log.info("焦点已移出启动器，自动隐藏")
        self.hide()

    def _focus_within(self, window: tk.Misc) -> bool:
        """True when Tk's focus is on ``window`` or one of its dialogs."""
        try:
            focused = window.focus_get()
        except tk.TclError:
            return True
        if focused is None:
            return False
        try:
            top = focused.winfo_toplevel()
        except (AttributeError, tk.TclError):
            return True
        if top is window:
            return True
        # Dialogs parented to the window (tray menu, plugin settings, a Tk
        # messagebox) are not part of the window's own toplevel path.
        prefix = f"{window}."
        try:
            if str(top).startswith(prefix):
                return True
            # Windows returns a Tcl object here, so compare its string form.
            if str(top.transient() or "") == str(window):
                return True
        except (AttributeError, tk.TclError):
            pass
        return False

    # -------------------------------------------------------------- plugins
    def reload_plugins(self) -> tuple[int, list[str]]:
        self.plugins = self.loader.scan()
        self._errors = list(self.loader.errors)
        if not self._plugins_suspended:
            self._sync_background_plugins()
        self._refresh_cards()
        return len(self.plugins), list(self._errors)

    def set_plugin_data_root(self, root: Path | None) -> None:
        self.plugin_data_root = Path(root) if root is not None else None

    def resume_plugins(self) -> None:
        """Allow plugin windows/services again after a data migration."""
        self._plugins_suspended = False

    def suspend_plugins_for_data_root_change(self) -> None:
        """Close every plugin window/service before moving their data."""
        self._plugins_suspended = True
        self.flush_window_states()
        for plugin_id, window in list(self._plugin_windows.items()):
            self._cancel_plugin_focus_job(window)
            self._cancel_window_state_job(plugin_id)
            if self._exists(window):
                try:
                    window.destroy()
                except tk.TclError:
                    pass
        self._plugin_windows.clear()
        self._plugin_frames.clear()
        self.stop_background_plugins()
        self._refresh_cards()

    def _make_context(self, meta: PluginMeta) -> PluginContext:
        if self.plugin_data_root is None:
            data_dir = paths.plugin_data_dir(meta.id)
        else:
            data_dir = paths.plugin_data_dir(meta.id, self.plugin_data_root)
        data_dir.mkdir(parents=True, exist_ok=True)
        actions = PluginActions(
            post_action=lambda action, mid=meta.id: self._post_plugin_action(
                mid, action
            ),
            open_window=lambda m=meta: self.open_plugin(m),
            hide_windows=self._hide_windows_for_capture,
            copy_png_to_clipboard=self._copy_png_via_clipboard,
            app_hotkey_display=self._app_hotkey_display,
        )
        return PluginContext(
            root=self.root,
            plugin_id=meta.id,
            plugin_dir=meta.folder,
            data_dir=data_dir,
            actions=actions,
            meta=meta,
        )

    def _post_plugin_action(self, plugin_id: str, action: str) -> None:
        commands = getattr(self.app, "commands", None)
        if commands is None:
            log.warning("应用命令队列不可用，无法投递插件动作：%s %s", plugin_id, action)
            return
        commands.put(f"plugin {plugin_id} {action}")

    def _hide_windows_for_capture(self) -> Callable[[], None]:
        hide = getattr(self.app, "hide_for_capture", None)
        if callable(hide):
            return hide()
        return self.hide_all_windows()

    def _app_hotkey_display(self) -> str:
        settings = getattr(self.app, "settings", None)
        hotkey = getattr(settings, "hotkey", None)
        display = getattr(hotkey, "display", None)
        if not callable(display):
            return ""
        try:
            return str(display())
        except Exception:
            return ""

    def _copy_png_via_clipboard(self, png: bytes) -> None:
        entry = self._background_plugins.get("clipboard")
        if entry is None:
            raise PluginError("剪贴板服务未运行，无法复制截图")
        instance = entry[1]
        writer = getattr(instance, "copy_image_png", None)
        if not callable(writer):
            raise PluginError("剪贴板插件版本过旧，无法复制截图")
        writer(png)

    def dispatch_plugin_action(self, plugin_id: str, action: str) -> bool:
        """Dispatch an action to a running background plugin instance."""
        if self._plugins_suspended:
            log.warning(
                "插件数据迁移进行中，忽略插件动作：%s %s", plugin_id, action
            )
            return False
        meta = next((item for item in self.plugins if item.id == plugin_id), None)
        if meta is None:
            log.warning("忽略未知插件的动作：%s %s", plugin_id, action)
            return False
        if not meta.background:
            log.warning("插件 %s 不是后台插件，不能接收动作", plugin_id)
            return False
        entry = self._background_plugins.get(plugin_id)
        if entry is not None:
            instance = entry[1]
        else:
            try:
                instance = self._instance_for(meta)
            except Exception:
                log.exception("启动插件 %s 以处理动作失败", plugin_id)
                return False
        try:
            instance.handle_action(action)
        except Exception:
            log.exception("插件 %s 处理动作 %s 失败", plugin_id, action)
            return False
        return True

    def hide_all_windows(self) -> Callable[[], None]:
        """Withdraw all tracked QuickTools windows and return a restore callback.

        Only windows that were visible at call time are restored. The callback
        is idempotent and tolerates windows destroyed while hidden.
        """
        # This path withdraws windows directly instead of going through
        # hide(), and the restore only deiconifies. A restored launcher counts
        # as a non-toggle display, so drop the auto-hide flag instead of
        # leaving it armed.
        self._set_auto_hide(False)
        hidden: list[tk.Toplevel] = []

        def collect(window: tk.Toplevel | None) -> None:
            if window is None or not self._exists(window):
                return
            try:
                if window.winfo_viewable():
                    hidden.append(window)
                    window.withdraw()
            except tk.TclError:
                pass

        collect(self.window)
        collect(self._tray_popup)
        for window in list(self._plugin_windows.values()):
            self._reset_plugin_focus_state(window)
            collect(window)
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass

        restored = False

        def restore() -> None:
            nonlocal restored
            if restored:
                return
            restored = True
            for window in hidden:
                if not self._exists(window):
                    continue
                try:
                    window.deiconify()
                    window.lift()
                except tk.TclError:
                    pass

        return restore

    def _new_instance(self, meta: PluginMeta) -> PluginBase:
        plugin_class = self.loader.load_class(meta)
        return plugin_class(self._make_context(meta))

    def _instance_for(self, meta: PluginMeta) -> PluginBase:
        """Return the instance used to open a plugin window.

        Background plugins keep one instance alive for the whole application,
        so their service and UI share state across window open/close cycles.
        """
        if meta.background:
            existing = self._background_plugins.get(meta.id)
            if existing is not None:
                return existing[1]
        instance = self._new_instance(meta)
        if meta.background:
            self._background_plugins[meta.id] = (meta, instance)
            self._background_failures.pop(meta.id, None)
            try:
                instance.start_service()
            except Exception:
                self._background_plugins.pop(meta.id, None)
                raise
        return instance

    def _sync_background_plugins(self) -> None:
        metas = {meta.id: meta for meta in self.plugins if meta.background}

        for plugin_id in list(self._background_plugins):
            old_meta, _instance = self._background_plugins[plugin_id]
            new_meta = metas.get(plugin_id)
            if (
                new_meta is None
                or new_meta.version != old_meta.version
                or new_meta.folder != old_meta.folder
            ):
                self._stop_background_plugin(plugin_id)
                self._background_failures.pop(plugin_id, None)

        for plugin_id, meta in metas.items():
            if plugin_id in self._background_plugins:
                continue
            signature = (meta.version, str(meta.folder))
            if self._background_failures.get(plugin_id) == signature:
                continue
            try:
                instance = self._new_instance(meta)
                instance.start_service()
            except Exception as exc:
                self._background_failures[plugin_id] = signature
                log.exception("启动后台插件 %s 失败", plugin_id)
                message = str(exc) if str(exc) else exc.__class__.__name__
                error = f"{plugin_id}: 后台服务启动失败：{message}"
                if error not in self._errors:
                    self._errors.append(error)
                continue
            self._background_plugins[plugin_id] = (meta, instance)
            self._background_failures.pop(plugin_id, None)

    def _stop_background_plugin(self, plugin_id: str) -> None:
        entry = self._background_plugins.pop(plugin_id, None)
        if entry is None:
            return
        window = self._plugin_windows.pop(plugin_id, None)
        if window is not None and self._exists(window):
            self._remember_window_size(plugin_id, window)
        self._cancel_window_state_job(plugin_id)
        self._plugin_frames.pop(plugin_id, None)
        if window is not None and self._exists(window):
            try:
                window.destroy()
            except tk.TclError:
                pass
        _meta, instance = entry
        try:
            instance.stop_service()
        except Exception:
            log.exception("停止后台插件 %s 失败", plugin_id)

    def stop_background_plugins(self) -> None:
        """Stop every background plugin service. Safe to call more than once."""
        for plugin_id in list(self._background_plugins):
            self._stop_background_plugin(plugin_id)

    @property
    def load_errors(self) -> list[str]:
        return list(self._errors)

    def plugin_window_count(self) -> int:
        return sum(1 for window in self._plugin_windows.values() if self._exists(window))

    def _exists(self, window: tk.Toplevel) -> bool:
        try:
            return bool(window.winfo_exists())
        except tk.TclError:
            return False

    def open_plugin(self, meta: PluginMeta) -> None:
        if self._plugins_suspended:
            log.warning("插件数据迁移进行中，暂不打开插件：%s", meta.id)
            return
        existing = self._plugin_windows.get(meta.id)
        if existing is not None and self._exists(existing):
            self.hide()
            self.window.after(20, lambda w=existing: self._focus_window(w))
            return
        self._plugin_windows.pop(meta.id, None)

        window: tk.Toplevel | None = None
        frame: WindowFrame | None = None
        try:
            instance = self._instance_for(meta)
            window = tk.Toplevel(self.root)
            window.withdraw()
            window.title(f"{meta.name} · 快捷工具")
            self.app.apply_window_icon(window)
            window.configure(bg=BG)
            frame = WindowFrame(
                window,
                title=meta.name,
                icon=meta.display_icon,
                fonts=self.fonts,
                on_settings=lambda w=window, inst=instance: (
                    self._open_plugin_settings(inst, w)
                ),
                on_close=lambda w=window, mid=meta.id: self._close_plugin(mid, w),
            )
            # Optional escape hatch for plugins that need to change their
            # title dynamically; normal plugins do not touch this.
            window.quicktools_frame = frame
            instance.create_ui(window)
            self._bind_window_state(meta.id, window)
            self._restore_window_state(meta.id, window, frame)
            window.protocol(
                "WM_DELETE_WINDOW", lambda w=window, mid=meta.id: self._close_plugin(mid, w)
            )
            window.bind(
                "<Destroy>",
                lambda event, mid=meta.id, w=window: self._on_plugin_window_destroyed(
                    event, mid, w
                ),
                add="+",
            )
            self._bind_plugin_auto_hide(window)
            frame.raise_grips()
        except Exception as exc:
            if window is not None and self._exists(window):
                try:
                    window.destroy()
                except tk.TclError:
                    pass
            log.exception("打开插件 %s 失败", meta.id)
            message = str(exc) if str(exc) else exc.__class__.__name__
            # A native dialog reports no Tk focus owner, so an armed
            # auto-hide check would hide the launcher behind its own error.
            self._set_auto_hide(False)
            messagebox.showerror(
                "插件加载失败",
                f"无法打开插件“{meta.name}”：\n\n{message}\n\n详细日志：{paths.log_file()}",
                parent=self.window,
            )
            return

        assert window is not None
        self._plugin_windows[meta.id] = window
        if frame is not None:
            self._plugin_frames[meta.id] = frame
        self.hide()
        self.window.after(20, lambda w=window: self._show_plugin_window(w))

    def _show_plugin_window(self, window: tk.Toplevel) -> None:
        if not self._exists(window):
            return
        restore_window(window)
        window.deiconify()
        window.lift()
        self._mark_plugin_shown(window)
        self._focus_frameless(window)

    def _focus_frameless(self, window: tk.Misc) -> None:
        """Focus a frameless window, including real X11 input focus."""
        try:
            window.focus_force()
        except tk.TclError:
            return
        if sys.platform.startswith("linux"):
            try:
                force_foreground(window)
            except Exception:
                log.debug("设置窗口 X11 原生焦点失败", exc_info=True)

    # ------------------------------------------------- plugin auto-hide
    def _bind_plugin_auto_hide(self, window: tk.Toplevel) -> None:
        """Hide a main plugin window when the user focuses another window.

        Plugin settings/about dialogs and the screenshot editor/overlay are
        created outside this path, so they keep their own lifecycle.
        """
        window._qt_focus_job = None
        window._qt_had_focus = False
        window.bind(
            "<FocusIn>",
            lambda _event, w=window: self._on_plugin_focus_in(w),
            add="+",
        )
        window.bind(
            "<FocusOut>",
            lambda _event, w=window: self._on_plugin_focus_out(w),
            add="+",
        )
        if sys.platform.startswith("linux"):
            # Override-redirect windows get no click-to-focus from the window
            # manager. A pinned window stays visible after losing focus, so
            # clicking back into it must restore the real X11 input focus;
            # otherwise keystrokes continue going to the other application.
            window.bind(
                "<ButtonPress-1>",
                lambda _event, w=window: self._restore_plugin_focus(w),
                add="+",
            )

    def _restore_plugin_focus(self, window: tk.Misc) -> None:
        """Route keyboard input back to a clicked frameless plugin window.

        Only ``XSetInputFocus`` is issued; Tk's focus model already points at
        the widget that handled the click (for example the detail Text), so
        text editing keeps working.
        """
        if not self._exists(window):
            return
        try:
            if is_foreground(window):
                return
            force_foreground(window)
        except Exception:
            log.debug("恢复插件窗口原生焦点失败", exc_info=True)

    def _mark_plugin_shown(self, window: tk.Toplevel) -> None:
        self._cancel_plugin_focus_job(window)
        window._qt_had_focus = True

    def _on_plugin_focus_in(self, window: tk.Toplevel) -> None:
        if not self._exists(window):
            return
        try:
            if not window.winfo_viewable():
                return
        except tk.TclError:
            return
        if _HAS_NATIVE_FOCUS and not is_foreground(window):
            return
        window._qt_had_focus = True

    def _plugin_pinned(self, window: tk.Toplevel) -> bool:
        frame = getattr(window, "quicktools_frame", None)
        try:
            return bool(frame is not None and frame.pinned)
        except Exception:
            return False

    def _on_plugin_focus_out(self, window: tk.Toplevel) -> None:
        if not getattr(window, "_qt_had_focus", False):
            return
        # A pinned window is explicitly meant to stay visible; do not hide it
        # when the user works in another application.
        if self._plugin_pinned(window):
            return
        if not self._exists(window):
            return
        try:
            if not window.winfo_viewable():
                return
        except tk.TclError:
            return
        self._cancel_plugin_focus_job(window)
        try:
            window._qt_focus_job = window.after(
                _AUTO_HIDE_DELAY_MS,
                lambda w=window: self._hide_plugin_if_focus_left(w),
            )
        except tk.TclError:
            window._qt_focus_job = None

    def _hide_plugin_if_focus_left(self, window: tk.Toplevel) -> None:
        window._qt_focus_job = None
        if not getattr(window, "_qt_had_focus", False):
            return
        # The pin was enabled between FocusOut and this check.
        if self._plugin_pinned(window):
            return
        if not self._exists(window):
            return
        try:
            if not window.winfo_viewable():
                return
        except tk.TclError:
            return
        if _HAS_NATIVE_FOCUS and is_foreground(window):
            return
        if self._focus_within(window):
            return
        # A just-opened settings/about dialog may not own Tk's focus yet at
        # this instant. Keep the parent alive while any child Toplevel is
        # visible; the dialog's close will restore focus to the parent.
        if self._has_visible_dialog(window):
            return
        log.info("插件窗口失去焦点，自动隐藏：%s", window.title())
        try:
            window.withdraw()
        except tk.TclError:
            pass

    def _has_visible_dialog(self, window: tk.Toplevel) -> bool:
        try:
            children = window.winfo_children()
        except tk.TclError:
            return True
        for child in children:
            if not isinstance(child, tk.Toplevel):
                continue
            try:
                if child.winfo_viewable():
                    return True
            except tk.TclError:
                continue
        return False

    def _cancel_plugin_focus_job(self, window: tk.Toplevel) -> None:
        job = getattr(window, "_qt_focus_job", None)
        window._qt_focus_job = None
        if job is None:
            return
        try:
            window.after_cancel(job)
        except tk.TclError:
            pass

    def _reset_plugin_focus_state(self, window: tk.Toplevel) -> None:
        self._cancel_plugin_focus_job(window)
        window._qt_had_focus = False

    # -------------------------------------------------------- window state
    def _bind_window_state(
        self, plugin_id: str, window: tk.Toplevel
    ) -> None:
        window.bind(
            "<Configure>",
            lambda event, pid=plugin_id, w=window: (
                self._on_plugin_window_configure(event, pid, w)
            ),
            add="+",
        )

    def _on_plugin_window_configure(
        self, event: tk.Event, plugin_id: str, window: tk.Toplevel
    ) -> None:
        if event.widget is not window:
            return
        self._cancel_window_state_job(plugin_id)
        try:
            self._window_state_jobs[plugin_id] = self.root.after(
                500,
                lambda: self._save_plugin_window_size(plugin_id, window),
            )
        except tk.TclError:
            pass

    def _cancel_window_state_job(self, plugin_id: str) -> None:
        job = self._window_state_jobs.pop(plugin_id, None)
        if job is None:
            return
        try:
            self.root.after_cancel(job)
        except tk.TclError:
            pass

    def _save_plugin_window_size(
        self, plugin_id: str, window: tk.Toplevel
    ) -> None:
        self._window_state_jobs.pop(plugin_id, None)
        if self._exists(window):
            self._remember_window_size(plugin_id, window)

    def _remember_window_size(
        self,
        plugin_id: str,
        window: tk.Toplevel,
        *,
        save: bool = True,
    ) -> None:
        frame = self._plugin_frames.get(plugin_id)
        if frame is not None:
            size = frame.normal_size()
            maximized = frame.maximized
        else:
            try:
                size = (window.winfo_width(), window.winfo_height())
            except tk.TclError:
                return
            maximized = False
        if size is None:
            return
        width, height = size
        if width <= 1 or height <= 1:
            return
        changed = self._window_states.set(
            plugin_id, width, height, maximized=maximized
        )
        if changed and save:
            self._window_states.save()

    def _restore_window_state(
        self,
        plugin_id: str,
        window: tk.Toplevel,
        frame: WindowFrame | None,
    ) -> None:
        state = self._window_states.get(plugin_id)
        if state is None:
            return
        try:
            window.update_idletasks()
            min_width, min_height = window.minsize()
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            # Never restore a size larger than the current display; a saved
            # size from a bigger monitor would otherwise open off-screen.
            max_width = max(min_width, screen_width - 80)
            max_height = max(min_height, screen_height - 100)
            width = max(min_width, min(state.width, max_width))
            height = max(min_height, min(state.height, max_height))
            center_on_screen(window, width, height)
            if state.maximized and frame is not None:
                frame.maximize()
        except tk.TclError:
            log.debug(
                "恢复插件 %s 的窗口大小失败", plugin_id, exc_info=True
            )

    def flush_window_states(self) -> None:
        """Store every open plugin window before the application exits."""
        for job in list(self._window_state_jobs.values()):
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._window_state_jobs.clear()
        for plugin_id, window in list(self._plugin_windows.items()):
            if self._exists(window):
                self._remember_window_size(plugin_id, window, save=False)
        self._window_states.save()

    def _open_plugin_settings(self, instance: PluginBase, window: tk.Toplevel) -> None:
        try:
            opener = getattr(instance, "open_settings", None)
            if callable(opener):
                opener(window)
                return
            raise PluginError("插件缺少设置入口")
        except Exception as exc:
            log.exception("打开插件设置失败")
            message = str(exc) if str(exc) else exc.__class__.__name__
            messagebox.showerror(
                "无法打开设置",
                f"{message}\n\n详细日志：{paths.log_file()}",
                parent=window,
            )

    def _on_plugin_window_destroyed(
        self, event: tk.Event, plugin_id: str, window: tk.Toplevel
    ) -> None:
        if event.widget is not window:
            return
        self._cancel_plugin_focus_job(window)
        self._cancel_window_state_job(plugin_id)
        if self._plugin_windows.get(plugin_id) is window:
            self._remember_window_size(plugin_id, window)
            self._plugin_windows.pop(plugin_id, None)
        self._plugin_frames.pop(plugin_id, None)
        try:
            if not self.window.winfo_exists() or not self.cards_frame.winfo_exists():
                return
        except tk.TclError:
            return
        self._refresh_cards()

    def _focus_window(self, window: tk.Toplevel) -> None:
        if not self._exists(window):
            return
        try:
            restore_window(window)
            window.deiconify()
            window.lift()
            self._mark_plugin_shown(window)
            self._focus_frameless(window)
        except tk.TclError:
            pass

    def _close_plugin(self, plugin_id: str, window: tk.Toplevel) -> None:
        self._cancel_plugin_focus_job(window)
        if self._plugin_windows.get(plugin_id) is window:
            self._remember_window_size(plugin_id, window)
            self._plugin_windows.pop(plugin_id, None)
        self._cancel_window_state_job(plugin_id)
        self._plugin_frames.pop(plugin_id, None)
        try:
            window.destroy()
        except tk.TclError:
            pass
        self._refresh_cards()

    def open_user_plugins_dir(self) -> None:
        from .ui_theme import open_in_file_manager

        try:
            open_in_file_manager(paths.user_plugins_dir())
        except Exception as exc:
            messagebox.showerror("无法打开插件目录", str(exc), parent=self.window)

    # ---------------------------------------------------------------- cards
    def _on_search_changed(self, *_args) -> None:
        # Typing changes the result set; start from the first match so Enter
        # always has a predictable target.
        self._selected_card_index = 0
        if self._search_job is not None:
            try:
                self.window.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.window.after(60, self._refresh_cards)

    def _filtered_plugins(self) -> list[PluginMeta]:
        query = self.search_var.get().strip().casefold()
        if not query:
            return self.plugins
        result = []
        for meta in self.plugins:
            haystack = (
                f"{meta.name} {meta.summary} {meta.description} {meta.id}"
            ).casefold()
            if query in haystack:
                result.append(meta)
        return result

    def _refresh_cards(self) -> None:
        self._search_job = None
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self._cards = []
        plugins = self._filtered_plugins()
        self._selected_card_index = 0 if plugins else -1
        if not plugins:
            empty = tk.Frame(self.cards_frame, bg=BG)
            empty.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=6, pady=20)
            tk.Label(
                empty,
                text="没有匹配的插件" if self.plugins else "还没有可用插件",
                bg=BG,
                fg=MUTED,
                font=self.fonts.u(12),
            ).pack()
            if not self.plugins:
                tk.Label(
                    empty,
                    text="把插件文件夹放入用户插件目录，然后在设置中重新扫描。",
                    bg=BG,
                    fg=MUTED,
                    font=self.fonts.u(9),
                ).pack(pady=(5, 0))
        else:
            wide = len(plugins) == 1
            for index, meta in enumerate(plugins):
                card = self._make_card(meta, wide=wide)
                if wide:
                    card.grid(
                        row=index,
                        column=0,
                        columnspan=2,
                        sticky="nsew",
                        padx=5,
                        pady=4,
                    )
                else:
                    card.grid(
                        row=index // 2,
                        column=index % 2,
                        sticky="nsew",
                        padx=5,
                        pady=4,
                    )
                self._cards.append(card)
        self._apply_card_selection()
        self._update_status()
        self.cards_frame.update_idletasks()
        bbox = self.cards_canvas.bbox("all")
        if bbox:
            self.cards_canvas.configure(scrollregion=bbox)
        self.cards_canvas.yview_moveto(0.0)
        self._sync_cards_scrollbar()

    def _make_card(self, meta: PluginMeta, *, wide: bool = False) -> tk.Frame:
        card = tk.Frame(
            self.cards_frame,
            bg=PANEL_ALT,
            highlightbackground=BORDER,
            highlightthickness=1,
            cursor="hand2",
        )
        body = tk.Frame(card, bg=PANEL_ALT)
        body.pack(fill="both", expand=True, padx=12, pady=9)

        badge = tk.Canvas(
            body,
            width=40,
            height=40,
            bg=PANEL_ALT,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        badge.pack(side="left", padx=(0, 10))

        def draw_badge(background: str, fill: str) -> None:
            badge.delete("all")
            badge.configure(bg=background)
            points = [
                9, 1, 31, 1, 39, 9, 39, 31, 31, 39, 9, 39, 1, 31, 1, 9, 1, 1,
            ]
            badge.create_polygon(
                points,
                smooth=True,
                splinesteps=18,
                fill=fill,
                outline="",
            )
            badge.create_text(
                20,
                20,
                text=meta.display_icon,
                fill=ACCENT,
                font=self.fonts.u(15, "bold"),
            )

        draw_badge(PANEL_ALT, BADGE_BG)

        text_box = tk.Frame(body, bg=PANEL_ALT)
        name = tk.Label(
            text_box,
            text=meta.name,
            bg=PANEL_ALT,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(12, "bold"),
            cursor="hand2",
        )
        name.pack(fill="x")
        summary = tk.Label(
            text_box,
            text=meta.display_summary or "暂无说明",
            bg=PANEL_ALT,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=650 if wide else 280,
            font=self.fonts.u(9),
            cursor="hand2",
        )
        summary.pack(fill="x", pady=(2, 0))

        is_open = meta.id in self._plugin_windows and self._exists(
            self._plugin_windows[meta.id]
        )
        status = tk.Label(
            body,
            text="已打开" if is_open else "›",
            bg=PANEL_ALT,
            fg=ACCENT if is_open else MUTED,
            font=self.fonts.u(10 if is_open else 16, "bold"),
            cursor="hand2",
        )
        # Reserve the status label's width before packing the expanding text
        # box.  Otherwise a long summary squeezes "已打开" and clips its last
        # character at the card edge.
        status.pack(side="right", padx=(8, 0))
        text_box.pack(side="left", fill="both", expand=True)

        def fit_summary(event: tk.Event) -> None:
            if event.widget is not text_box:
                return
            try:
                summary.configure(wraplength=max(60, event.width - 2))
            except tk.TclError:
                pass

        text_box.bind("<Configure>", fit_summary, add="+")

        widgets = [card, body, text_box, name, summary, status]

        def open_here(_event=None):
            self.open_plugin(meta)

        def hover(_event=None):
            for widget in widgets:
                try:
                    widget.configure(bg=BUTTON)
                except tk.TclError:
                    pass
            draw_badge(BUTTON, BADGE_BG_HOVER)

        def leave(_event=None):
            for widget in widgets:
                try:
                    widget.configure(bg=PANEL_ALT)
                except tk.TclError:
                    pass
            draw_badge(PANEL_ALT, BADGE_BG)

        for widget in widgets:
            widget.bind("<Button-1>", open_here)
            widget.bind("<Enter>", hover)
            widget.bind("<Leave>", leave)
            self._bind_wheel(widget)
        badge.bind("<Button-1>", open_here)
        badge.bind("<Enter>", hover)
        badge.bind("<Leave>", leave)
        self._bind_wheel(badge)
        return card

    def _on_search_enter(self, _event=None) -> str:
        plugins = self._filtered_plugins()
        if not plugins:
            return "break"
        index = self._selected_card_index
        if not 0 <= index < len(plugins):
            index = 0
        self.open_plugin(plugins[index])
        return "break"

    def _on_escape(self, _event=None) -> str:
        # First Esc clears a search; a second one hides the launcher. This is
        # the usual launcher behaviour and avoids losing a typed query.
        try:
            query = self.search_var.get()
        except tk.TclError:
            query = ""
        if query:
            self.search_var.set("")
            self._focus_search()
            return "break"
        self.hide()
        return "break"

    def _move_selection(self, delta: int) -> str:
        count = len(self._cards)
        if not count:
            return "break"
        current = self._selected_card_index
        if not 0 <= current < count:
            current = 0
        self._selected_card_index = (current + delta) % count
        self._apply_card_selection()
        self._see_selected_card()
        return "break"

    def _apply_card_selection(self) -> None:
        index = self._selected_card_index
        for position, card in enumerate(self._cards):
            selected = position == index
            try:
                card.configure(
                    highlightbackground=ACCENT if selected else BORDER,
                    highlightcolor=ACCENT if selected else BORDER,
                    highlightthickness=2 if selected else 1,
                )
            except tk.TclError:
                pass

    def _see_selected_card(self) -> None:
        index = self._selected_card_index
        if not 0 <= index < len(self._cards):
            return
        card = self._cards[index]
        try:
            self.cards_canvas.update_idletasks()
            bbox = self.cards_canvas.bbox("all")
            if not bbox:
                return
            total = max(1, bbox[3] - bbox[1])
            top = card.winfo_y()
            height = card.winfo_height()
            view_top = self.cards_canvas.canvasy(0)
            view_height = self.cards_canvas.winfo_height()
            if top < view_top:
                self.cards_canvas.yview_moveto(max(0.0, top / total))
            elif top + height > view_top + view_height:
                target = (top + height - view_height) / total
                self.cards_canvas.yview_moveto(max(0.0, min(1.0, target)))
        except tk.TclError:
            pass

    def _on_cards_configure(self, _event=None) -> None:
        bbox = self.cards_canvas.bbox("all")
        if bbox:
            self.cards_canvas.configure(scrollregion=bbox)
        self._sync_cards_scrollbar()

    def _on_cards_canvas_configure(self, event: tk.Event) -> None:
        self.cards_canvas.itemconfigure(self._cards_window, width=event.width)
        self._sync_cards_scrollbar()

    def _sync_cards_scrollbar(self) -> None:
        """Hide the scrollbar while every plugin card fits on screen."""
        try:
            bbox = self.cards_canvas.bbox("all")
            needed = bool(bbox and bbox[3] > self.cards_canvas.winfo_height() + 2)
            if needed and not self._scrollbar_visible:
                self.cards_scrollbar.pack(
                    side="right", fill="y", before=self.cards_canvas
                )
                self._scrollbar_visible = True
            elif not needed and self._scrollbar_visible:
                self.cards_scrollbar.pack_forget()
                self._scrollbar_visible = False
        except tk.TclError:
            pass

    def _bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<Button-4>", self._on_wheel, add="+")
        widget.bind("<Button-5>", self._on_wheel, add="+")
        widget.bind("<MouseWheel>", self._on_wheel, add="+")

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            units = -3 if getattr(event, "delta", 0) > 0 else 3
        self.cards_canvas.yview_scroll(units, "units")
        return "break"

    # --------------------------------------------------------------- status
    def update_hotkey_status(self, text: str, warning: bool = False) -> None:
        self._hotkey_status = text
        self._hotkey_warning = warning
        self._update_status()

    def _update_status(self) -> None:
        hotkey_text = getattr(self, "_hotkey_status", self.app.hotkey_status_text())
        warning = getattr(self, "_hotkey_warning", self.app.hotkey_status_warning())
        if not hotkey_text:
            hotkey_text = "关闭窗口后仍在后台运行"
        if self._errors:
            extra = f"  ·  {len(self._errors)} 个插件未加载（详见设置）"
        else:
            extra = ""
        self.status_var.set(hotkey_text + extra)
        self.status_label.configure(fg=DANGER if warning else MUTED)

    def _open_settings(self) -> None:
        self.app.open_settings()

    def _ensure_tray_popup(self) -> tk.Toplevel:
        popup = self._tray_popup
        if popup is not None:
            return popup

        popup = tk.Toplevel(self.window)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=BORDER)
        popup.bind("<Escape>", lambda _e: self.hide_tray_menu())
        popup.bind("<FocusOut>", self._on_tray_popup_focus_out)

        inner = tk.Frame(popup, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        show_button = FlatButton(
            inner,
            "显示",
            self._tray_show,
            fonts=self.fonts,
            font_size=10,
            padx=16,
            pady=9,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
        )
        show_button.pack(fill="x")
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")
        quit_button = FlatButton(
            inner,
            "退出",
            self._tray_quit,
            fonts=self.fonts,
            font_size=10,
            padx=16,
            pady=9,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
        )
        quit_button.pack(fill="x")

        self._tray_popup = popup
        return popup

    def _on_tray_popup_focus_out(self, _event=None) -> None:
        popup = self._tray_popup
        if popup is None:
            return
        popup.after(80, self._hide_tray_popup_if_unfocused)

    def _hide_tray_popup_if_unfocused(self) -> None:
        popup = self._tray_popup
        if popup is None or not popup.winfo_exists():
            return
        try:
            focused = popup.focus_get()
        except tk.TclError:
            focused = None
        if focused is None or focused.winfo_toplevel() is not popup:
            self.hide_tray_menu()

    def show_tray_menu(self, x: int, y: int) -> None:
        """Show the tray dropdown on the Tk main thread."""
        popup = self._ensure_tray_popup()
        if popup.winfo_viewable():
            self.hide_tray_menu()
            return
        # Keep only one topmost Tk window so focus and pointer clicks always
        # belong to the dropdown, even if the launcher was visible.
        if self.window.winfo_viewable():
            self.hide()
        popup.update_idletasks()
        width = 170
        height = popup.winfo_reqheight()
        screen_w = popup.winfo_screenwidth()
        screen_h = popup.winfo_screenheight()
        if x < 0 or y < 0:
            if sys.platform == "win32":
                x, y = screen_w - width - 8, screen_h - height - 48
            else:
                x, y = screen_w - width - 8, 30
        else:
            x = int(x) - width // 2
            y = int(y) + 2
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()
        popup.lift()
        popup.attributes("-topmost", True)
        self._focus_frameless(popup)
        try:
            popup.grab_set()
        except tk.TclError:
            pass
        popup.after(80, lambda: self._focus_frameless(popup))

    def hide_tray_menu(self) -> None:
        popup = self._tray_popup
        if popup is None:
            return
        try:
            popup.grab_release()
        except tk.TclError:
            pass
        try:
            popup.withdraw()
        except tk.TclError:
            pass

    def _tray_show(self) -> None:
        self.hide_tray_menu()
        self.show()

    def _tray_quit(self) -> None:
        self.hide_tray_menu()
        self.app.quit()
