"""Application lifecycle, command routing and global state."""

from __future__ import annotations

import queue
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox
from typing import Callable

from . import paths
from .config import AppSettings, HotkeySpec, load_settings, save_settings
from .data_migration import (
    MigrationResult,
    PluginDataError,
    migrate_plugin_data,
    normalize_plugin_data_root,
)
from .hotkey import HotkeyManager
from .ipc import IpcServer
from .launcher import Launcher
from .logging_setup import get_logger
from .plugin_loader import PluginLoader
from .settings_ui import SettingsWindow
from .tray import TrayController
from .ui_theme import enable_high_dpi

log = get_logger(__name__)


class QuickToolsApp:
    def __init__(
        self, start_visible: bool = True, *, start_auto_hide: bool = False
    ) -> None:
        enable_high_dpi()
        paths.ensure_app_dirs()
        self._shutting_down = False
        self._data_migration_busy = False
        self._hotkey_capturing = False
        self.show_error_dialogs = True

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("快捷工具")
        self.root.report_callback_exception = self._report_callback_exception
        self._app_icon_image = None
        self._load_window_icon()

        self.commands: queue.Queue[str] = queue.Queue()
        self.settings: AppSettings = load_settings()
        self.loader = PluginLoader(paths.user_plugins_dir(), paths.builtin_plugins_dir())
        self.hotkey = HotkeyManager(
            self.settings.hotkey, lambda: self.commands.put("toggle")
        )
        self.settings_window: SettingsWindow | None = None
        self._poll_job: str | None = None
        self._restore_launcher_after_settings = False

        configured_root = self.settings.plugin_data_root
        self.launcher = Launcher(
            self,
            self.root,
            plugin_data_root=(
                paths.plugin_data_root(configured_root)
                if configured_root
                else None
            ),
        )
        self.hotkey.start()
        self.ipc = IpcServer(self._enqueue_command)
        self.ipc.start()
        self.tray = TrayController()
        self.tray.start()
        self._refresh_status_ui()

        self._poll_job = self.root.after(50, self._drain_commands)
        if start_visible:
            self.launcher.show(auto_hide=start_auto_hide)

    def _load_window_icon(self) -> None:
        try:
            image = tk.PhotoImage(
                master=self.root, file=str(paths.assets_dir() / "icon.png")
            )
            self.root.iconphoto(True, image)
            self._app_icon_image = image
        except Exception as exc:
            log.warning("应用图标加载失败：%s", exc)

    def apply_window_icon(self, window: tk.Toplevel) -> None:
        if self._app_icon_image is None:
            return
        try:
            window.iconphoto(False, self._app_icon_image)
        except tk.TclError:
            log.debug("窗口图标设置失败", exc_info=True)

    # ------------------------------------------------------------- commands
    def _enqueue_command(self, command: str) -> None:
        self.commands.put(command)

    def _drain_commands(self) -> None:
        self._poll_job = None
        if self._shutting_down:
            return
        handled = 0
        while handled < 10:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            handled += 1
            log.info("处理命令：%s", command)
            if command == "toggle":
                self.launcher.toggle()
            elif command == "show":
                self.launcher.show()
            elif command == "settings":
                self.open_settings()
            elif command.startswith("menu "):
                parts = command.split()
                try:
                    x, y = int(parts[1]), int(parts[2])
                except (IndexError, ValueError):
                    x, y = -1, -1
                self.launcher.show_tray_menu(x, y)
            elif command.startswith("plugin "):
                parts = command.split(" ", 2)
                if len(parts) == 3:
                    self.launcher.dispatch_plugin_action(parts[1], parts[2])
            elif command == "quit":
                if self.quit():
                    return
                # A migration is in progress; keep the command pump alive so
                # the app can be quit once it finishes.
                continue
        self._poll_job = self.root.after(50, self._drain_commands)

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            if not self._shutting_down:
                self._cleanup()

    # -------------------------------------------------------------- hotkey
    def begin_hotkey_capture(self) -> None:
        if self._hotkey_capturing:
            return
        self._hotkey_capturing = True
        self.hotkey.suspend()
        self._refresh_status_ui()

    def cancel_hotkey_capture(self) -> None:
        if not self._hotkey_capturing:
            return
        self._hotkey_capturing = False
        self.hotkey.resume()
        self._refresh_status_ui()

    def set_hotkey(self, new_spec: HotkeySpec) -> tuple[bool, str]:
        old_settings = self.settings
        ok, message = self.hotkey.change(new_spec)
        if not ok:
            self._hotkey_capturing = False
            self._refresh_status_ui()
            return False, message

        new_settings = replace(self.settings, hotkey=new_spec)
        try:
            save_settings(new_settings)
        except Exception as exc:
            log.exception("保存快捷键设置失败")
            self.hotkey.change(old_settings.hotkey)
            self.settings = old_settings
            self._hotkey_capturing = False
            self._refresh_status_ui()
            return False, f"保存设置失败：{exc}"

        self.settings = new_settings
        self._hotkey_capturing = False
        self._refresh_status_ui()
        return True, ""

    def hotkey_status_text(self) -> str:
        if self._hotkey_capturing:
            return "正在录制快捷键…"
        return self.hotkey.status_text()

    def hotkey_status_warning(self) -> bool:
        return not self.hotkey.running

    def mark_first_run_seen(self) -> None:
        """Persist that the launcher welcome hint has been dismissed."""
        if self.settings.first_run_seen:
            return
        updated = replace(self.settings, first_run_seen=True)
        try:
            save_settings(updated)
        except Exception:
            log.exception("保存首次使用提示状态失败")
        self.settings = updated

    def _refresh_status_ui(self) -> None:
        try:
            self.launcher.update_hotkey_status(
                self.hotkey_status_text(), self.hotkey_status_warning()
            )
        except tk.TclError:
            pass
        window = self.settings_window
        if window is not None and self._window_exists(window):
            try:
                window._refresh_hotkey_section()
            except tk.TclError:
                pass

    # -------------------------------------------------------------- plugins
    def hide_for_capture(self) -> Callable[[], None]:
        """Hide every QuickTools window before a screenshot.

        Returns an idempotent callback that restores only the windows that
        were visible when this method was called.
        """
        settings_window = self.settings_window
        restore_settings = False
        if settings_window is not None and self._window_exists(settings_window):
            try:
                if settings_window.winfo_viewable():
                    settings_window.withdraw()
                    restore_settings = True
            except tk.TclError:
                pass
        restore_others = self.launcher.hide_all_windows()

        restored = False

        def restore() -> None:
            nonlocal restored
            if restored:
                return
            restored = True
            restore_others()
            if restore_settings and self._window_exists(settings_window):
                try:
                    settings_window.deiconify()
                    settings_window.lift()
                except tk.TclError:
                    pass

        return restore

    def reload_plugins(self) -> tuple[int, list[str]]:
        count, errors = self.launcher.reload_plugins()
        self._refresh_status_ui()
        return count, errors

    # ------------------------------------------------------- plugin data root
    @property
    def data_migration_busy(self) -> bool:
        return self._data_migration_busy

    def begin_data_migration(self) -> None:
        """Block exit while plugin data is being moved."""
        self._data_migration_busy = True

    def end_data_migration(self) -> None:
        self._data_migration_busy = False

    def current_plugin_data_root(self) -> Path:
        raw = self.settings.plugin_data_root
        return (
            paths.plugin_data_root(raw)
            if raw
            else paths.default_plugin_data_root()
        )

    def suspend_plugins_for_data_root_change(self) -> Path:
        """Stop plugin windows/services before moving their data."""
        old_root = self.current_plugin_data_root()
        self.launcher.suspend_plugins_for_data_root_change()
        return old_root

    def migrate_plugin_data_root(
        self,
        base_settings: AppSettings,
        new_root: str,
        *,
        merge: bool = False,
        progress=None,
        should_cancel=None,
    ) -> tuple[MigrationResult, AppSettings]:
        """Filesystem/config-only migration; safe to call from a worker."""
        _stored, effective = normalize_plugin_data_root(
            new_root, default_root=paths.default_plugin_data_root()
        )
        old_root = paths.plugin_data_root(base_settings.plugin_data_root)
        result = migrate_plugin_data(
            old_root,
            effective,
            merge=merge,
            progress=progress,
            should_cancel=should_cancel,
        )
        new_settings = replace(
            base_settings, plugin_data_root=_stored
        )
        try:
            save_settings(new_settings)
        except Exception as exc:
            try:
                result.rollback()
            except Exception:
                log.exception("回滚插件数据迁移失败")
            raise PluginDataError(
                f"保存设置失败，已尝试回滚：{exc}"
            ) from exc
        result.finalize()
        return result, new_settings

    def resume_plugins_after_data_root_change(
        self, new_settings: AppSettings | None
    ) -> None:
        if new_settings is not None:
            self.settings = new_settings
            raw = new_settings.plugin_data_root
            self.launcher.set_plugin_data_root(
                paths.plugin_data_root(raw) if raw else None
            )
        self.launcher.resume_plugins()
        self.launcher.reload_plugins()
        self._refresh_status_ui()

    # ------------------------------------------------------------- settings
    def open_settings(self) -> None:
        if self.settings_window is not None and self._window_exists(
            self.settings_window
        ):
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            try:
                self.settings_window._refresh_autostart_section()
            except tk.TclError:
                pass
            return
        self._restore_launcher_after_settings = self.launcher.window.winfo_viewable()
        if self._restore_launcher_after_settings:
            self.launcher.hide()
        try:
            self.settings_window = SettingsWindow(self, self.root)
            self.apply_window_icon(self.settings_window)
        except Exception:
            if self._restore_launcher_after_settings:
                self.launcher.show()
            raise

    def settings_closed(self, window: SettingsWindow) -> None:
        if self.settings_window is window:
            self.settings_window = None
        if self._restore_launcher_after_settings and not self._shutting_down:
            self._restore_launcher_after_settings = False
            self.launcher.show()

    def _window_exists(self, window: tk.Misc) -> bool:
        try:
            return bool(window.winfo_exists())
        except tk.TclError:
            return False

    # ----------------------------------------------------------- exceptions
    def _report_callback_exception(self, exc, val, tb) -> None:
        log.error("Tk 回调异常", exc_info=(exc, val, tb))
        if not self.show_error_dialogs or self._shutting_down:
            return
        try:
            messagebox.showerror(
                "快捷工具错误",
                f"{exc.__name__}: {val}\n\n详细信息已写入：\n{paths.log_file()}",
                parent=self.root,
            )
        except Exception:
            pass

    # --------------------------------------------------------------- shutdown
    def quit(self) -> bool:
        if self._data_migration_busy:
            log.warning("插件数据迁移进行中，已忽略退出请求")
            return False
        if self._shutting_down:
            return False
        self._shutting_down = True
        log.info("快捷工具正在退出")
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        self._cleanup()
        try:
            self.root.quit()
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        return True

    def _cleanup(self) -> None:
        self._shutting_down = True
        try:
            self.launcher.flush_window_states()
        except Exception:
            log.exception("保存插件窗口大小失败")
        try:
            self.launcher.stop_background_plugins()
        except Exception:
            log.exception("停止后台插件失败")
        try:
            self.tray.stop()
        except Exception:
            log.exception("停止状态栏图标失败")
        try:
            self.hotkey.stop()
        except Exception:
            log.exception("停止全局快捷键失败")
        try:
            self.ipc.stop()
        except Exception:
            log.exception("停止 IPC 失败")
