"""Background clipboard service shared by the plugin window and launcher."""

from __future__ import annotations

import io
import logging
import queue
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .backends import create_backend
from .backends.base import ClipboardBackend
from .models import (
    BackendStatus,
    ClipboardContent,
    ClipboardEntry,
    ClipboardError,
    ClipboardKind,
    PartialFilesError,
    content_digest,
    current_platform,
    kind_value,
)
from .platform_utils import accessible_paths, paths_to_uri_list
from .settings import ClipboardSettings, load_settings, save_settings
from .store import ClipboardStore

log = logging.getLogger(__name__)

Listener = Callable[[str, int | None], None]


class ClipboardService:
    """Own the backend, SQLite store and debounced capture queue.

    The backend thread only puts snapshots on a queue. Database and image
    writes happen on the Tk main thread via ``root.after`` so Tk widgets are
    never touched from worker threads.
    """

    def __init__(
        self,
        data_dir: Path,
        root: Any,
        *,
        backend: ClipboardBackend | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.root = root
        self.settings: ClipboardSettings = load_settings(self.data_dir)
        self.store = ClipboardStore(self.data_dir)
        self.backend: ClipboardBackend = backend or create_backend()
        self.last_error = ""
        self._queue: queue.Queue[ClipboardContent] = queue.Queue(maxsize=100)
        self._listeners: list[Listener] = []
        self._record_lock = threading.Lock()
        self._running = False
        self._after_id: str | None = None
        self._suppress_digest: str | None = None
        self._suppress_until = 0.0
        self._suppress_any_until = 0.0
        # Some desktop clipboard managers (notably GNOME on X11) take over a
        # file selection when the source app exits and re-publish it as plain
        # paths. Ignore that narrow text-only echo for a short while.
        self._recent_file_texts: set[str] = set()
        self._recent_file_until = 0.0

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            self.backend.start(self._on_change)
        except Exception as exc:
            self.last_error = str(exc) or exc.__class__.__name__
            log.exception("启动剪贴板监听失败")
        self._schedule_drain()

    def stop(self) -> None:
        if not self._running and self._after_id is None:
            return
        self._running = False
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except (tk.TclError, AttributeError):
                pass
            self._after_id = None
        try:
            self.backend.stop()
        except Exception:
            log.exception("停止剪贴板监听失败")
        try:
            self.store.close()
        except Exception:
            log.exception("关闭剪贴板数据库失败")
        self._running = False

    # -------------------------------------------------------------- capture
    def _on_change(self, content: ClipboardContent) -> None:
        if not self._running or not self.settings.recording:
            return
        kind = kind_value(content.kind)
        if kind == "image" and not self.settings.capture_images:
            return
        if kind == "files" and not self.settings.capture_files:
            return
        now = time.monotonic()
        if kind == "text" and now < self._recent_file_until:
            normalized = (content.text or "").replace("\r\n", "\n").strip()
            if normalized in self._recent_file_texts:
                return
        digest = content_digest(content)
        with self._record_lock:
            if now < self._suppress_any_until:
                return
            if (
                digest == self._suppress_digest
                and now < self._suppress_until
            ):
                self._suppress_digest = None
                return
        try:
            self._queue.put_nowait(content)
        except queue.Full:
            log.warning("剪贴板事件队列已满，丢弃一条记录")

    def _schedule_drain(self) -> None:
        if not self._running:
            return
        try:
            self._after_id = self.root.after(120, self._drain)
        except (tk.TclError, AttributeError):
            self._after_id = None
            self._running = False

    def _drain(self) -> None:
        self._after_id = None
        if not self._running:
            return
        processed = 0
        while processed < 20:
            try:
                content = self._queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            kind = kind_value(content.kind)
            if kind == "image" and not self.settings.capture_images:
                continue
            if kind == "files" and not self.settings.capture_files:
                continue
            try:
                entry = self.store.add(
                    content, max_image_bytes=self.settings.max_image_bytes
                )
                self.store.prune(
                    max_entries=self.settings.max_entries,
                    max_image_bytes=self.settings.max_image_bytes,
                )
                if kind == "files" and content.paths:
                    recent = {
                        path
                        for path in content.paths
                    }
                    recent.add("\n".join(content.paths))
                    recent.add(paths_to_uri_list(content.paths).strip())
                    recent.add(
                        "\n".join(
                            line.strip()
                            for line in paths_to_uri_list(content.paths).splitlines()
                            if line.strip()
                        )
                    )
                    self._recent_file_texts = {
                        value.replace("\r\n", "\n").strip()
                        for value in recent
                        if value and value.strip()
                    }
                    self._recent_file_until = time.monotonic() + 10.0
                self.last_error = ""
                self._notify("added", entry.id)
            except ClipboardError as exc:
                self.last_error = str(exc)
                self._notify("error", None)
            except Exception:
                self.last_error = "记录剪贴板内容失败，详见日志"
                log.exception("记录剪贴板内容失败")
                self._notify("error", None)
        self._schedule_drain()

    # -------------------------------------------------------------- queries
    def entries(
        self,
        kind: ClipboardKind | None = None,
        query: str = "",
        *,
        newest_first: bool = True,
    ) -> list[ClipboardEntry]:
        return self.store.list_entries(kind, query, newest_first=newest_first)

    def counts(self) -> dict[str, int]:
        return self.store.counts()

    def get(self, entry_id: int) -> ClipboardEntry | None:
        return self.store.get(entry_id)

    def image_file(self, entry: ClipboardEntry) -> Path | None:
        return self.store.image_file(entry)

    def thumb_file(self, entry: ClipboardEntry) -> Path | None:
        return self.store.thumb_file(entry)

    # -------------------------------------------------------------- mutate
    def delete_entry(self, entry_id: int) -> bool:
        deleted = self.store.delete(entry_id)
        if deleted:
            self._notify("deleted", entry_id)
        return deleted

    def clear_history(self) -> int:
        removed = self.store.clear()
        self._notify("cleared", None)
        return removed

    def update_entry_text(
        self, entry_id: int, text: str
    ) -> ClipboardEntry | None:
        updated = self.store.update_text(entry_id, text)
        if updated is not None:
            self._notify("edited", updated.id)
        return updated

    def update_settings(self, **changes) -> ClipboardSettings:
        new_settings = replace(self.settings, **changes).normalized()
        save_settings(self.data_dir, new_settings)
        self.settings = new_settings
        self.store.prune(
            max_entries=new_settings.max_entries,
            max_image_bytes=new_settings.max_image_bytes,
        )
        self._notify("settings", None)
        return new_settings

    def set_recording(self, recording: bool) -> ClipboardSettings:
        return self.update_settings(recording=bool(recording))

    def copy_entry(
        self,
        entry: ClipboardEntry,
        *,
        paths: list[str] | None = None,
    ) -> ClipboardEntry | None:
        """Write an entry back to the system clipboard.

        For file entries with some missing paths, raises ``PartialFilesError``
        so the UI can ask whether to copy the remaining files.
        """
        digest = entry.digest
        kind = entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind)
        try:
            if kind == "files":
                if entry.source_platform != current_platform():
                    raise ClipboardError(
                        "该文件列表来自其他操作系统，无法在当前系统复制。"
                    )
                available, missing = accessible_paths(
                    entry.paths, entry.source_platform
                )
                if paths is not None:
                    available = list(paths)
                    missing = []
                elif missing:
                    raise PartialFilesError(available, missing)
                if not available:
                    raise ClipboardError("所有文件都已移动或删除，无法复制。")
                digest = content_digest(
                    ClipboardContent(
                        kind=ClipboardKind.FILES,
                        paths=tuple(available),
                        platform=current_platform(),
                    )
                )
                self._begin_suppression(digest)
                try:
                    self.backend.write_files(available)
                except Exception:
                    self._clear_suppression()
                    raise
            elif kind == "image":
                data = self.store.image_bytes(entry)
                if not data:
                    raise ClipboardError("图片文件不存在，无法复制。")
                self._begin_suppression(digest)
                try:
                    self.backend.write_image(data)
                except Exception:
                    self._clear_suppression()
                    raise
            else:
                text = entry.text_content or ""
                self._begin_suppression(digest)
                try:
                    self.backend.write_text(text)
                except Exception:
                    self._clear_suppression()
                    raise
        except Exception as exc:
            if isinstance(exc, ClipboardError):
                raise
            raise ClipboardError(str(exc) or exc.__class__.__name__) from exc

        # Re-copying from history increments the counter but must not bump
        # last_copied_at: 二次复制 is a paste helper, so the list keeps its
        # current order instead of moving the entry to the top.
        updated = self.store.mark_copied(entry.id)
        self._notify("copied", entry.id)
        return updated

    def copy_image_png(
        self, png: bytes, *, record: bool = True
    ) -> ClipboardEntry | None:
        """Write PNG bytes to the system clipboard.

        When ``record`` is true the image is also added to clipboard history.
        The caller must be on the Tk main thread because the store writes
        files and SQLite rows synchronously.
        """
        if not isinstance(png, (bytes, bytearray)) or not png:
            raise ClipboardError("截图图片数据为空")
        payload = bytes(png)
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                if image.format != "PNG":
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    payload = buffer.getvalue()
        except Exception as exc:
            raise ClipboardError("截图图片数据无效") from exc

        content = ClipboardContent(
            kind=ClipboardKind.IMAGE,
            image_png=payload,
            source="QuickTools 截图",
            platform=current_platform(),
        )
        digest = content_digest(content)
        self._begin_suppression(digest)
        try:
            self.backend.write_image(payload)
        except Exception:
            self._clear_suppression()
            raise

        entry: ClipboardEntry | None = None
        if record:
            try:
                entry = self.store.add(
                    content, max_image_bytes=self.settings.max_image_bytes
                )
                self.store.prune(
                    max_entries=self.settings.max_entries,
                    max_image_bytes=self.settings.max_image_bytes,
                )
                self.last_error = ""
                self._notify("added", entry.id)
            except ClipboardError as exc:
                self.last_error = str(exc)
                log.warning("记录截图到剪贴板历史失败：%s", exc)
                self._notify("error", None)
            except Exception:
                self.last_error = "记录截图到剪贴板历史失败，详见日志"
                log.exception("记录截图到剪贴板历史失败")
                self._notify("error", None)
        return entry

    def copy_plain_text(self, text: str) -> None:
        """Copy a path/string without adding it as a history entry."""
        digest = content_digest(
            ClipboardContent(
                kind=ClipboardKind.TEXT,
                text=text,
                platform=current_platform(),
            )
        )
        self._begin_suppression(digest)
        try:
            self.backend.write_text(text)
        except Exception:
            self._clear_suppression()
            raise

    def _begin_suppression(self, digest: str) -> None:
        now = time.monotonic()
        with self._record_lock:
            self._suppress_digest = digest
            self._suppress_until = now + 2.0
            self._suppress_any_until = now + 0.6

    def _clear_suppression(self) -> None:
        with self._record_lock:
            self._suppress_digest = None
            self._suppress_until = 0.0
            self._suppress_any_until = 0.0

    # ------------------------------------------------------------- status/UI
    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    def _notify(self, event: str, entry_id: int | None) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, entry_id)
            except Exception:
                log.exception("剪贴板 UI 回调失败")

    @property
    def backend_status(self) -> BackendStatus:
        return self.backend.status

    @property
    def recording(self) -> bool:
        return self.settings.recording

    def status_text(self) -> tuple[str, str, str]:
        """Return (headline, detail, level) where level is ok/warn/error."""
        status = self.backend.status
        if not status.available:
            detail = status.detail or status.install_hint or "剪贴板监听不可用"
            return ("监听不可用", detail, "error")
        if not self.settings.recording:
            return ("已暂停记录", "监听仍在运行，但不会新增历史", "warn")
        if self.last_error:
            return ("已在后台运行", self.last_error, "warn")
        return ("已在后台运行", f"{status.mode} · 自动记录剪贴板内容", "ok")
