"""The QuickTools plugin launcher window."""

from __future__ import annotations

import sys
import tkinter as tk
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
    BG,
    BORDER,
    BUTTON,
    BUTTON_HOVER,
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

if TYPE_CHECKING:
    from .app import QuickToolsApp

log = get_logger(__name__)


class Launcher:
    def __init__(self, app: "QuickToolsApp", root: tk.Tk) -> None:
        self.app = app
        self.root = root
        self.fonts: Fonts = pick_fonts(root)
        self.loader = app.loader
        self.plugins: list[PluginMeta] = []
        self._errors: list[str] = []
        self._plugin_windows: dict[str, tk.Toplevel] = {}
        self._background_plugins: dict[str, tuple[PluginMeta, PluginBase]] = {}
        self._background_failures: dict[str, tuple[str, str]] = {}
        self._cards: list[tk.Frame] = []
        self._search_job: str | None = None
        self._tray_popup: tk.Toplevel | None = None
        self._header_logo = None
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
        self.window.bind("<Escape>", lambda _e: self.hide())
        self.window.minsize(640, 420)
        self._build()
        self.reload_plugins()

    # ---------------------------------------------------------------- build
    def _build(self) -> None:
        shell = tk.Frame(self.window, bg=BG, padx=20, pady=16)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x", pady=(0, 12))
        if self._header_logo is not None:
            tk.Label(
                header,
                image=self._header_logo,
                bg=BG,
                bd=0,
            ).pack(side="left", padx=(0, 10))
        titles = tk.Frame(header, bg=BG)
        titles.pack(side="left")
        tk.Label(
            titles,
            text="快捷工具",
            bg=BG,
            fg=TEXT,
            font=self.fonts.u(20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            titles,
            text="选择要启动的插件",
            bg=BG,
            fg=MUTED,
            font=self.fonts.u(10),
        ).pack(anchor="w", pady=(2, 0))

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

        cards_border = tk.Frame(shell, bg=BORDER)
        cards_border.pack(fill="both", expand=True)
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
    def show(self) -> None:
        self.window.deiconify()
        # Pick up plugins copied into the user directory since the last show.
        self.reload_plugins()
        center_on_screen(self.window, 800, 540)
        self.window.attributes("-topmost", True)
        self.window.lift()
        self.window.focus_force()
        self.search_var.set("")
        self.window.after(40, self._focus_search)
        log.info("启动器已显示")

    def hide(self) -> None:
        self.window.withdraw()
        log.info("启动器已隐藏")

    def toggle(self) -> None:
        if self.window.winfo_viewable():
            self.hide()
        else:
            self.show()

    def _focus_search(self) -> None:
        try:
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, tk.END)
        except tk.TclError:
            pass

    # -------------------------------------------------------------- plugins
    def reload_plugins(self) -> tuple[int, list[str]]:
        self.plugins = self.loader.scan()
        self._errors = list(self.loader.errors)
        self._sync_background_plugins()
        self._refresh_cards()
        return len(self.plugins), list(self._errors)

    def _make_context(self, meta: PluginMeta) -> PluginContext:
        data_dir = paths.plugin_data_dir(meta.id)
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
        existing = self._plugin_windows.get(meta.id)
        if existing is not None and self._exists(existing):
            self.hide()
            self.window.after(20, lambda w=existing: self._focus_window(w))
            return
        self._plugin_windows.pop(meta.id, None)

        window: tk.Toplevel | None = None
        try:
            instance = self._instance_for(meta)
            window = tk.Toplevel(self.root)
            window.withdraw()
            window.title(f"{meta.name} · 快捷工具")
            self.app.apply_window_icon(window)
            window.configure(bg=BG)
            instance.create_ui(window)
            window.protocol(
                "WM_DELETE_WINDOW", lambda w=window, mid=meta.id: self._close_plugin(mid, w)
            )
        except Exception as exc:
            if window is not None and self._exists(window):
                try:
                    window.destroy()
                except tk.TclError:
                    pass
            log.exception("打开插件 %s 失败", meta.id)
            message = str(exc) if str(exc) else exc.__class__.__name__
            messagebox.showerror(
                "插件加载失败",
                f"无法打开插件“{meta.name}”：\n\n{message}\n\n详细日志：{paths.log_file()}",
                parent=self.window,
            )
            return

        assert window is not None
        self._plugin_windows[meta.id] = window
        self.hide()
        self.window.after(20, lambda w=window: self._show_plugin_window(w))

    def _show_plugin_window(self, window: tk.Toplevel) -> None:
        if not self._exists(window):
            return
        window.deiconify()
        window.lift()
        window.focus_force()

    def _focus_window(self, window: tk.Toplevel) -> None:
        if not self._exists(window):
            return
        try:
            window.deiconify()
            window.lift()
            window.focus_force()
        except tk.TclError:
            pass

    def _close_plugin(self, plugin_id: str, window: tk.Toplevel) -> None:
        if self._plugin_windows.get(plugin_id) is window:
            self._plugin_windows.pop(plugin_id, None)
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
            haystack = f"{meta.name} {meta.description} {meta.id}".casefold()
            if query in haystack:
                result.append(meta)
        return result

    def _refresh_cards(self) -> None:
        self._search_job = None
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self._cards = []
        plugins = self._filtered_plugins()
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
                        pady=5,
                    )
                else:
                    card.grid(
                        row=index // 2,
                        column=index % 2,
                        sticky="nsew",
                        padx=5,
                        pady=5,
                    )
                self._cards.append(card)
        self._update_status()
        self.cards_frame.update_idletasks()
        bbox = self.cards_canvas.bbox("all")
        if bbox:
            self.cards_canvas.configure(scrollregion=bbox)
        self.cards_canvas.yview_moveto(0.0)

    def _make_card(self, meta: PluginMeta, *, wide: bool = False) -> tk.Frame:
        card = tk.Frame(
            self.cards_frame,
            bg=PANEL_ALT,
            highlightbackground=BORDER,
            highlightthickness=1,
            cursor="hand2",
        )

        top = tk.Frame(card, bg=PANEL_ALT)
        top.pack(fill="x", padx=14, pady=(12, 4))
        badge = tk.Frame(top, bg=BUTTON, width=46, height=46)
        badge.pack(side="left", padx=(0, 12))
        badge.pack_propagate(False)
        icon = tk.Label(
            badge,
            text=meta.display_icon,
            bg=BUTTON,
            fg=ACCENT,
            font=self.fonts.u(20, "bold"),
            cursor="hand2",
        )
        icon.pack(fill="both", expand=True)
        title_box = tk.Frame(top, bg=PANEL_ALT)
        title_box.pack(side="left", fill="x", expand=True)
        name = tk.Label(
            title_box,
            text=meta.name,
            bg=PANEL_ALT,
            fg=TEXT,
            anchor="w",
            font=self.fonts.u(14, "bold"),
            cursor="hand2",
        )
        name.pack(fill="x")
        version = tk.Label(
            title_box,
            text=f"v{meta.version}",
            bg=PANEL_ALT,
            fg=MUTED,
            anchor="w",
            font=self.fonts.u(9),
            cursor="hand2",
        )
        version.pack(fill="x", pady=(2, 0))

        description = tk.Label(
            card,
            text=meta.description or "无描述",
            bg=PANEL_ALT,
            fg=MUTED,
            justify="left",
            anchor="nw",
            wraplength=620 if wide else 280,
            font=self.fonts.u(10),
            cursor="hand2",
        )
        description.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        bottom = tk.Frame(card, bg=PANEL_ALT)
        bottom.pack(fill="x", padx=14, pady=(0, 10))
        is_open = meta.id in self._plugin_windows and self._exists(
            self._plugin_windows[meta.id]
        )
        hint = tk.Label(
            bottom,
            text="已打开，点击聚焦" if is_open else "点击打开",
            bg=PANEL_ALT,
            fg=ACCENT if not is_open else MUTED,
            font=self.fonts.u(9),
            cursor="hand2",
        )
        hint.pack(side="left")
        arrow = tk.Label(
            bottom,
            text="→",
            bg=PANEL_ALT,
            fg=ACCENT,
            font=self.fonts.u(12, "bold"),
            cursor="hand2",
        )
        arrow.pack(side="right")

        card_widgets = [
            card,
            top,
            title_box,
            name,
            version,
            description,
            bottom,
            hint,
            arrow,
        ]
        badge_widgets = [badge, icon]

        def open_here(_event=None):
            self.open_plugin(meta)

        def hover(_event=None):
            for widget in card_widgets:
                try:
                    widget.configure(bg=BUTTON)
                except tk.TclError:
                    pass
            for widget in badge_widgets:
                try:
                    widget.configure(bg=BUTTON_HOVER)
                except tk.TclError:
                    pass

        def leave(_event=None):
            for widget in card_widgets:
                try:
                    widget.configure(bg=PANEL_ALT)
                except tk.TclError:
                    pass
            for widget in badge_widgets:
                try:
                    widget.configure(bg=BUTTON)
                except tk.TclError:
                    pass

        for widget in card_widgets + badge_widgets:
            widget.bind("<Button-1>", open_here)
            widget.bind("<Enter>", hover)
            widget.bind("<Leave>", leave)
            self._bind_wheel(widget)
        return card

    def _on_search_enter(self, _event=None) -> None:
        plugins = self._filtered_plugins()
        if len(plugins) == 1:
            self.open_plugin(plugins[0])

    def _on_cards_configure(self, _event=None) -> None:
        bbox = self.cards_canvas.bbox("all")
        if bbox:
            self.cards_canvas.configure(scrollregion=bbox)

    def _on_cards_canvas_configure(self, event: tk.Event) -> None:
        self.cards_canvas.itemconfigure(self._cards_window, width=event.width)

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
        popup.focus_force()
        try:
            popup.grab_set()
        except tk.TclError:
            pass
        popup.after(80, popup.focus_force)

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
