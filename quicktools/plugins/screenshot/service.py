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

from PIL import Image, ImageOps

from quicktools.plugin_api import PluginActions

from .capture import create_backend
from .capture.base import CaptureBackend
from .editor.annotations import Tool
from .editor.editor_window import CaptureEditor, NavigationTarget
from .geometry import choose_screen, crop_global_rect
from .models import (
    CaptureCancelled,
    CaptureError,
    CaptureMode,
    Point,
    Rect,
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
        self._active_entry_id: str | None = None
        self._active_entry_is_new = False
        self._navigation_ids: list[str] = []
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
        self.recent = RecentStore(
            self.data_dir, self.settings.resolved_save_dir()
        )
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
        self._navigation_ids = []
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
        log.info("用户操作：请求截图，模式=%s", mode)
        try:
            requested = CaptureMode.from_value(mode)
        except CaptureError as exc:
            log.warning("截图请求被拒绝：%s", exc)
            self._report(str(exc))
            return
        if requested is CaptureMode.IMPORT:
            log.warning("截图请求被拒绝：导入图片不是截图模式")
            self._report("导入图片不是截图模式")
            return
        self._mode = requested
        if not self._running or self.backend is None:
            log.warning("截图请求失败：截图服务未启动")
            self._report("截图服务未启动")
            return
        if self._busy:
            log.warning("截图请求失败：已有截图任务正在进行")
            self._report("已有截图任务正在进行")
            return
        if not self.backend.status.available:
            detail = (
                self.backend.status.detail
                or self.backend.status.install_hint
                or "当前环境不支持截图"
            )
            log.warning("截图请求失败：%s", detail)
            self._report(detail)
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
                    log.warning("截图请求失败：Wayland 不支持滚动截图")
                    self._report("Wayland 不支持滚动截图")
                    return
                self._start_portal_capture(requested)
                return
            log.warning("截图请求失败：当前会话不支持截图")
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
            log.exception("截图前隐藏 QuickTools 窗口失败")
            self._busy = False
            self._report(f"隐藏 QuickTools 窗口失败：{exc}")
            return
        log.info(
            "截图：开始%s，后端=%s，隐藏延迟=%dms",
            requested.label,
            self.backend.name,
            max(50, int(self.settings.hide_delay_ms)),
        )
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
            log.exception("Portal 截图前隐藏 QuickTools 窗口失败")
            self._busy = False
            self._report(f"隐藏 QuickTools 窗口失败：{exc}")
            return
        log.info("截图：启动 Wayland portal，模式=%s", mode.label)
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
                log.exception("Wayland 系统截图文件无效")
                self._finish_cancel(f"系统截图文件无效：{exc}")
                return
            log.info(
                "截图：Wayland portal 返回图片 %d×%d",
                captured.width,
                captured.height,
            )
            initial_tool = (
                Tool.LASSO if self._mode is CaptureMode.FREEFORM else None
            )
            self._on_selected(captured, initial_tool=initial_tool)
            return
        if kind == "cancelled":
            log.info("用户操作：取消 Wayland 系统截图")
            self._finish_cancel("已取消系统截图")
            return
        log.warning("Wayland 系统截图失败：%s", event[1])
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
            log.exception("截图抓屏失败")
            self._finish_cancel(f"截图失败：{exc}")
            return
        pointer = self._pointer_position(backend)
        screens = backend.screens()
        screen = choose_screen(screens, pointer)
        if screen is None:
            log.warning("截图失败：没有找到可截图的显示器")
            self._finish_cancel("没有找到可截图的显示器")
            return
        log.info(
            "截图：抓屏 %d×%d，显示器=%s %s，指针=%s",
            captured.image.width,
            captured.image.height,
            screen.name,
            screen.rect,
            pointer,
        )
        windows: list[WindowInfo] = []
        if self._mode is CaptureMode.WINDOW:
            try:
                windows = backend.list_windows()
            except Exception as exc:
                log.exception("枚举窗口失败")
                self._finish_cancel(f"枚举窗口失败：{exc}")
                return
            if not windows:
                log.warning("截图失败：没有找到可截图的窗口")
                self._finish_cancel("没有找到可截图的窗口")
                return
            log.info("截图：枚举到 %d 个可选窗口", len(windows))
            for item in windows:
                log.debug(
                    "截图窗口：z=%s 标题=%r 应用=%r 区域=%s",
                    item.z_order,
                    item.title,
                    item.app_name,
                    item.rect,
                )
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
        log.info("截图：开始滚动截图，区域=%s", global_rect)
        self._report("滚动截图中，可在控制条点击完成或取消")

    def _on_scroll_done(
        self, image: Image.Image, frames: int, reason: str
    ) -> None:
        self._scroll_controller = None
        if image is None:
            log.warning("滚动截图没有生成结果：%s", reason)
            self._finish_cancel("滚动截图没有生成结果")
            return
        log.info(
            "截图：滚动截图完成，帧数=%d，原因=%s，结果=%d×%d",
            frames,
            reason,
            image.width,
            image.height,
        )
        self._report(f"滚动截图完成（{frames} 帧，{reason}）")
        self._on_selected(image)

    def _on_scroll_cancelled(self, message: str) -> None:
        self._scroll_controller = None
        log.info("用户操作：取消滚动截图：%s", message)
        self._finish_cancel(message)

    def _on_window_selected(self, window: WindowInfo) -> None:
        self._overlay = None
        backend = self.backend
        captured = self._captured
        screen = self._current_screen
        if backend is None or captured is None or screen is None:
            log.warning("窗口截图状态已失效，取消截图")
            self._finish_cancel("窗口截图状态已失效")
            return
        log.info(
            "用户操作：选择窗口 id=%s 标题=%r 应用=%r 区域=%s",
            window.handle,
            window.title,
            window.app_name,
            window.rect,
        )
        self._report(f"正在采集窗口：{window.title}")
        raised = False
        try:
            raised = backend.raise_window(window.handle)
        except Exception:
            log.exception("抬升截图窗口失败：%s", window.handle)
        log.info("截图：窗口抬升%s", "成功" if raised else "失败，使用当前画面")
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
            log.warning(
                "窗口抬升后抓屏失败，使用冻结画面", exc_info=True
            )
        capture_rect = self._window_capture_rect(window.rect)
        log.info(
            "截图：窗口区域=%s，外扩=%dpx，最终区域=%s",
            window.rect,
            max(0, int(self.settings.window_margin_px)),
            capture_rect,
        )
        image = crop_global_rect(captured, capture_rect)
        if image is None:
            log.warning("截图：窗口区域不在抓屏范围内，尝试冻结画面")
            image = crop_global_rect(fallback_captured, capture_rect)
        if image is None:
            log.warning("截图失败：窗口不在屏幕范围内")
            self._finish_cancel("窗口不在屏幕范围内")
            return
        log.info("截图：窗口裁剪得到 %d×%d", image.width, image.height)
        self._on_selected(image)

    def _window_capture_rect(self, rect: Rect) -> Rect:
        margin = max(0, int(self.settings.window_margin_px))
        if margin == 0:
            return rect
        return Rect(
            rect.x - margin,
            rect.y - margin,
            rect.width + margin * 2,
            rect.height + margin * 2,
        )

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
        log.info(
            "截图：选区完成，结果 %d×%d，模式=%s，初始工具=%s",
            image.width,
            image.height,
            self._mode.value,
            getattr(initial_tool, "value", initial_tool),
        )
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
            except RecentStoreError as exc:
                log.warning("保存最近截图失败：%s", exc)
            except Exception:
                log.exception("保存最近截图失败")
        if record_new:
            self._active_entry_id = entry_id
            self._active_entry_is_new = entry_id is not None
        has_newer, has_older = self._prepare_navigation(
            self._active_entry_id
        )
        log.info(
            "编辑器：打开%s，记录 id=%s，图片=%d×%d，模式=%s，来源=%s，"
            "可切换：更新=%s 更早=%s",
            "新截图" if record_new else "最近截图",
            self._active_entry_id,
            image.width,
            image.height,
            self._mode.value,
            self._source,
            has_newer,
            has_older,
        )
        editor_kwargs: dict[str, Any] = {
            "on_copy": self._copy_image,
            "on_save": self._save_image,
            "on_close": self._editor_closed,
            "on_return": self._editor_closed_and_return,
            "on_autosave": self._autosave_image,
            "on_navigate": self._navigate_editor,
            "nav_has_newer": has_newer,
            "nav_has_older": has_older,
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

    # ------------------------------------------------------------ navigation
    def _prepare_navigation(
        self, current_id: str | None
    ) -> tuple[bool, bool]:
        self._navigation_ids = []
        recent = self.recent
        if current_id is None or recent is None:
            return False, False
        try:
            entries = recent.list(limit=None)
        except Exception:
            log.exception("读取最近截图导航列表失败")
            return False, False
        self._navigation_ids = [entry.id for entry in entries]
        try:
            index = self._navigation_ids.index(current_id)
        except ValueError:
            log.warning(
                "编辑器导航：当前记录 id=%s 不在最近列表中", current_id
            )
            return False, False
        log.debug(
            "编辑器导航：快照 %d 条，当前索引=%d，id=%s",
            len(self._navigation_ids),
            index,
            current_id,
        )
        return (
            self._navigation_neighbor(index, -1) is not None,
            self._navigation_neighbor(index, 1) is not None,
        )

    def _navigation_neighbor(
        self, index: int, direction: int
    ) -> int | None:
        recent = self.recent
        ids = self._navigation_ids
        if recent is None:
            return None
        candidate = index + direction
        while 0 <= candidate < len(ids):
            entry = recent.get(ids[candidate])
            if entry is not None and recent.image_path(entry) is not None:
                return candidate
            candidate += direction
        return None

    def _navigate_editor(self, direction: int) -> NavigationTarget | None:
        label = "上一张（更新）" if direction == -1 else "下一张（更早）"
        log.info("用户操作：编辑器切换%s", label)
        if direction not in (-1, 1):
            log.warning("编辑器导航：无效方向 %s", direction)
            return None
        recent = self.recent
        current_id = self._active_entry_id
        ids = self._navigation_ids
        if recent is None or current_id is None:
            log.warning(
                "编辑器导航失败：最近库或当前记录不可用（current=%s）",
                current_id,
            )
            return None
        try:
            index = ids.index(current_id)
        except ValueError:
            log.warning(
                "编辑器导航失败：当前记录 id=%s 不在导航快照中",
                current_id,
            )
            return None
        target_index = self._navigation_neighbor(index, direction)
        if target_index is None:
            log.info("编辑器导航：没有%s可切换", label)
            return None
        entry = recent.get(ids[target_index])
        if entry is None:
            log.warning(
                "编辑器导航失败：目标记录 id=%s 不存在",
                ids[target_index],
            )
            return None
        path = recent.image_path(entry)
        if path is None:
            log.warning(
                "编辑器导航失败：目标记录 id=%s 的图片文件不存在",
                entry.id,
            )
            return None
        try:
            with Image.open(path) as image:
                image.load()
                copied = image.copy()
        except Exception:
            log.exception("打开相邻截图失败：%s", path)
            return None
        log.info(
            "编辑器导航：切换到记录 id=%s，%d×%d，文件=%s（%s → %s）",
            entry.id,
            copied.width,
            copied.height,
            path,
            current_id,
            entry.id,
        )
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
        has_newer = self._navigation_neighbor(target_index, -1) is not None
        has_older = self._navigation_neighbor(target_index, 1) is not None
        return NavigationTarget(
            image=copied,
            entry_id=entry.id,
            has_newer=has_newer,
            has_older=has_older,
        )

    # ------------------------------------------------------------- actions
    def _copy_image(self, image: Image.Image) -> None:
        if self.actions is None:
            log.error("复制截图失败：截图插件缺少剪贴板桥接")
            raise RuntimeError("截图插件缺少剪贴板桥接")
        png = self._png_bytes(image)
        log.info(
            "用户操作：复制截图，%d×%d，%d 字节",
            image.width,
            image.height,
            len(png),
        )
        self.actions.copy_png_to_clipboard(png)
        self._update_active_entry(png)
        self._report("截图已复制到剪贴板")

    def _autosave_image(self, image: Image.Image) -> bool:
        """Persist editor changes into the recent entry (and saved file)."""
        png = self._png_bytes(image)
        if not self._update_active_entry(png):
            log.warning(
                "自动保存失败：最近记录 id=%s 未能更新",
                self._active_entry_id,
            )
            return False
        return True

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
        if path is None:
            # Screenshots already live in the save directory. Plain "保存"
            # updates that managed file instead of creating a duplicate.
            self._update_active_entry(self._png_bytes(image))
            target = None
            recent = self.recent
            if recent is not None and self._active_entry_id is not None:
                entry = recent.get(self._active_entry_id)
                if entry is not None:
                    target = entry.path
            if target is None:
                target = self._next_save_path()
                self._write_image_file(image, target)
            log.info(
                "用户操作：保存截图到最近文件 %s（%d×%d）",
                target,
                image.width,
                image.height,
            )
            self._report(f"截图已保存：{target}")
            return target
        target = Path(path)
        log.info(
            "用户操作：另存截图到 %s（%d×%d）",
            target,
            image.width,
            image.height,
        )
        self._write_image_file(image, target)
        # Exports are snapshots; the managed recent file still tracks edits.
        self._update_active_entry(self._png_bytes(image))
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

    def _update_active_entry(self, png: bytes) -> bool:
        entry_id = self._active_entry_id
        recent = self.recent
        if entry_id is None or recent is None:
            return True
        try:
            updated = recent.update_png(entry_id, png)
            if updated is None:
                log.warning("更新最近截图失败：记录 id=%s 不存在", entry_id)
            else:
                log.debug(
                    "最近截图：记录 id=%s 已更新为 %d×%d，%d 字节，文件=%s",
                    entry_id,
                    updated.width,
                    updated.height,
                    len(png),
                    updated.path,
                )
            return updated is not None
        except Exception:
            log.exception("更新最近截图失败：id=%s", entry_id)
            return False

    def _editor_closed_and_return(self, done: bool) -> None:
        self._editor_closed(done, return_to_assistant=True)

    def _editor_closed(
        self, done: bool, *, return_to_assistant: bool = False
    ) -> None:
        log.info(
            "用户操作：关闭截图编辑器，完成=%s，返回助手=%s，记录 id=%s",
            done,
            return_to_assistant,
            self._active_entry_id,
        )
        self._editor = None
        # 关闭即保留：打开编辑器时原图已写入最近截图，改动又由自动保存落库，
        # 因此不再删除“没动过就关闭”的新记录。
        self._active_entry_id = None
        self._active_entry_is_new = False
        self._navigation_ids = []
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
        self._navigation_ids = []
        if is_new and entry_id is not None and self.recent is not None:
            try:
                self.recent.delete(entry_id)
                log.info("截图：删除未完成的最近文件 id=%s", entry_id)
            except Exception:
                log.exception(
                    "删除未完成的截图文件失败：id=%s", entry_id
                )

    def _dispose_scroll_controller(self) -> None:
        controller = self._scroll_controller
        self._scroll_controller = None
        if controller is not None:
            try:
                controller.dispose()
            except Exception:
                log.exception("关闭滚动截图控制条失败")

    def _finish_cancel(self, message: str) -> None:
        log.info("截图流程结束：%s", message)
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
                log.exception("销毁截图选区失败")
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
            entries = recent.list(limit=limit, favorite=favorite, mode=mode)
            log.debug(
                "最近截图：查询 limit=%s 收藏=%s 模式=%s -> %d 条",
                limit,
                favorite,
                mode,
                len(entries),
            )
            return entries
        except Exception:
            log.exception("读取最近截图失败")
            return []

    def set_recent_favorite(
        self, entry: RecentEntry, favorite: bool
    ) -> RecentEntry | None:
        log.info(
            "用户操作：%s最近截图 id=%s",
            "收藏" if favorite else "取消收藏",
            entry.id,
        )
        recent = self.recent
        if recent is None:
            log.warning("收藏截图失败：截图服务未启动")
            self._report("截图服务未启动")
            return None
        try:
            updated = recent.set_favorite(entry.id, favorite)
        except Exception as exc:
            log.exception("收藏截图失败：id=%s", entry.id)
            self._report(f"收藏失败：{exc}")
            return None
        if updated is None:
            log.warning(
                "收藏截图失败：记录 id=%s 不存在或文件名无法修改", entry.id
            )
            self._report("收藏失败：记录不存在或文件改名失败")
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

    def import_images(self, paths: list[str]) -> list[RecentEntry]:
        """Copy local images into the recent library and edit the first one."""
        log.info("用户操作：导入图片，共 %d 个文件", len(paths))
        if not paths:
            return []
        recent = self.recent
        if not self._running or recent is None:
            log.warning("导入图片失败：截图服务未启动")
            self._report("截图服务未启动")
            return []
        if self._busy:
            log.warning("导入图片失败：已有截图任务正在进行")
            self._report("已有截图任务正在进行")
            return []

        imported: list[RecentEntry] = []
        failed = 0
        for raw in paths:
            path = Path(raw)
            try:
                with Image.open(path) as image:
                    image.load()
                    oriented = ImageOps.exif_transpose(image)
                    has_alpha = oriented.mode in ("RGBA", "LA") or (
                        oriented.mode == "P"
                        and "transparency" in oriented.info
                    )
                    converted = oriented.convert(
                        "RGBA" if has_alpha else "RGB"
                    )
                    png = self._png_bytes(converted)
                entry = recent.add_png(
                    png,
                    mode=CaptureMode.IMPORT.value,
                    source=f"导入：{path}",
                )
            except Exception as exc:
                failed += 1
                log.warning("导入图片失败：%s（%s）", path, exc)
                continue
            imported.append(entry)
            log.info(
                "导入图片：%s → 最近截图 id=%s，%d×%d，文件=%s",
                path,
                entry.id,
                entry.width,
                entry.height,
                entry.path,
            )

        if not imported:
            self._report("导入图片失败：无法导入所选图片")
            return []
        self._notify_recent_changed()
        self._source = "导入图片"
        self.open_recent(imported[0])
        editor_opened = self._editor is not None
        if failed:
            message = f"已导入 {len(imported)} 张图片，{failed} 张未能导入"
        else:
            message = f"已导入 {len(imported)} 张图片"
        if not editor_opened:
            message += "；打开编辑器失败"
        self._report(message)
        return imported

    def open_recent(self, entry: RecentEntry) -> None:
        log.info(
            "用户操作：打开最近截图 id=%s，模式=%s，尺寸=%d×%d，"
            "收藏=%s，文件=%s",
            entry.id,
            entry.mode,
            entry.width,
            entry.height,
            bool(entry.favorite),
            entry.path,
        )
        recent = self.recent
        if recent is None:
            log.warning("打开最近截图失败：截图服务未启动")
            return
        if self._busy:
            log.warning("打开最近截图失败：已有截图任务正在进行")
            return
        path = recent.image_path(entry)
        if path is None:
            log.warning(
                "打开最近截图失败：图片文件不存在，记录 id=%s，路径=%s",
                entry.id,
                entry.path,
            )
            self._report("截图文件不存在")
            return
        log.info("最近截图：读取文件 %s", path)
        try:
            with Image.open(path) as image:
                image.load()
                copied = image.copy()
        except Exception as exc:
            log.exception("打开最近截图失败：%s", path)
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
        log.info(
            "用户操作：复制最近截图 id=%s（%d×%d）",
            entry.id,
            entry.width,
            entry.height,
        )
        if self.actions is None:
            log.warning("复制最近截图失败：剪贴板服务不可用")
            self._report("剪贴板服务不可用")
            return
        recent = self.recent
        if recent is None:
            log.warning("复制最近截图失败：截图服务未启动")
            return
        path = recent.image_path(entry)
        if path is None:
            log.warning(
                "复制最近截图失败：图片文件不存在，记录 id=%s，路径=%s",
                entry.id,
                entry.path,
            )
            self._report("截图文件不存在")
            return
        try:
            if path.suffix.lower() == ".png":
                png = path.read_bytes()
            else:
                with Image.open(path) as image:
                    image.load()
                    png = self._png_bytes(image)
            self.actions.copy_png_to_clipboard(png)
            log.info(
                "最近截图：id=%s 已复制到剪贴板，%d 字节",
                entry.id,
                len(png),
            )
        except Exception as exc:
            log.exception("复制最近截图失败：id=%s", entry.id)
            self._report(f"复制失败：{exc}")
            return
        self._report("截图已复制到剪贴板")

    def delete_recent(self, entry: RecentEntry) -> None:
        log.info("用户操作：删除最近截图 id=%s，文件=%s", entry.id, entry.path)
        recent = self.recent
        if recent is None:
            log.warning("删除最近截图失败：截图服务未启动")
            self._report("截图服务未启动")
            return
        try:
            deleted = recent.delete(entry.id)
        except Exception:
            log.exception("删除最近截图文件失败：id=%s", entry.id)
            self._report("删除截图失败，详见日志")
            return
        if not deleted:
            log.warning(
                "删除最近截图失败：记录 id=%s 不存在或文件无法删除", entry.id
            )
            self._report("删除失败：文件不存在或无法删除")
            return
        log.info("最近截图：已删除文件 id=%s", entry.id)
        self._report("已删除截图及文件")

    def clear_recent(self) -> None:
        log.info("用户操作：清空最近截图")
        recent = self.recent
        if recent is None:
            log.warning("清空最近截图失败：截图服务未启动")
            self._report("截图服务未启动")
            return
        try:
            count = recent.clear()
        except Exception:
            log.exception("清空最近截图文件失败")
            self._report("清空最近截图失败，详见日志")
            return
        log.info("最近截图：已清空 %d 个文件", count)
        if count:
            self._report(f"已清空最近截图（删除 {count} 个文件）")
        else:
            self._report("已清空最近截图")

    # -------------------------------------------------------------- settings
    def update_settings(self, **changes: Any) -> ScreenshotSettings:
        from dataclasses import replace

        log.info("用户操作：修改截图设置 %s", changes)
        old_save_dir = self.settings.resolved_save_dir()
        updated = replace(self.settings, **changes).normalized()
        self.settings = save_settings(self.data_dir, updated)
        new_save_dir = self.settings.resolved_save_dir()
        if new_save_dir != old_save_dir and self.recent is not None:
            self.recent.set_save_dir(new_save_dir)
            log.info("最近截图：保存目录已切换为 %s", new_save_dir)
        log.info(
            "截图设置：已保存（外扩=%dpx，格式=%s，保存目录=%s）",
            updated.window_margin_px,
            updated.image_format,
            new_save_dir,
        )
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
