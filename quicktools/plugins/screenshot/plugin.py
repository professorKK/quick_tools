"""Screenshot plugin entry point."""

from __future__ import annotations

import logging
import os
import tkinter as tk

from quicktools.hotkey import HotkeyManager, is_wayland_session
from quicktools.plugin_api import PluginBase
from quicktools.ui_theme import BG, center_on_screen

from .service import ScreenshotService
from .settings import ScreenshotSettings
from .shortcuts import mode_shortcut_items
from .ui.control_window import ControlWindow

log = logging.getLogger(__name__)


class ScreenshotPlugin(PluginBase):
    settings_cards = True
    ACTIONS = frozenset(
        {
            "open",
            "capture_region",
            "capture_window",
            "capture_freeform",
            "capture_scroll",
        }
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        self.service: ScreenshotService | None = None
        self._startup_error = ""
        self._view: ControlWindow | None = None
        self._hotkey: HotkeyManager | None = None
        self._hotkey_managers: list[HotkeyManager] = []
        self._hotkey_suspended = False

    # ------------------------------------------------------------- lifecycle
    def start_service(self) -> None:
        if self.service is not None:
            return
        try:
            service = ScreenshotService(
                self.context.data_dir, self.context.root, self.context.actions
            )
            service.set_status_listener(self._on_service_status)
            service.set_recent_changed_listener(self._refresh_recent_view)
            service.start()
        except Exception as exc:
            self._startup_error = str(exc) or exc.__class__.__name__
            log.exception("启动截图服务失败")
            return
        self.service = service
        self._startup_error = ""
        self._start_hotkey(service)

    def stop_service(self) -> None:
        self._stop_hotkey()
        service = self.service
        self.service = None
        if service is not None:
            try:
                service.stop()
            except Exception:
                log.exception("停止截图服务失败")
        self._view = None

    def _start_hotkey(self, service: ScreenshotService) -> None:
        self._stop_hotkey()
        if self._hotkey_suspended:
            return
        if is_wayland_session():
            service.report_status(
                "Wayland：请把系统快捷键绑定到 quicktools --screenshot "
                "region/window/freeform/scroll"
            )
            return
        settings = service.settings
        if not settings.hotkey_enabled:
            service.report_status("截图快捷键未启用")
            return

        managers: list[HotkeyManager] = []
        primary_display = settings.hotkey.display()
        app_display = self.app_hotkey_display()
        primary_manager: HotkeyManager | None = None
        primary_conflict = bool(
            app_display
            and primary_display.casefold() == app_display.casefold()
        )
        primary_error = ""
        if not primary_conflict:
            manager = HotkeyManager(settings.hotkey, self._on_hotkey)
            if manager.start():
                primary_manager = manager
                managers.append(manager)
            else:
                primary_error = manager.error

        mode_registered = 0
        mode_skipped = 0
        for action, spec in mode_shortcut_items():
            display = spec.display()
            if display.casefold() == primary_display.casefold():
                mode_skipped += 1
                continue
            if app_display and display.casefold() == app_display.casefold():
                mode_skipped += 1
                continue
            manager = HotkeyManager(
                spec, lambda value=action: self._on_mode_hotkey(value)
            )
            if manager.start():
                managers.append(manager)
                mode_registered += 1
            else:
                log.warning(
                    "模式快捷键 %s 注册失败：%s", display, manager.error
                )

        self._hotkey_managers = managers
        self._hotkey = primary_manager
        if primary_conflict:
            message = "截图快捷键与启动器快捷键冲突，请在设置中修改"
        elif primary_manager is None:
            message = f"截图快捷键注册失败：{primary_error}"
        else:
            message = f"截图快捷键：{primary_display}"
        total_modes = len(mode_shortcut_items())
        if primary_manager is not None:
            if mode_registered == total_modes:
                message += " · 模式快捷键 Ctrl+Alt+1..4"
            elif mode_registered or mode_skipped:
                message += "；部分模式快捷键未注册，请检查系统占用"
        elif mode_registered:
            message += "；模式快捷键已启用"
        service.report_status(message)

    def _stop_hotkey(self) -> None:
        managers = self._hotkey_managers
        self._hotkey_managers = []
        self._hotkey = None
        for manager in managers:
            try:
                manager.stop()
            except Exception:
                log.exception("停止截图快捷键失败")

    def _on_hotkey(self) -> None:
        actions = self.context.actions
        if actions is None:
            return
        actions.post_action("capture_region")

    def _on_mode_hotkey(self, action: str) -> None:
        actions = self.context.actions
        if actions is None:
            return
        try:
            actions.post_action(action)
        except Exception:
            log.exception("投递截图动作失败：%s", action)

    def suspend_hotkey(self) -> None:
        self._hotkey_suspended = True
        self._stop_hotkey()

    def resume_hotkey(self) -> None:
        self._hotkey_suspended = False
        service = self.service
        if service is not None:
            self._start_hotkey(service)

    # ------------------------------------------------------------------- UI
    def create_ui(self, window: tk.Toplevel) -> None:
        service = self._ensure_service()
        window.title("截图助手 · 快捷工具")
        window.configure(bg=BG)
        view = ControlWindow(window, self)
        view.pack(fill="both", expand=True)
        self._view = view
        if service is not None:
            view.set_status(service.last_status)
        else:
            view.set_status(self._startup_error or "截图服务未启动")

        window.update_idletasks()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        min_width = min(1000, max(760, screen_width - 80))
        recommended = int(
            getattr(view, "recommended_min_height", 720)
        )
        min_height = min(
            max(640, screen_height - 80),
            max(640, recommended),
        )
        width = min(1120, max(min_width, int(screen_width * 0.68)))
        height = min(900, max(min_height, int(screen_height * 0.78)))
        center_on_screen(window, width, height)
        window.minsize(min_width, min_height)
        window.resizable(True, True)
        window.bind(
            "<Destroy>",
            lambda event, w=window, v=view: self._on_window_destroy(event, w, v),
            add="+",
        )
        window.bind(
            "<Map>",
            lambda event, w=window, v=view: (
                v.on_show() if event.widget is w else None
            ),
            add="+",
        )

    def _on_window_destroy(
        self, event: tk.Event, window: tk.Toplevel, view: ControlWindow
    ) -> None:
        if event.widget is not window:
            return
        if self._view is view:
            self._view = None

    def create_settings_ui(self, parent: tk.Misc) -> None:
        from .ui.settings_view import ScreenshotSettingsPanel

        ScreenshotSettingsPanel(
            parent, self, self._on_settings_saved
        ).pack(fill="both", expand=True)

    def _on_settings_saved(self) -> None:
        view = self._view
        if view is None:
            return
        try:
            view.refresh_settings()
            recent = getattr(view, "recent_view", None)
            if recent is not None:
                recent.refresh()
        except tk.TclError:
            pass

    def _ensure_service(self) -> ScreenshotService | None:
        if self.service is None:
            self.start_service()
        return self.service

    def import_images(self, paths: list[str]):
        """Import local images into the recent library and open the editor."""
        service = self._ensure_service()
        if service is None:
            raise RuntimeError(self._startup_error or "截图服务未启动")
        return service.import_images(paths)

    # --------------------------------------------------------------- actions
    def handle_action(self, action: str) -> None:
        log.info("用户操作：截图插件动作 %s", action)
        if action not in self.ACTIONS:
            log.warning("截图插件忽略未知动作：%s", action)
            return
        if action == "open":
            actions = self.context.actions
            if actions is None:
                log.warning("截图插件缺少 open_window 动作")
                return
            actions.open_window()
            return

        service = self._ensure_service()
        if service is None:
            self.set_status(self._startup_error or "截图服务未启动")
            return
        mode = action.removeprefix("capture_")
        service.capture(mode)

    # ----------------------------------------------------------------- state
    @property
    def settings(self) -> ScreenshotSettings:
        service = self._ensure_service()
        if service is not None:
            return service.settings
        return ScreenshotSettings()

    def _refresh_recent_view(self) -> None:
        """Refresh the assistant window even when it stayed mapped."""
        view = self._view
        if view is None:
            return
        try:
            if view.winfo_exists():
                view.on_show()
        except tk.TclError:
            pass

    def _on_service_status(self, message: str) -> None:
        view = self._view
        if view is not None:
            try:
                if view.winfo_exists():
                    view.set_status(message)
                    if view.winfo_viewable():
                        return
            except tk.TclError:
                pass
        if self._is_error_status(message):
            log.warning("截图状态：%s", message)
        else:
            log.info("截图状态：%s", message)
        if self._is_error_status(message):
            try:
                from tkinter import messagebox

                messagebox.showerror("截图", message, parent=None)
            except Exception:
                log.debug("显示截图错误对话框失败", exc_info=True)

    @staticmethod
    def _is_error_status(message: str) -> bool:
        if message.startswith(("已取消", "截图完成", "滚动截图完成")):
            return False
        markers = (
            "失败",
            "无法",
            "不支持",
            "未启动",
            "没有找到",
            "不在屏幕范围内",
            "冲突",
        )
        return any(marker in message for marker in markers)

    def set_status(self, message: str) -> None:
        self._on_service_status(message)

    def status_text(self) -> str:
        service = self.service
        if service is None:
            return self._startup_error or "截图服务未启动"
        return service.last_status

    def hotkey_display(self) -> str:
        return self.settings.hotkey.display()

    def app_hotkey_display(self) -> str:
        actions = self.context.actions
        if actions is None:
            return ""
        try:
            return actions.app_hotkey_display()
        except Exception:
            return ""

    def open_save_folder(self) -> None:
        from quicktools.ui_theme import open_in_file_manager

        path = self.settings.resolved_save_dir()
        log.info("用户操作：打开截图保存目录 %s", path)
        try:
            open_in_file_manager(path)
        except Exception as exc:
            log.exception("打开截图保存目录失败：%s", path)
            self.set_status(f"无法打开保存目录：{exc}")
            return
        self.set_status(f"已打开保存目录：{path}")

    def update_settings(self, **changes) -> ScreenshotSettings:
        service = self._ensure_service()
        if service is None:
            raise RuntimeError(self._startup_error or "截图服务未启动")
        settings = service.update_settings(**changes)
        view = self._view
        if view is not None:
            try:
                view.refresh_settings()
            except tk.TclError:
                pass
        if "hotkey" in changes or "hotkey_enabled" in changes:
            self._start_hotkey(service)
        else:
            self.set_status("设置已保存")
        return settings

    @staticmethod
    def platform_hint() -> str:
        if (
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or os.environ.get("WAYLAND_DISPLAY")
        ):
            return (
                "Wayland：区域/窗口截图使用系统选择器；自由截图在系统全屏后"
                "用编辑器套索裁剪；全局快捷键需绑定到命令行"
            )
        return ""
