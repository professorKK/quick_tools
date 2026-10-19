"""X11 clipboard backend using XFixes events and ICCCM selection transfers.

Reads are event-driven: XFixes reports ownership changes, then the contents are
fetched with ConvertSelection. Large transfers use INCR. Writes make our
message window the CLIPBOARD owner and serve SelectionRequest events.
"""

from __future__ import annotations

import io
import logging
import queue
import select
import threading
import time
from dataclasses import dataclass
from typing import Sequence

from PIL import Image
from Xlib import X, Xatom, display
from Xlib import error as xerror
from Xlib.ext import xfixes
from Xlib.protocol import event as xevent

from ..models import (
    BackendStatus,
    ClipboardContent,
    ClipboardError,
    ClipboardKind,
)
from ..platform_utils import parse_uri_list, paths_to_uri_list
from .base import BaseBackend

log = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
INCR_THRESHOLD = 64 * 1024
READ_TIMEOUT = 2.0
INCR_TIMEOUT = 5.0
IMAGE_TARGETS = ("image/png", "image/bmp", "image/tiff", "image/jpeg")
TEXT_TARGETS = (
    "UTF8_STRING",
    "text/plain;charset=utf-8",
    "text/plain",
    "STRING",
    "TEXT",
)


@dataclass
class _Payload:
    kind: ClipboardKind
    text: str | None = None
    png: bytes | None = None
    paths: tuple[str, ...] = ()


@dataclass
class _WriteJob:
    payload: _Payload
    done: threading.Event
    error: Exception | None = None


@dataclass
class _ReadJob:
    kind: ClipboardKind
    done: threading.Event
    result: object = None
    error: Exception | None = None


