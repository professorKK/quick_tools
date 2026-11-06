"""Tk 侧控制器：管理 gp 悬浮窗的 PyQt helper 进程。

Tk 主进程只做三件事：把 helper 进程拉起来、转发 show/hide/quit 命令、把
helper 的 stdout 事件放回主线程。悬浮窗界面与它的设置对话框都在 Qt 进程
里，**Tk 侧不实现任何 gp 界面**。后台线程只往队列里塞字符串，Tk 主线程用
``after`` 抽干后再处理。
"""

from __future__ import annotations

import ctypes.util
import importlib.util
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

from quicktools import paths

log = logging.getLogger(__name__)

GP_HELPER_FLAG = "--gp-qt-helper"

POLL_INTERVAL_MS = 200
DRAIN_INTERVAL_MS = 100
STARTUP_TIMEOUT_MS = 8000
REAP_TIMEOUT = 1.0

EVENT_CLOSED = "closed"
EVENT_POSITION = "position"


def qt_available() -> bool:
    """True when the PyQt6 helper can be started in this environment."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundles PyQt6 as a dependency; find_spec may not see the
        # frozen module until the helper imports it. The ready handshake
        # reports a real startup failure.
        return True
    return importlib.util.find_spec("PyQt6") is not None


def helper_command(
    data_dir: Path | None, plugin_dir: Path | None = None
) -> list[str]:
    """Build the command that starts the floating widget process."""
    if getattr(sys, "frozen", False):
        command = [sys.executable, GP_HELPER_FLAG]
    else:
        command = [sys.executable, "-m", "quicktools", GP_HELPER_FLAG]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir)])
    if plugin_dir is not None:
        command.extend(["--plugin-dir", str(plugin_dir)])
    return command


def helper_environment() -> dict[str, str]:
    """Environment for the helper, including a fallback xcb-cursor library.

    Qt 6.5+ needs ``libxcb-cursor.so.0`` for the xcb platform plugin. Some
    minimal Ubuntu installs do not ship it, so the Linux x86_64 build carries
    the MIT-licensed library under ``quicktools/vendor``. Use it only when the
    system loader cannot find one.
    """
    env = os.environ.copy()
    if not sys.platform.startswith("linux"):
        return env
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return env
    try:
        if ctypes.util.find_library("xcb-cursor"):
            return env
    except Exception:
        pass
    vendor = paths.package_dir() / "vendor" / "linux-x86_64"
    if not (vendor / "libxcb-cursor.so.0").exists():
        return env
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = (
        str(vendor) + (os.pathsep + current if current else "")
    )
    return env


def parse_event(line: str) -> tuple[str, tuple]:
    """Translate one helper stdout line into an event name and payload.

    ``ready`` is consumed by the reader thread and never reaches this function.
    Unknown lines are ignored so a newer helper cannot break an older host.
    """
    text = (line or "").strip()
    if not text:
        return ("", ())
    if text == EVENT_CLOSED:
        return (EVENT_CLOSED, ())
    if text.startswith(f"{EVENT_POSITION} "):
        parts = text.split()
        if len(parts) >= 3:
            try:
                return (EVENT_POSITION, (int(parts[1]), int(parts[2])))
            except ValueError:
                return ("", ())
    return ("", ())


class GpFloatingHost:
    """Own the helper process that shows the floating widget."""

    def __init__(
        self,
        host_window: tk.Toplevel,
        data_dir: Path,
        plugin_dir: Path | None = None,
    ) -> None:
        self._window = host_window
        self._data_dir = Path(data_dir)
        self._plugin_dir = Path(plugin_dir) if plugin_dir is not None else None
        self._process: subprocess.Popen[str] | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._ready = threading.Event()
        self._closing = False
        self._failed = False
        self._drain_job: str | None = None
        self._poll_job: str | None = None
        self._startup_job: str | None = None
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._stderr_thread: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> bool:
        """Start the helper; return False when it could not be launched."""
        # The visible window lives in the helper process; the Tk window is
        # only an invisible lifecycle proxy.
        self._window._qt_external_ui = True  # type: ignore[attr-defined]
        self._conceal()
        try:
            self._process = subprocess.Popen(
                helper_command(self._data_dir, self._plugin_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                close_fds=True,
                env=helper_environment(),
            )
        except OSError:
            log.exception("启动 gp 悬浮窗进程失败")
            self._process = None
            return False
        if self._process.poll() is not None:
            details = self._read_stderr_now(self._process)
            log.error(
                "gp 悬浮窗进程启动后立即退出：code=%s%s",
                self._process.returncode,
                f"\n{details}" if details else "",
            )
            self._process = None
            return False
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, args=(self._process,), daemon=True
        )
        self._stderr_thread.start()
        threading.Thread(
            target=self._read_stdout, args=(self._process,), daemon=True
        ).start()
        self._window.bind("<Map>", self._on_host_map, add="+")
        self._window.bind("<Destroy>", self._on_host_destroy, add="+")
        self._poll_job = self._window.after(POLL_INTERVAL_MS, self._poll)
        self._drain_job = self._window.after(DRAIN_INTERVAL_MS, self._drain)
        self._startup_job = self._window.after(
            STARTUP_TIMEOUT_MS, self._check_startup
        )
        self.show()
        return True

    def close(self) -> None:
        """Stop the helper and release every timer."""
        if self._closing:
            return
        self._closing = True
        self._cancel_jobs()
        process = self._process
        self._process = None
        if process is None:
            return
        self._write(process, "quit")
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=REAP_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError):
            pass
        threading.Thread(
            target=self._reap, args=(process,), daemon=True
        ).start()

    # ------------------------------------------------------------ commands
    def show(self) -> None:
        self._send("show")

    def hide(self) -> None:
        self._send("hide")

    # -------------------------------------------------------------- events
    def handle_line(self, line: str) -> None:
        """Handle one helper stdout line (Tk main thread only)."""
        name, payload = parse_event(line)
        if not name:
            return
        if name == EVENT_CLOSED:
            log.info("用户操作：退出 gp 插件")
            # 右键“退出”表示关闭插件本身。销毁代理窗口会让启动器移除该
            # 插件窗口、卡片恢复为未打开；<Destroy> 再通知 helper 退出。
            self._destroy_window()
        elif name == EVENT_POSITION:
            x, y = payload
            log.info("gp 悬浮窗位置已更新：x=%s y=%s", x, y)

    # -------------------------------------------------------------- timers
    def _drain(self) -> None:
        self._drain_job = None
        if self._closing:
            return
        while True:
            try:
                line = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                self.handle_line(line)
            except Exception:
                log.exception("处理 gp 悬浮窗事件失败")
        self._schedule_drain()

    def _schedule_drain(self) -> None:
        if self._closing:
            return
        try:
            self._drain_job = self._window.after(DRAIN_INTERVAL_MS, self._drain)
        except tk.TclError:
            self._drain_job = None

    def _poll(self) -> None:
        self._poll_job = None
        process = self._process
        if process is None or self._closing:
            return
        code = process.poll()
        if code is None:
            try:
                self._poll_job = self._window.after(
                    POLL_INTERVAL_MS, self._poll
                )
            except tk.TclError:
                pass
            return
        self._process = None
        self._cancel_jobs()
        if not self._ready.is_set():
            log.error("gp 悬浮窗启动失败：code=%s", code)
            self._report_failure()
            return
        log.info("gp 悬浮窗进程已退出：code=%s", code)
        if code not in (0, None):
            self._log_stderr_tail("gp 悬浮窗错误输出")
            self._destroy_window()
            self._show_error(
                "gp 悬浮窗异常退出，请查看日志：\n\n"
                f"{self._log_file()}"
            )
            return
        self._destroy_window()

    def _check_startup(self) -> None:
        self._startup_job = None
        if self._closing or self._failed or self._ready.is_set():
            return
        log.error("gp 悬浮窗未报告启动完成")
        self._report_failure()

    def _report_failure(self) -> None:
        if self._failed:
            return
        self._failed = True
        self._log_stderr_tail("gp 悬浮窗错误输出")
        self.close()
        self._destroy_window()
        self._show_error(
            "无法启动 gp 悬浮窗，请检查 PyQt6 与 Qt 平台库是否可用。\n\n"
            f"详细日志：{self._log_file()}"
        )

    def _show_error(self, message: str) -> None:
        try:
            messagebox.showerror(
                "gp 插件错误",
                message,
                parent=self._window.master,
            )
        except tk.TclError:
            pass

    def _destroy_window(self) -> None:
        try:
            self._window.withdraw()
            self._window.update_idletasks()
        except tk.TclError:
            pass
        try:
            self._window.destroy()
        except tk.TclError:
            pass

    def _cancel_jobs(self) -> None:
        for attribute in ("_drain_job", "_poll_job", "_startup_job"):
            job = getattr(self, attribute)
            setattr(self, attribute, None)
            if job is None:
                continue
            try:
                self._window.after_cancel(job)
            except tk.TclError:
                pass

    # --------------------------------------------------------------- proxy
    def _conceal(self) -> None:
        """Keep the lifecycle proxy invisible and off-screen."""
        try:
            self._window.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        try:
            self._window.geometry("1x1+-10000+-10000")
        except tk.TclError:
            pass
        try:
            from quicktools.win32_window import prepare_tool_window

            # The Qt window is the only visible window; keep the invisible
            # proxy out of the Windows taskbar and Alt+Tab.
            prepare_tool_window(self._window)
        except Exception:
            log.debug("隐藏 gp 代理窗口的任务栏入口失败", exc_info=True)

    def _on_host_map(self, event: tk.Event) -> None:
        if event.widget is not self._window or self._closing:
            return
        self._window.after_idle(self._conceal)
        self.show()

    def _on_host_destroy(self, event: tk.Event) -> None:
        if event.widget is not self._window:
            return
        self.close()

    # ------------------------------------------------------------- process
    def _send(self, command: str) -> None:
        process = self._process
        if process is None:
            return
        self._write(process, command)

    @staticmethod
    def _write(process: subprocess.Popen[str], command: str) -> None:
        try:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.write(command + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            log.debug("向 gp 悬浮窗进程写入命令失败", exc_info=True)

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        """Push helper events into the queue; never touch Tk from here."""
        try:
            if process.stdout is None:
                return
            for line in process.stdout:
                text = line.strip()
                if not text:
                    continue
                if text == "ready":
                    self._ready.set()
                    continue
                self._queue.put(text)
        except (OSError, ValueError):
            log.debug("读取 gp 悬浮窗输出失败", exc_info=True)

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        """Drain the helper's stderr so Qt fatal errors are not lost."""
        try:
            if process.stderr is None:
                return
            for line in process.stderr:
                text = line.rstrip()
                if not text:
                    continue
                self._stderr_tail.append(text)
                log.debug("gp 悬浮窗 stderr：%s", text)
        except (OSError, ValueError):
            pass

    @staticmethod
    def _read_stderr_now(process: subprocess.Popen[str]) -> str:
        """Best-effort read for a helper that already exited."""
        try:
            if process.stderr is None:
                return ""
            return process.stderr.read().strip()
        except (OSError, ValueError):
            return ""

    def _log_stderr_tail(self, reason: str) -> None:
        thread = self._stderr_thread
        if thread is not None and thread is not threading.current_thread():
            # 进程已经退出，读取线程即将到达 EOF；短暂等待最后的 traceback。
            thread.join(timeout=0.2)
        if not self._stderr_tail:
            return
        log.error("%s\n%s", reason, "\n".join(self._stderr_tail))

    @staticmethod
    def _log_file() -> str:
        try:
            return str(paths.log_file())
        except Exception:
            return ""

    @staticmethod
    def _reap(process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            process.terminate()
            process.wait(timeout=1)
            return
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            process.kill()
        except OSError:
            pass
