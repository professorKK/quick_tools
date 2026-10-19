"""Wayland clipboard backend built on wl-clipboard.

Wayland does not expose a portable in-process clipboard API. Event-driven
monitoring therefore relies on ``wl-paste --watch``; both ``wl-paste`` and
``wl-copy`` must be installed by the user. Availability and compositor
restrictions are reported through ``BackendStatus`` instead of being hidden.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import threading
from typing import Sequence

from PIL import Image

from ..models import BackendStatus, ClipboardContent, ClipboardError, ClipboardKind
from ..platform_utils import parse_uri_list, paths_to_uri_list
from .base import BaseBackend

log = logging.getLogger(__name__)

INSTALL_HINT = (
    "Wayland 下需要安装 wl-clipboard：\n"
    "  Debian/Ubuntu: sudo apt install wl-clipboard\n"
    "  Fedora: sudo dnf install wl-clipboard\n"
    "  Arch: sudo pacman -S wl-clipboard\n"
    "  openSUSE: sudo zypper install wl-clipboard\n"
    "不同合成器对后台读取剪贴板的限制不同，无法保证所有 Wayland 环境可用。"
)

IMAGE_TYPES = ("image/png", "image/bmp", "image/tiff", "image/jpeg")
TEXT_TYPES = (
    "text/plain;charset=utf-8",
    "text/plain",
    "UTF8_STRING",
    "STRING",
)


class WaylandBackend(BaseBackend):
    name = "wayland"

    def __init__(self) -> None:
        super().__init__()
        self._wl_paste = shutil.which("wl-paste")
        self._wl_copy = shutil.which("wl-copy")
        self._thread: threading.Thread | None = None
        self._watcher: subprocess.Popen[bytes] | None = None
        self._stop_event = threading.Event()
        if not self._wl_paste or not self._wl_copy:
            self.status = BackendStatus(
                False,
                "Wayland",
                "未找到 wl-paste / wl-copy，无法监听 Wayland 剪贴板。",
                INSTALL_HINT,
            )
        else:
            self.status = BackendStatus(
                True,
                "Wayland (wl-clipboard)",
                "依赖合成器支持 data-control；部分环境只能读取当前应用。",
            )

    # ------------------------------------------------------------ lifecycle
    def start(self, on_change) -> None:
        self._on_change = on_change
        if not self.status.available:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop, name="clipboard-wayland", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        watcher = self._watcher
        if watcher is not None:
            try:
                watcher.terminate()
            except OSError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._watcher = None

    def _watch_loop(self) -> None:
        assert self._wl_paste is not None
        while not self._stop_event.is_set():
            try:
                process = subprocess.Popen(
                    [self._wl_paste, "--watch", "sh", "-c", "printf x"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                self.status = BackendStatus(
                    False, "Wayland", f"无法启动 wl-paste：{exc}", INSTALL_HINT
                )
                return
            self._watcher = process
            try:
                assert process.stdout is not None
                while not self._stop_event.is_set():
                    marker = process.stdout.read(1)
                    if not marker:
                        break
                    # Clipboard writes often produce several XFixes/wayland
                    # notifications in a row; let them settle first.
                    if self._stop_event.wait(0.15):
                        break
                    try:
                        content = self.snapshot()
                    except Exception:
                        log.exception("读取 Wayland 剪贴板失败")
                        continue
                    if content is not None and self._on_change is not None:
                        self._on_change(content)
            finally:
                try:
                    process.terminate()
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
                self._watcher = None
            if not self._stop_event.is_set():
                self._stop_event.wait(0.5)

    # ---------------------------------------------------------------- read
    def _types(self) -> list[str]:
        if not self._wl_paste:
            return []
        result = subprocess.run(
            [self._wl_paste, "--list-types"],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [
            line.strip()
            for line in result.stdout.decode("utf-8", "replace").splitlines()
            if line.strip()
        ]

    def _read_type(self, mime: str) -> bytes | None:
        if not self._wl_paste:
            return None
        try:
            result = subprocess.run(
                [self._wl_paste, "--no-newline", "--type", mime],
                capture_output=True,
                timeout=3.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout if result.returncode == 0 else None

    @staticmethod
    def _decode(data: bytes, *, latin1_fallback: bool = True) -> str | None:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1") if latin1_fallback else None

    def _read_files_only(self) -> list[str] | None:
        types = self._types()
        if "x-special/gnome-copied-files" in types:
            data = self._read_type("x-special/gnome-copied-files")
            if data:
                text = self._decode(data) or ""
                lines = text.splitlines()
                payload = "\n".join(lines[1:] if lines else [])
                paths = parse_uri_list(payload)
                if paths:
                    return paths
        if "text/uri-list" in types:
            data = self._read_type("text/uri-list")
            if data:
                paths = parse_uri_list(self._decode(data) or "")
                if paths:
                    return paths
        return None

    @staticmethod
    def _to_png(data: bytes, mime: str) -> bytes | None:
        if mime == "image/png":
            return data
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                output = io.BytesIO()
                image.save(output, "PNG")
                return output.getvalue()
        except Exception:
            log.debug("无法转换 Wayland 图片 MIME %s", mime, exc_info=True)
            return None

    def _read_image_only(self) -> bytes | None:
        types = self._types()
        for mime in IMAGE_TYPES:
            if mime in types:
                data = self._read_type(mime)
                if data:
                    converted = self._to_png(data, mime)
                    if converted:
                        return converted
        return None

    def _read_text_only(self) -> str | None:
        types = self._types()
        for mime in TEXT_TYPES:
            if mime in types:
                data = self._read_type(mime)
                if data is None:
                    continue
                text = self._decode(data, latin1_fallback=True)
                if text and text.strip():
                    return text
        return None

    def read_files(self) -> list[str] | None:
        return self._read_files_only()

    def read_image(self) -> bytes | None:
        return self._read_image_only()

    def read_text(self) -> str | None:
        return self._read_text_only()

    def snapshot(self) -> ClipboardContent | None:
        try:
            files = self._read_files_only()
        except (OSError, subprocess.TimeoutExpired):
            files = None
        if files:
            return ClipboardContent(kind=ClipboardKind.FILES, paths=tuple(files))
        try:
            image = self._read_image_only()
        except (OSError, subprocess.TimeoutExpired):
            image = None
        if image:
            return ClipboardContent(kind=ClipboardKind.IMAGE, image_png=image)
        try:
            text = self._read_text_only()
        except (OSError, subprocess.TimeoutExpired):
            text = None
        if text and text.strip():
            return ClipboardContent(kind=ClipboardKind.TEXT, text=text)
        return None

    # --------------------------------------------------------------- write
    def _copy(self, mime: str, data: bytes) -> None:
        if not self._wl_copy:
            raise ClipboardError("未找到 wl-copy，无法写入 Wayland 剪贴板。")
        try:
            result = subprocess.run(
                [self._wl_copy, "--type", mime],
                input=data,
                capture_output=True,
                timeout=3.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClipboardError(f"写入 Wayland 剪贴板失败：{exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise ClipboardError(
                "写入 Wayland 剪贴板失败"
                + (f"：{detail}" if detail else "")
            )

    def write_text(self, text: str) -> None:
        self._copy("text/plain;charset=utf-8", text.encode("utf-8"))

    def write_image(self, png: bytes) -> None:
        self._copy("image/png", png)

    def write_files(self, paths: Sequence[str]) -> None:
        self._copy("text/uri-list", paths_to_uri_list(paths).encode("utf-8"))