class X11Backend(BaseBackend):
    name = "x11"

    def __init__(self) -> None:
        super().__init__()
        self.status = BackendStatus(False, "X11", "X11 监听尚未启动")
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._display = None
        self._root = None
        self._window = None
        self._clipboard_atom = 0
        self._prop_atom = 0
        self._atom: dict[str, int] = {}
        self._event_time = X.CurrentTime
        self._pending_read_at = 0.0
        self._last_owner = None
        self._owned_payload: _Payload | None = None
        self._owned_timestamp = 0
        self._incr_out: dict[tuple[int, int], tuple[list[bytes], int]] = {}
        self._incr_read_active: int | None = None
        self._source_cache: dict[int, str | None] = {}

    # ------------------------------------------------------------ lifecycle
    def start(self, on_change) -> None:
        self._on_change = on_change
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="clipboard-x11", daemon=True
        )
        self._thread.start()
        self._ready.wait(2.0)

    def stop(self) -> None:
        self._running.clear()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
            if thread.is_alive():
                log.warning("X11 剪贴板监听线程未能及时退出")
        self._thread = None

    def _run(self) -> None:
        try:
            self._setup()
        except Exception as exc:
            log.exception("初始化 X11 剪贴板监听失败")
            self.status = BackendStatus(
                False, "X11", f"X11 剪贴板监听启动失败：{exc}"
            )
            self._ready.set()
            return
        self._running.set()
        self._ready.set()
        try:
            self._loop()
        except Exception as exc:
            log.exception("X11 剪贴板事件循环异常")
            self.status = BackendStatus(
                False, "X11", f"X11 剪贴板监听已停止：{exc}"
            )
        finally:
            self._teardown()

    def _setup(self) -> None:
        self._display = display.Display()
        info = self._display.query_extension("XFIXES")
        if info is None:
            raise ClipboardError("X 服务器不支持 XFixes 扩展")
        self._display.xfixes_query_version()
        screen = self._display.screen()
        self._root = screen.root
        self._window = self._root.create_window(
            0,
            0,
            1,
            1,
            0,
            screen.root_depth,
            X.InputOutput,
            X.CopyFromParent,
            event_mask=X.PropertyChangeMask | X.StructureNotifyMask,
        )
        names = (
            "CLIPBOARD",
            "TARGETS",
            "TIMESTAMP",
            "UTF8_STRING",
            "STRING",
            "TEXT",
            "MULTIPLE",
            "INCR",
            "ATOM",
            "INTEGER",
            "text/plain",
            "text/plain;charset=utf-8",
            "text/uri-list",
            "image/png",
            "image/bmp",
            "image/tiff",
            "image/jpeg",
            "x-special/gnome-copied-files",
            "_NET_WM_PID",
        )
        self._atom = {name: self._display.intern_atom(name) for name in names}
        self._clipboard_atom = self._atom["CLIPBOARD"]
        self._prop_atom = self._display.intern_atom("QUICKTOOLS_CLIPBOARD")
        self._display.xfixes_select_selection_input(
            self._window,
            self._clipboard_atom,
            xfixes.XFixesSetSelectionOwnerNotifyMask
            | xfixes.XFixesSelectionWindowDestroyNotifyMask
            | xfixes.XFixesSelectionClientCloseNotifyMask,
        )
        self._display.flush()
        self.status = BackendStatus(
            True, "X11 (XFixes)", "通过 XFixes 事件监听剪贴板。"
        )

    def _teardown(self) -> None:
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            pass
        try:
            if self._display is not None:
                self._display.close()
        except Exception:
            pass
        self._window = None
        self._display = None

    # -------------------------------------------------------------- event loop
    def _loop(self) -> None:
        while self._running.is_set():
            self._process_jobs()
            now = time.monotonic()
            if self._pending_read_at and now >= self._pending_read_at:
                self._pending_read_at = 0.0
                self._capture_current()
            timeout = 0.2
            if self._pending_read_at:
                timeout = min(timeout, max(0.0, self._pending_read_at - now))
            event = self._pump_event(timeout)
            if event is not None:
                self._handle_event(event)

    def _pump_event(self, timeout: float):
        if self._display is None:
            return None
        try:
            if self._display.pending_events():
                return self._display.next_event()
            ready, _write, _error = select.select(
                [self._display.fileno()], [], [], max(0.0, timeout)
            )
        except (OSError, ValueError):
            return None
        if not ready:
            return None
        try:
            if self._display.pending_events():
                return self._display.next_event()
        except (OSError, ValueError, xerror.XError):
            return None
        return None


    def _handle_event(self, event) -> None:
        # python-xlib returns dynamically generated XFixes event classes; an
        # isinstance check against the module attribute can be False even
        # though the class name matches. Match the protocol fields instead.
        if hasattr(event, "selection") and hasattr(event, "sub_code"):
            if event.selection != self._clipboard_atom:
                return
            if event.sub_code == xfixes.XFixesSetSelectionOwnerNotify:
                owner = event.owner
                owner_id = getattr(owner, "id", 0) if owner is not None else 0
                self._last_owner = owner if owner_id else None
                self._event_time = event.selection_timestamp or X.CurrentTime
                if owner_id and owner_id != getattr(self._window, "id", 0):
                    self._pending_read_at = time.monotonic() + 0.15
                else:
                    # Our own copy-back write; the service updates history itself.
                    self._pending_read_at = 0.0
            elif event.sub_code in (
                xfixes.XFixesSelectionWindowDestroyNotify,
                xfixes.XFixesSelectionClientCloseNotify,
            ):
                self._last_owner = None
            return
        if isinstance(event, xevent.SelectionRequest):
            self._serve_request(event)
        elif isinstance(event, xevent.SelectionClear):
            if event.atom == self._clipboard_atom:
                self._owned_payload = None
                self._incr_out.clear()
        elif isinstance(event, xevent.PropertyNotify):
            self._handle_property_notify(event)

    def _handle_property_notify(self, event) -> None:
        if self._incr_read_active is not None:
            return
        key = (getattr(event.window, "id", 0), event.atom)
        item = self._incr_out.get(key)
        if item is None or event.state != X.PropertyDelete:
            return
        chunks, target_type = item
        requestor = event.window
        try:
            if chunks:
                chunk = chunks.pop(0)
                requestor.change_property(event.atom, target_type, 8, chunk)
            else:
                requestor.change_property(event.atom, target_type, 8, b"")
                del self._incr_out[key]
            self._display.flush()
        except (xerror.XError, OSError):
            self._incr_out.pop(key, None)

    def _capture_current(self) -> None:
        try:
            content = self._read_snapshot()
        except (xerror.XError, OSError, ValueError) as exc:
            log.debug("读取 X11 剪贴板失败：%s", exc)
            return
        except Exception:
            log.exception("读取 X11 剪贴板时发生未预期错误")
            return
        if content is not None and self._on_change is not None:
            self._on_change(content)

    # ---------------------------------------------------------------- reading
    def _selection_owner(self):
        try:
            owner = self._display.get_selection_owner(self._clipboard_atom)
        except (xerror.XError, OSError):
            return None
        if owner is None or getattr(owner, "id", 0) == 0:
            return None
        return owner

    def _read_snapshot(self) -> ClipboardContent | None:
        owner = self._selection_owner()
        if owner is None or owner.id == self._window.id:
            return None
        source = self._source_name(owner)
        targets = self._fetch_targets()
        if not targets:
            return None

        gnome_files = self._atom["x-special/gnome-copied-files"]
        if gnome_files in targets:
            result = self._read_target(gnome_files)
            if result is not None:
                text = self._text_from_result(result)
                if text:
                    lines = text.splitlines()
                    paths = parse_uri_list("\n".join(lines[1:] if lines else []))
                    if paths:
                        return ClipboardContent(
                            kind=ClipboardKind.FILES,
                            paths=tuple(paths),
                            source=source,
                        )

        uri_atom = self._atom["text/uri-list"]
        if uri_atom in targets:
            result = self._read_target(uri_atom)
            if result is not None:
                text = self._text_from_result(result)
                paths = parse_uri_list(text or "")
                if paths:
                    return ClipboardContent(
                        kind=ClipboardKind.FILES,
                        paths=tuple(paths),
                        source=source,
                    )

        for name in IMAGE_TARGETS:
            atom = self._atom.get(name)
            if atom is not None and atom in targets:
                result = self._read_target(atom)
                if result is None:
                    continue
                data = self._bytes_from_result(result)
                png = self._to_png(data, name)
                if png:
                    return ClipboardContent(
                        kind=ClipboardKind.IMAGE,
                        image_png=png,
                        source=source,
                    )

        for name in TEXT_TARGETS:
            atom = self._atom.get(name)
            if atom is not None and atom in targets:
                result = self._read_target(atom)
                if result is None:
                    continue
                text = self._text_from_result(result, name)
                if text and text.strip():
                    return ClipboardContent(
                        kind=ClipboardKind.TEXT, text=text, source=source
                    )
        return None

    def _fetch_targets(self) -> set[int]:
        result = self._read_target(self._atom["TARGETS"])
        if result is None:
            return set()
        _xtype, fmt, value = result
        if fmt != 32 or not isinstance(value, list):
            return set()
        return {int(atom) for atom in value}

    def _read_target(self, target: int):
        if self._display is None:
            return None
        try:
            self._window.delete_property(self._prop_atom)
            self._window.convert_selection(
                self._clipboard_atom,
                target,
                self._prop_atom,
                X.CurrentTime,
            )
            self._display.flush()
        except (xerror.XError, OSError):
            return None
        prop = self._wait_selection_notify(target, READ_TIMEOUT)
        if not prop:
            return None
        try:
            prop_obj = self._window.get_full_property(
                prop, X.AnyPropertyType
            )
        except (xerror.XError, OSError):
            return None
        if prop_obj is None:
            return None
        if prop_obj.property_type == self._atom["INCR"]:
            data = self._read_incr(prop)
            return (None, 8, data)
        xtype = prop_obj.property_type
        fmt = prop_obj.format
        value = prop_obj.value
        try:
            self._window.delete_property(prop)
            self._display.flush()
        except (xerror.XError, OSError):
            pass
        if fmt == 8:
            return (xtype, 8, bytes(value))
        if fmt == 32:
            return (xtype, 32, list(value))
        return None

    def _wait_selection_notify(self, target: int, timeout: float) -> int | None:
        deadline = time.monotonic() + timeout
        while self._running.is_set() and time.monotonic() < deadline:
            remaining = max(0.0, min(0.1, deadline - time.monotonic()))
            event = self._pump_event(remaining)
            if event is None:
                continue
            if isinstance(event, xevent.SelectionNotify):
                requestor = getattr(event, "requestor", None)
                if (
                    getattr(requestor, "id", None) == self._window.id
                    and event.selection == self._clipboard_atom
                    and event.target == target
                ):
                    return event.property
                continue
            if isinstance(event, xevent.PropertyNotify):
                # Property notifications while waiting for the transfer are
                # unrelated to this read.
                self._handle_property_notify(event)
                continue
            if isinstance(event, xevent.SelectionRequest):
                self._serve_request(event)
                continue
            self._handle_event(event)
        return None

    def _read_incr(self, prop: int) -> bytes:
        self._incr_read_active = prop
        chunks: list[bytes] = []
        try:
            try:
                self._window.delete_property(prop)
                self._display.flush()
            except (xerror.XError, OSError):
                return b""
            deadline = time.monotonic() + INCR_TIMEOUT
            while self._running.is_set() and time.monotonic() < deadline:
                remaining = max(0.0, min(0.1, deadline - time.monotonic()))
                event = self._pump_event(remaining)
                if event is None:
                    continue
                if isinstance(event, xevent.PropertyNotify) and (
                    getattr(event.window, "id", 0) == self._window.id
                    and event.atom == prop
                ):
                    if event.state != X.PropertyNewValue:
                        continue
                    try:
                        prop_obj = self._window.get_full_property(
                            prop, X.AnyPropertyType
                        )
                    except (xerror.XError, OSError):
                        break
                    if prop_obj is None:
                        break
                    try:
                        self._window.delete_property(prop)
                        self._display.flush()
                    except (xerror.XError, OSError):
                        pass
                    if prop_obj.format != 8:
                        break
                    data = bytes(prop_obj.value)
                    if not data:
                        break
                    chunks.append(data)
                elif not isinstance(event, xevent.PropertyNotify):
                    self._handle_event(event)
            else:
                log.warning("X11 INCR 读取超时")
        finally:
            self._incr_read_active = None
        return b"".join(chunks)

    @staticmethod
    def _bytes_from_result(result) -> bytes:
        _xtype, fmt, value = result
        if fmt != 8:
            return b""
        return bytes(value)

    @staticmethod
    def _text_from_result(result, target_name: str = "UTF8_STRING") -> str | None:
        data = X11Backend._bytes_from_result(result)
        if not data:
            return None
        if target_name in ("STRING", "TEXT"):
            return data.decode("latin-1", "replace")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1", "replace")

    @staticmethod
    def _to_png(data: bytes, mime: str) -> bytes | None:
        if not data:
            return None
        if mime == "image/png":
            return data
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                output = io.BytesIO()
                image.save(output, "PNG")
                return output.getvalue()
        except Exception:
            log.debug("无法转换 X11 图片 MIME %s", mime, exc_info=True)
            return None

    def _source_name(self, owner) -> str | None:
        owner_id = getattr(owner, "id", 0)
        if owner_id in self._source_cache:
            return self._source_cache[owner_id]
        name: str | None = None
        try:
            pid_prop = owner.get_full_property(
                self._atom["_NET_WM_PID"], X.AnyPropertyType
            )
            if pid_prop is not None and pid_prop.value:
                pid = int(pid_prop.value[0])
                try:
                    with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as handle:
                        name = handle.read().strip() or None
                except OSError:
                    name = None
            if not name:
                wm_class = owner.get_wm_class()
                if wm_class:
                    name = (wm_class[1] or wm_class[0] or "").strip() or None
        except (xerror.XError, OSError, ValueError):
            name = None
        if len(self._source_cache) > 128:
            self._source_cache.clear()
        self._source_cache[owner_id] = name
        return name

    # ---------------------------------------------------------------- writing
    def write_text(self, text: str) -> None:
        self._submit_write(_Payload(kind=ClipboardKind.TEXT, text=text))

    def write_image(self, png: bytes) -> None:
        self._submit_write(_Payload(kind=ClipboardKind.IMAGE, png=png))

    def write_files(self, paths: Sequence[str]) -> None:
        self._submit_write(
            _Payload(kind=ClipboardKind.FILES, paths=tuple(paths))
        )

    def _submit_write(self, payload: _Payload) -> None:
        if not self._running.is_set():
            raise ClipboardError("X11 剪贴板监听未运行，无法写入。")
        job = _WriteJob(payload=payload, done=threading.Event())
        self._jobs.put(job)
        if not job.done.wait(3.0):
            raise ClipboardError("写入 X11 剪贴板超时")
        if job.error is not None:
            if isinstance(job.error, ClipboardError):
                raise job.error
            raise ClipboardError(f"写入 X11 剪贴板失败：{job.error}") from job.error

    def _do_write(self, payload: _Payload) -> None:
        self._owned_payload = payload
        self._owned_timestamp = int(time.time() * 1000) & 0xFFFFFFFF
        self._incr_out.clear()
        self._window.set_selection_owner(self._clipboard_atom, X.CurrentTime)
        self._display.flush()
        owner = self._selection_owner()
        if owner is None or owner.id != self._window.id:
            self._owned_payload = None
            raise ClipboardError("无法取得 X11 剪贴板所有权")

    # ---------------------------------------------------------- read interface
    def _submit_read(self, kind: ClipboardKind):
        if not self._running.is_set():
            return None
        job = _ReadJob(kind=kind, done=threading.Event())
        self._jobs.put(job)
        if not job.done.wait(4.0):
            return None
        if job.error is not None:
            log.debug("X11 读取任务失败：%s", job.error)
            return None
        return job.result

    def read_text(self) -> str | None:
        return self._submit_read(ClipboardKind.TEXT)

    def read_image(self) -> bytes | None:
        return self._submit_read(ClipboardKind.IMAGE)

    def read_files(self) -> list[str] | None:
        return self._submit_read(ClipboardKind.FILES)

    def _process_jobs(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                if isinstance(job, _WriteJob):
                    self._do_write(job.payload)
                elif isinstance(job, _ReadJob):
                    job.result = self._do_read(job.kind)
            except Exception as exc:
                job.error = exc
            finally:
                job.done.set()

    def _do_read(self, kind: ClipboardKind):
        owner = self._selection_owner()
        if owner is None or owner.id == self._window.id:
            return None
        targets = self._fetch_targets()
        if not targets:
            return None
        if kind is ClipboardKind.FILES:
            for name in ("x-special/gnome-copied-files", "text/uri-list"):
                atom = self._atom[name]
                if atom not in targets:
                    continue
                result = self._read_target(atom)
                text = self._text_from_result(result) if result else None
                if not text:
                    continue
                if name == "x-special/gnome-copied-files":
                    lines = text.splitlines()
                    text = "\n".join(lines[1:] if lines else [])
                paths = parse_uri_list(text)
                if paths:
                    return paths
            return None
        if kind is ClipboardKind.IMAGE:
            for name in IMAGE_TARGETS:
                atom = self._atom.get(name)
                if atom is None or atom not in targets:
                    continue
                result = self._read_target(atom)
                if result is None:
                    continue
                png = self._to_png(self._bytes_from_result(result), name)
                if png:
                    return png
            return None
        if kind is ClipboardKind.TEXT:
            for name in TEXT_TARGETS:
                atom = self._atom.get(name)
                if atom is None or atom not in targets:
                    continue
                result = self._read_target(atom)
                if result is None:
                    continue
                text = self._text_from_result(result, name)
                if text and text.strip():
                    return text
        return None

    # --------------------------------------------------------- selection serve
    def _serve_request(self, event) -> None:
        if event.selection != self._clipboard_atom:
            return
        requestor = event.requestor
        prop = event.property or event.target
        payload = self._owned_payload
        if payload is None or not prop or event.target == self._atom["MULTIPLE"]:
            self._send_selection_notify(event, 0)
            return
        try:
            target_type, fmt, data = self._payload_for_target(event.target, payload)
        except (xerror.XError, OSError):
            self._send_selection_notify(event, 0)
            return
        if target_type is None:
            self._send_selection_notify(event, 0)
            return
        try:
            if fmt == 8 and len(data) > INCR_THRESHOLD:
                requestor.change_attributes(event_mask=X.PropertyChangeMask)
                requestor.change_property(
                    prop, self._atom["INCR"], 32, []
                )
                chunks = [
                    data[index : index + CHUNK_SIZE]
                    for index in range(0, len(data), CHUNK_SIZE)
                ]
                self._incr_out[(requestor.id, prop)] = (chunks, target_type)
            else:
                requestor.change_property(prop, target_type, fmt, data)
            self._send_selection_notify(event, prop)
            self._display.flush()
        except (xerror.XError, OSError):
            self._incr_out.pop((requestor.id, prop), None)
            self._send_selection_notify(event, 0)

    def _payload_for_target(self, target: int, payload: _Payload):
        if target == self._atom["TARGETS"]:
            atoms = [self._atom["TARGETS"], self._atom["TIMESTAMP"]]
            if payload.kind is ClipboardKind.TEXT:
                atoms.extend(self._atom[name] for name in TEXT_TARGETS)
            elif payload.kind is ClipboardKind.IMAGE:
                atoms.append(self._atom["image/png"])
            else:
                atoms.extend(
                    (
                        self._atom["text/uri-list"],
                        self._atom["x-special/gnome-copied-files"],
                        self._atom["UTF8_STRING"],
                        self._atom["STRING"],
                        self._atom["text/plain;charset=utf-8"],
                        self._atom["text/plain"],
                    )
                )
            return (Xatom.ATOM, 32, atoms)
        if target == self._atom["TIMESTAMP"]:
            return (Xatom.INTEGER, 32, [int(self._owned_timestamp) & 0xFFFFFFFF])
        if payload.kind is ClipboardKind.TEXT:
            text = payload.text or ""
            if target == self._atom["UTF8_STRING"] or target in (
                self._atom["text/plain;charset=utf-8"],
                self._atom["text/plain"],
            ):
                return (target, 8, text.encode("utf-8"))
            if target in (self._atom["STRING"], self._atom["TEXT"]):
                return (target, 8, text.encode("latin-1", "replace"))
            return (None, 0, b"")
        if payload.kind is ClipboardKind.FILES:
            paths = payload.paths
            if target == self._atom["text/uri-list"]:
                return (
                    target,
                    8,
                    paths_to_uri_list(paths).encode("utf-8"),
                )
            if target == self._atom["x-special/gnome-copied-files"]:
                payload_text = "copy\n" + paths_to_uri_list(paths)
                return (target, 8, payload_text.encode("utf-8"))
            if target in (
                self._atom["UTF8_STRING"],
                self._atom["text/plain;charset=utf-8"],
                self._atom["text/plain"],
            ):
                return (target, 8, "\n".join(paths).encode("utf-8"))
            if target in (self._atom["STRING"], self._atom["TEXT"]):
                return (
                    target,
                    8,
                    "\n".join(paths).encode("latin-1", "replace"),
                )
            return (None, 0, b"")
        if payload.kind is ClipboardKind.IMAGE:
            if target == self._atom["image/png"]:
                return (target, 8, payload.png or b"")
            return (None, 0, b"")
        return (None, 0, b"")

    def _send_selection_notify(self, request: xevent.SelectionRequest, prop: int) -> None:
        notify = xevent.SelectionNotify(
            time=request.time,
            requestor=request.requestor,
            selection=request.selection,
            target=request.target,
            property=prop,
        )
        try:
            request.requestor.send_event(notify)
            self._display.flush()
        except (xerror.XError, OSError):
            pass
