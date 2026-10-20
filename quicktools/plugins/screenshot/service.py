"""Screenshot service: hide, capture, select, edit and persist."""

from __future__ import annotations

import io
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from quicktools.plugin_api import PluginActions

from .capture import create_backend
from .capture.base import CaptureBackend
from .editor.annotations import Tool
from .editor.editor_window import CaptureEditor
from .geometry import choose_screen, crop_global_rect
from .models import (
    CaptureCancelled,
    CaptureError,
    CaptureMode,
    Point,
    WindowInfo,
)
from .recent.store import RecentEntry, RecentStore, RecentStoreError
from .scroll.controller import ScrollController
from .selection.overlay import CaptureOverlay
from .settings import ScreenshotSettings, load_settings, save_settings

log = logging.getLogger(__name__)

StatusListener = Callable[[str], None]
RestoreWindows = Callable[[], None]
RecentChangedListener = Callable[[], None]


def _create_portal_client():
    from .capture.portal import PortalScreenshotClient

    return PortalScreenshotClient()


class ScreenshotService:
    def __init__(
        self,
        data_dir: Path,
        root: Any,
        actions: PluginActions | None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.root = root
        self.actions = actions
        self.settings: ScreenshotSettings = load_settings(self.data_dir)
        self.backend: CaptureBackend | None = None
        self.recent: RecentStore | None = None
        self._running = False
        self._busy = False
        self._status_listener: StatusListener | None = None
        self._recent_changed_listener: RecentChangedListener | None = None
        self.last_status = "截图服务尚未启动"
        self._restore: RestoreWindows | None = None
        self._after_job: str | None = None
        self._overlay: CaptureOverlay | None = None
        self._editor: CaptureEditor | None = None
        self._active_entry_id: int | None = None
        self._active_entry_is_new = False
        self._mode = CaptureMode.REGION
        self._source = "QuickTools 截图"
        self._captured = None
        self._current_screen = None
        self._scroll_controller: ScrollController | None = None
        self._portal_queue: queue.Queue[tuple] | None = None
        self._portal_thread: threading.Thread | None = None
        self._portal_after: str | None = None
        self._portal_active = False

    # ------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self.backend = create_backend()
        self.recent = RecentStore(self.data_dir)
        self._running = True
        status = self.backend.status
        if status.available:
            self._report(f"截图服务已就绪 · {status.mode}")
        else:
            self._report(status.detail or status.install_hint or "截图不可用")
        log.info("截图服务已启动：%s", status.mode)

    def stop(self) -> None:
        if not self._running and self._after_job is None:
            return
        self._running = False
        self._cancel_after_job()
        self._cancel_portal()
        editor = self._editor
        self._editor = None
        if editor is not None:
            try:
                editor.dispose()
            except Exception:
                log.exception("关闭截图编辑器失败")
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                log.exception("关闭截图选区失败")
        self._dispose_scroll_controller()
        self._restore_windows()
        recent = self.recent
        self.recent = None
        if recent is not None:
            try:
                recent.close()
            except Exception:
                log.exception("关闭最近截图数据库失败")
        backend = self.backend
        self.backend = None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                log.exception("关闭截图后端失败")
        self._busy = False
        self._captured = None
        self._current_screen = None
        self._status_listener = None
        self.last_status = "截图服务已停止"
        log.info("截图服务已停止")

    def set_status_listener(self, listener: StatusListener | None) -> None:
        self._status_listener = listener

    def set_recent_changed_listener(
        self, listener: RecentChangedListener | None
    ) -> None:
        self._recent_changed_listener = listener

    def _notify_recent_changed(self) -> None:
        listener = self._recent_changed_listener
        if listener is None:
            return
        try:
            listener()
        except Exception:
            log.exception("刷新最近截图列表失败")

    def report_status(self, message: str) -> None:
        self._report(message)

    def _report(self, message: str) -> None:
        self.last_status = message
        listener = self._status_listener
        if listener is not None:
            try:
                listener(message)
            except Exception:
                log.exception("截图状态回调失败")

    # -------------------------------------------------------------- capture
    def capture(self, mode: str) -> None:
        try:
            requested = CaptureMode.from_value(mode)
        except CaptureError as exc:
            self._report(str(exc))
            return
        self._mode = requested
        if not self._running or self.backend is None:
            self._report("截图服务未启动")
            return
        if self._busy:
            self._report("已有截图任务正在进行")
            return
        if not self.backend.status.available:
            self._report(
                self.backend.status.detail
                or self.backend.status.install_hint
                or "当前环境不支持截图"
            )
            return
        capabilities = getattr(self.backend, "capabilities", None)
        capability_info = None
        if callable(capabilities):
            try:
                capability_info = capabilities()
            except Exception:
                capability_info = None
        if capability_info is not None and not capability_info.custom_overlay:
            if capability_info.interactive_portal:
                if requested is CaptureMode.SCROLL:
                    self._report("Wayland 不支持滚动截图")
                    return
                self._start_portal_capture(requested)
                return
            self._report("当前会话不支持截图")
            return
        if capability_info is not None:
            if (
                requested is CaptureMode.WINDOW
                and not capability_info.window_enumeration
            ):
                self._report("当前会话不支持窗口枚举截图")
                return
            if (
                requested is CaptureMode.SCROLL
                and not capability_info.scrolling
            ):
                self._report("当前环境不支持滚动截图")
                return
        self._source = self.backend.name
        self._captured = None
        self._current_screen = None
        self._busy = True
        try:
            if self.actions is not None:
                self._restore = self.actions.hide_windows()
            else:
                self._restore = None
        except Exception as exc:
            self._busy = False
            self._report(f"隐藏 QuickTools 窗口失败：{exc}")
            return
        self._report("正在准备截图…")
        delay = max(50, int(self.settings.hide_delay_ms))
        self._after_job = self.root.after(delay, self._begin_region_capture)

    # -------------------------------------------------------------- portal
    def _start_portal_capture(self, mode: CaptureMode) -> None:
        if self._busy:
            self._report("已有截图任务正在进行")
            return
        self._mode = mode
        self._source = "wayland"
        self._captured = None
        self._current_screen = None
        self._restore = None
        self._busy = True
        try:
            if self.actions is not None:
                self._restore = self.actions.hide_windows()
        except Exception as exc:
            self._busy = False
            self._report(f"隐藏 QuickTools 窗口失败：{exc}")
            return
        portal_queue: queue.Queue[tuple] = queue.Queue()
        self._portal_queue = portal_queue
        self._portal_active = True
        if mode is CaptureMode.FREEFORM:
            self._report("正在请求系统全屏截图…")
        else:
            self._report("请在系统截图选择器中选择区域或窗口…")

        def worker() -> None:
            try:
                time.sleep(max(0.05, self.settings.hide_delay_ms / 1000))
                client = _create_portal_client()
                interactive = mode is not CaptureMode.FREEFORM
                png = client.capture(interactive=interactive)
                portal_queue.put(("done", png))
            except CaptureCancelled:
                portal_queue.put(("cancelled",))
            except Exception as exc:
                portal_queue.put(
                    ("error", str(exc) or exc.__class__.__name__)
                )

        self._portal_thread = threading.Thread(
            target=worker, name="screenshot-portal", daemon=True
        )
        self._portal_thread.start()
        self._portal_after = self.root.after(100, self._poll_portal)

    def _poll_portal(self) -> None:
        self._portal_after = None
        if not self._portal_active or self._portal_queue is None:
            return
        try:
            event = self._portal_queue.get_nowait()
        except queue.Empty:
            self._portal_after = self.root.after(100, self._poll_portal)
            return
        self._portal_active = False
        kind = event[0]
        if kind == "done":
            try:
                with Image.open(io.BytesIO(event[1])) as image:
                    image.load()
                    captured = image.convert("RGBA")
            except Exception as exc:
                self._finish_cancel(f"系统截图文件无效：{exc}")
                return
            initial_tool = (
                Tool.LASSO if self._mode is CaptureMode.FREEFORM else None
            )
            self._on_selected(captured, initial_tool=initial_tool)
            return
        if kind == "cancelled":
            self._finish_cancel("已取消系统截图")
            return
        self._finish_cancel(f"系统截图失败：{event[1]}")

    def _cancel_portal(self) -> None:
        self._portal_active = False
        if self._portal_after is not None:
            try:
                self.root.after_cancel(self._portal_after)
            except Exception:
                pass
            self._portal_after = None
        self._portal_queue = None
        self._portal_thread = None

    def _begin_region_capture(self) -> None:
        self._after_job = None
        backend = self.backend
        if not self._running or backend is None:
            return
        try:
            captured = backend.grab_screen()
        except Exception as exc:
            self._finish_cancel(f"截图失败：{exc}")
            return
        pointer = self._pointer_position(backend)
        screens = backend.screens()
        screen = choose_screen(screens, pointer)
        if screen is None:
            self._finish_cancel("没有找到可截图的显示器")
            return
        windows: list[WindowInfo] = []
        if self._mode is CaptureMode.WINDOW:
            try:
                windows = backend.list_windows()
            except Exception as exc:
                self._finish_cancel(f"枚举窗口失败：{exc}")
                return
            if not windows:
                self._finish_cancel("没有找到可截图的窗口")
                return
        self._captured = captured
        self._current_screen = screen
        try:
            self._overlay = CaptureOverlay(
                self.root,
                captured,
                screen,
                self._mode,
                windows,
                self._on_selected,
                self._on_overlay_cancel,
                on_window_selected=self._on_window_selected,
                on_region_selected=(
                    self._on_scroll_region
                    if self._mode is CaptureMode.SCROLL
                    else None
                ),
            )
        except Exception as exc:
            log.exception("创建截图选区失败")
            self._finish_cancel(f"创建选区失败：{exc}")
            return
        if self._mode is CaptureMode.WINDOW:
            self._report("点击选择一个窗口")
        elif self._mode is CaptureMode.FREEFORM:
            self._report("按住鼠标拖拽绘制套索")
        elif self._mode is CaptureMode.SCROLL:
            self._report("拖拽选择滚动区域")
        else:
            self._report("拖拽选择截图区域")

    def _on_scroll_region(
        self, image: Image.Image, global_rect, screen
    ) -> None:
        self._overlay = None
        self._captured = None
        self._current_screen = None
        try:
            self._scroll_controller = ScrollController(
                self.root,
                global_rect,
                self.settings,
                on_done=self._on_scroll_done,
                on_cancel=self._on_scroll_cancelled,
            )
        except Exception as exc:
            log.exception("启动滚动截图失败")
            self._finish_cancel(f"启动滚动截图失败：{exc}")
            return
        self._report("滚动截图中，可在控制条点击完成或取消")

    def _on_scroll_done(
        self, image: Image.Image, frames: int, reason: str
    ) -> None:
        self._scroll_controller = None
        if image is None:
            self._finish_cancel("滚动截图没有生成结果")
            return
        self._report(f"滚动截图完成（{frames} 帧，{reason}）")
        self._on_selected(image)

    def _on_scroll_cancelled(self, message: str) -> None:
        self._scroll_controller = None
        self._finish_cancel(message)

    def _on_window_selected(self, window: WindowInfo) -> None:
        self._overlay = None
        backend = self.backend
        captured = self._captured
        screen = self._current_screen
        if backend is None or captured is None or screen is None:
            self._finish_cancel("窗口截图状态已失效")
            return
        self._report(f"正在采集窗口：{window.title}")
        raised = False
        try:
            raised = backend.raise_window(window.handle)
        except Exception:
            log.debug("抬升截图窗口失败", exc_info=True)
        if raised:
            self._after_job = self.root.after(
                180,
                lambda: self._capture_window_after_raise(
                    window, captured, screen
                ),
            )
        else:
            self._capture_window_after_raise(window, captured, screen)

    def _capture_window_after_raise(
        self, window: WindowInfo, fallback_captured, screen
    ) -> None:
        self._after_job = None
        backend = self.backend
        if not self._running or backend is None:
            return
        captured = fallback_captured
        try:
            captured = backend.grab_screen()
        except Exception:
            log.debug("窗口抬升后抓屏失败，使用冻结画面", exc_info=True)
        image = crop_global_rect(captured, window.rect)
        if image is None:
            image = crop_global_rect(fallback_captured, window.rect)
        if image is None:
            self._finish_cancel("窗口不在屏幕范围内")
            return
        self._on_selected(image)

    def _pointer_position(self, backend: CaptureBackend) -> Point | None:
        try:
            pointer = backend.cursor_position()
        except Exception:
            pointer = None
        if pointer is not None:
            return pointer
        try:
            return Point(
                int(self.root.winfo_pointerx()),
                int(self.root.winfo_pointery()),
            )
        except Exception:
            return None

    def _on_selected(
        self, image: Image.Image, *, initial_tool: Tool | None = None
    ) -> None:
        self._overlay = None
        self._captured = None
        self._current_screen = None
        self._cancel_portal()
        try:
            self._open_editor(image, initial_tool=initial_tool)
        except Exception as exc:
            log.exception("打开截图编辑器失败")
            self._discard_new_entry()
            self._finish_cancel(f"打开编辑器失败：{exc}")

    def _on_overlay_cancel(self) -> None:
        self._overlay = None
        self._finish_cancel("已取消截图")

    def _open_editor(
        self,
        image: Image.Image,
        *,
        record_new: bool = True,
        initial_tool: Tool | None = None,
    ) -> None:
        editor = self._editor
        if editor is not None:
            editor.dispose()
        entry_id = None
        recent = self.recent
        if record_new and recent is not None:
            try:
                entry = recent.add_png(
                    self._png_bytes(image),
                    mode=self._mode.value,
                    source=self._source,
                )
                entry_id = entry.id
                self._prune_recent()
            except RecentStoreError as exc:
                log.warning("保存最近截图失败：%s", exc)
            except Exception:
                log.exception("保存最近截图失败")
        if record_new:
            self._active_entry_id = entry_id
            self._active_entry_is_new = entry_id is not None
        editor_kwargs: dict[str, Any] = {
            "on_copy": self._copy_image,
            "on_save": self._save_image,
            "on_close": self._editor_closed,
            "on_return": self._editor_closed_and_return,
            "on_autosave": self._autosave_image,
            "require_action_on_close": record_new,
        }
        if initial_tool is not None:
            editor_kwargs["initial_tool"] = initial_tool
        self._editor = CaptureEditor(
            self.root,
            image,
            self.settings,
            **editor_kwargs,
        )
        self._report("截图完成，可复制、保存或关闭")

    # ------------------------------------------------------------- actions
    def _copy_image(self, image: Image.Image) -> None:
        if self.actions is None:
            raise RuntimeError("截图插件缺少剪贴板桥接")
        png = self._png_bytes(image)
        self.actions.copy_png_to_clipboard(png)
        self._update_active_entry(png)
        self._report("截图已复制到剪贴板")

    def _autosave_image(self, image: Image.Image) -> None:
        """Persist editor changes into the recent entry (and saved file)."""
        png = self._png_bytes(image)
        self._update_active_entry(png)
        entry_id = self._active_entry_id
        recent = self.recent
        if entry_id is None or recent is None:
            return
        try:
            entry = recent.get(entry_id)
        except Exception:
            log.exception("读取最近截图记录失败")
            return
        if entry is None or not entry.saved_path:
            return
        try:
            self._write_image_file(image, Path(entry.saved_path))
        except Exception:
            log.exception("自动保存截图文件失败")

    def _write_image_file(self, image: Image.Image, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        suffix = target.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            background.alpha_composite(rgba)
            payload = background.convert("RGB")
            payload.save(
                target, format="JPEG", quality=self.settings.jpeg_quality
            )
        elif suffix == ".webp":
            payload = image.convert("RGBA")
            payload.save(
                target, format="WEBP", quality=self.settings.jpeg_quality
            )
        else:
            image.save(target, format="PNG")

    def _save_image(self, image: Image.Image, path: Path | None) -> Path:
        target = Path(path) if path is not None else self._next_save_path()
        self._write_image_file(image, target)
        self._update_active_entry(self._png_bytes(image), saved_path=target)
        self._report(f"截图已保存：{target}")
        return target

    def _next_save_path(self) -> Path:
        directory = self.settings.resolved_save_dir()
        image_format = self.settings.image_format
        extension = "jpg" if image_format == "jpeg" else image_format
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = directory / f"screenshot_{stamp}"
        candidate = base.with_suffix(f".{extension}")
        index = 1
        while candidate.exists():
            candidate = directory / f"screenshot_{stamp}_{index}.{extension}"
            index += 1
        return candidate

    def _update_active_entry(
        self, png: bytes, *, saved_path: Path | None = None
    ) -> None:
        entry_id = self._active_entry_id
        recent = self.recent
        if entry_id is None or recent is None:
            return
        try:
            updated = recent.update_png(entry_id, png)
            if updated is not None and saved_path is not None:
                recent.mark_saved(entry_id, saved_path)
            self._prune_recent()
        except Exception:
            log.exception("更新最近截图失败")

    def _editor_closed_and_return(self, done: bool) -> None:
        self._editor_closed(done, return_to_assistant=True)

    def _editor_closed(
        self, done: bool, *, return_to_assistant: bool = False
    ) -> None:
        self._editor = None
        entry_id = self._active_entry_id
        is_new = self._active_entry_is_new
        self._active_entry_id = None
        self._active_entry_is_new = False
        if (
            not done
            and is_new
            and entry_id is not None
            and self.recent is not None
        ):
            try:
                self.recent.delete(entry_id)
                self._prune_recent()
            except Exception:
                log.exception("删除未完成的截图记录失败")
        self._busy = False
        self._captured = None
        self._current_screen = None
        self._cancel_portal()
        self._dispose_scroll_controller()
        if return_to_assistant:
            self._restore_windows()
            self._show_assistant()
            self._notify_recent_changed()
            self._report(
                "截图已完成，已返回截图助手"
                if done
                else "已关闭截图，已返回截图助手"
            )
        else:
            self._restore = None
            self._hide_windows_on_close()
            self._report("截图已完成" if done else "已关闭截图")

    def _discard_new_entry(self) -> None:
        entry_id = self._active_entry_id
        is_new = self._active_entry_is_new
        self._active_entry_id = None
        self._active_entry_is_new = False
        if is_new and entry_id is not None and self.recent is not None:
            try:
                self.recent.delete(entry_id)
                self._prune_recent()
            except Exception:
                log.exception("删除未完成的截图记录失败")

    def _dispose_scroll_controller(self) -> None:
        controller = self._scroll_controller
        self._scroll_controller = None
        if controller is not None:
            try:
                controller.dispose()
            except Exception:
                log.exception("关闭滚动截图控制条失败")

    def _finish_cancel(self, message: str) -> None:
        self._busy = False
        self._captured = None
        self._current_screen = None
        self._cancel_portal()
        self._dispose_scroll_controller()
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            try:
                overlay.destroy()
            except Exception:
                pass
        self._restore_windows()
        self._report(message)

    def _restore_windows(self) -> None:
        restore = self._restore
        self._restore = None
        if restore is not None:
            try:
                restore()
            except Exception:
                log.exception("恢复 QuickTools 窗口失败")

    def _show_assistant(self) -> None:
        actions = self.actions
        if actions is None:
            return
        try:
            actions.open_window()
        except Exception:
            log.exception("返回截图助手失败")

    def _hide_windows_on_close(self) -> None:
        """Plain close: hide every visible QuickTools window, no restore."""
        actions = self.actions
        if actions is None:
            return
        try:
            actions.hide_windows()
        except Exception:
            log.exception("关闭截图后隐藏 QuickTools 窗口失败")

    def _cancel_after_job(self) -> None:
        job = self._after_job
        self._after_job = None
        if job is not None:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    # -------------------------------------------------------------- recent
    def recent_entries(
        self,
        limit: int = 8,
        *,
        favorite: bool | None = None,
        mode: str | None = None,
    ) -> list[RecentEntry]:
        recent = self.recent
        if recent is None:
            return []
        try:
            return recent.list(limit=limit, favorite=favorite, mode=mode)
        except Exception:
            log.exception("读取最近截图失败")
            return []

    def set_recent_favorite(
        self, entry: RecentEntry, favorite: bool
    ) -> RecentEntry | None:
        recent = self.recent
        if recent is None:
            self._report("截图服务未启动")
            return None
        try:
            updated = recent.set_favorite(entry.id, favorite)
        except Exception as exc:
            log.exception("收藏截图失败")
            self._report(f"收藏失败：{exc}")
            return None
        if updated is None:
            self._report("截图记录不存在")
            return None
        self._report("已收藏截图" if favorite else "已取消收藏")
        return updated

    def toggle_recent_favorite(
        self, entry: RecentEntry
    ) -> RecentEntry | None:
        recent = self.recent
        if recent is None:
            self._report("截图服务未启动")
            return None
        current = recent.get(entry.id) or entry
        return self.set_recent_favorite(current, not current.favorite)

    def open_recent(self, entry: RecentEntry) -> None:
        recent = self.recent
        if recent is None or self._busy:
            return
        path = recent.image_path(entry)
        if path is None:
            self._report("截图文件不存在")
            return
        try:
            with Image.open(path) as image:
                image.load()
                copied = image.copy()
        except Exception as exc:
            log.exception("打开最近截图失败")
            self._report(f"打开截图失败：{exc}")
            return
        self._busy = True
        self._active_entry_id = entry.id
        self._active_entry_is_new = False
        try:
            self._mode = (
                CaptureMode.from_value(entry.mode)
                if entry.mode
                else CaptureMode.REGION
            )
        except CaptureError:
            self._mode = CaptureMode.REGION
        try:
            self._open_editor(copied, record_new=False)
        except Exception as exc:
            self._busy = False
            self._active_entry_id = None
            self._active_entry_is_new = False
            log.exception("打开最近截图编辑器失败")
            self._report(f"打开编辑器失败：{exc}")

    def copy_recent(self, entry: RecentEntry) -> None:
        if self.actions is None:
            self._report("剪贴板服务不可用")
            return
        recent = self.recent
        if recent is None:
            return
        path = recent.image_path(entry)
        if path is None:
            self._report("截图文件不存在")
            return
        try:
            png = path.read_bytes()
            self.actions.copy_png_to_clipboard(png)
        except Exception as exc:
            log.exception("复制最近截图失败")
            self._report(f"复制失败：{exc}")
            return
        self._report("截图已复制到剪贴板")

    def delete_recent(self, entry: RecentEntry) -> None:
        recent = self.recent
        if recent is None:
            return
        if recent.delete(entry.id):
            self._report("已删除截图记录")
        self._prune_recent()

    def clear_recent(self) -> None:
        recent = self.recent
        if recent is not None:
            recent.clear()
            self._report("已清空最近截图")

    def _prune_recent(self) -> None:
        recent = self.recent
        if recent is None:
            return
        try:
            recent.prune(
                max_entries=self.settings.recent_limit,
                max_bytes=self.settings.recent_max_mb * 1024 * 1024,
            )
        except Exception:
            log.exception("清理最近截图失败")

    # -------------------------------------------------------------- settings
    def update_settings(self, **changes: Any) -> ScreenshotSettings:
        from dataclasses import replace

        updated = replace(self.settings, **changes).normalized()
        self.settings = save_settings(self.data_dir, updated)
        self._prune_recent()
        self._report("设置已保存")
        return self.settings

    def open_save_folder(self) -> Path:
        path = self.settings.resolved_save_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _png_bytes(image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
