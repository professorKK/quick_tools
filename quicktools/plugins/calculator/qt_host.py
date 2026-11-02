"""Tk-side controller for the PyQt6 calculator helper process.

The calculator plugin used to draw its UI inside a Tk Toplevel.  A Qt widget
cannot be embedded in that window, so the Qt interface runs in its own
process while the Tk window stays alive as an invisible lifecycle proxy.
The proxy keeps the launcher's "已打开" state, window state and close
semantics working; the visible window belongs to Qt.
"""

from __future__ import annotations

import ctypes.util
import importlib.util
import logging
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import messagebox

from quicktools import paths

log = logging.getLogger(__name__)

QT_HELPER_FLAG = "--calculator-qt-helper"
_FALLBACK_ENV = "QUICKTOOLS_CALCULATOR_TK"


def qt_available() -> bool:
    """True when the PyQt6 interface should be used."""
    if os.environ.get(_FALLBACK_ENV) == "1":
        return False
    if getattr(sys, "frozen", False):
        # PyInstaller bundles PyQt6 as a dependency; find_spec may not see the
        # frozen module until the helper imports it. The ready handshake still
        # falls back to Tk if the helper cannot start.
        return True
    return importlib.util.find_spec("PyQt6") is not None


def helper_command(data_dir: Path | None) -> list[str]:
    """Build the command that starts the Qt window process."""
    if getattr(sys, "frozen", False):
        command = [sys.executable, QT_HELPER_FLAG]
    else:
        command = [sys.executable, "-m", "quicktools", QT_HELPER_FLAG]
    if data_dir is not None:
        command.extend(["--data-dir", str(data_dir)])
    return command


def helper_environment() -> dict[str, str]:
    """Environment for the helper, including a fallback xcb-cursor library.

    Qt 6.5+ needs ``libxcb-cursor.so.0`` for the xcb platform plugin.  Some
    minimal Ubuntu installs do not ship it, so the Linux x86_64 build carries
    the MIT-licensed library under ``quicktools/vendor``.  Use it only when
    the system loader cannot find one.
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


class ExternalCalculatorWindow:
    def __init__(
        self,
        host: tk.Toplevel,
        data_dir: Path | None,
        on_failure: Callable[[], None] | None = None,
    ) -> None:
        self.host = host
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.on_failure = on_failure
        self.process: subprocess.Popen[str] | None = None
        self._poll_job: str | None = None
        self._startup_job: str | None = None
        self._closing = False
        self._failed = False
        self._ready = threading.Event()
        self._started = False

    def start(self) -> bool:
        """Start the helper; return False when the caller should use Tk."""
        self.host._qt_external_ui = True  # type: ignore[attr-defined]
        try:
            self.host.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        try:
            from quicktools.win32_window import prepare_tool_window

            # The Qt window is the only visible window; keep the invisible
            # proxy out of the Windows taskbar and Alt+Tab.
            prepare_tool_window(self.host)
        except Exception:
            log.debug("隐藏计算器代理窗口的任务栏入口失败", exc_info=True)
        self._conceal()
        try:
            self.process = subprocess.Popen(
                helper_command(self.data_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                close_fds=True,
                env=helper_environment(),
            )
        except OSError:
            log.exception("启动 PyQt 计算器进程失败，回退到 Tk 界面")
            self._restore_host()
            return False
        if self.process.poll() is not None:
            log.error(
                "PyQt 计算器进程启动后立即退出，回退到 Tk 界面：code=%s",
                self.process.returncode,
            )
            self._restore_host()
            return False
        threading.Thread(
            target=self._read_ready, args=(self.process,), daemon=True
        ).start()
        self._started = True
        self.host.bind("<Map>", self._on_host_map, add="+")
        self.host.bind("<Unmap>", self._on_host_unmap, add="+")
        self.host.bind("<Destroy>", self._on_host_destroy, add="+")
        self._poll_job = self.host.after(200, self._poll)
        self._startup_job = self.host.after(4000, self._check_startup)
        self.show()
        return True

    def _read_ready(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is None:
                return
            for line in process.stdout:
                if line.strip() == "ready":
                    self._ready.set()
                    return
        except (OSError, ValueError):
            pass

    def _check_startup(self) -> None:
        self._startup_job = None
        if self._closing or self._failed or self._ready.is_set():
            return
        process = self.process
        if process is not None and process.poll() is None:
            # A slow but live helper is left alone; the window may still be
            # initializing. Only an exited helper triggers the Tk fallback.
            return
        log.error("PyQt 计算器未报告启动完成，回退到 Tk 界面")
        self._fallback_to_tk()

    def _fallback_to_tk(self) -> None:
        if self._failed:
            return
        self._failed = True
        self.close()
        self._restore_host()
        callback = self.on_failure
        if callback is not None:
            try:
                callback()
            except Exception:
                log.exception("回退到 Tk 计算器界面失败")

    # ------------------------------------------------------------ commands
    def show(self) -> None:
        self._send("show")

    def hide(self) -> None:
        self._send("hide")

    def close(self, *, wait: bool = True) -> None:
        if self._closing:
            return
        self._closing = True
        self._cancel_poll()
        self._cancel_startup()
        process = self.process
        self.process = None
        if process is None:
            return
        self._write(process, "quit")
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if wait:
            # The host window can be destroyed while a data-root migration is
            # starting; give the helper a moment to flush and exit so it does
            # not write into the old plugin directory after migration begins.
            try:
                process.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                pass
        threading.Thread(
            target=self._reap, args=(process,), daemon=True
        ).start()

    def _send(self, command: str) -> None:
        process = self.process
        if process is None:
            return
        self._write(process, command)

    @staticmethod
    def _write(process: subprocess.Popen[str], command: str) -> None:
        try:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.write(command + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

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

    # -------------------------------------------------------------- host
    def _conceal(self) -> None:
        """Keep the lifecycle proxy invisible and off-screen."""
        try:
            self.host.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        try:
            self.host.geometry("1x1+-10000+-10000")
        except tk.TclError:
            pass
        try:
            from quicktools.win32_window import prepare_tool_window

            # The Tk handle exists only after the first map on Windows.
            prepare_tool_window(self.host)
        except Exception:
            log.debug("隐藏计算器代理窗口的任务栏入口失败", exc_info=True)

    def _restore_host(self) -> None:
        self._started = False
        self.host._qt_external_ui = False  # type: ignore[attr-defined]
        try:
            self.host.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        try:
            self.host.geometry("")
        except tk.TclError:
            pass

    def _on_host_map(self, event: tk.Event) -> None:
        if event.widget is not self.host or self._closing:
            return
        self.host.after_idle(self._conceal)
        self.show()

    def _on_host_unmap(self, event: tk.Event) -> None:
        if event.widget is not self.host or self._closing:
            return
        self.hide()

    def _on_host_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.host:
            return
        self.close()

    def _cancel_poll(self) -> None:
        job = self._poll_job
        self._poll_job = None
        if job is None:
            return
        try:
            self.host.after_cancel(job)
        except tk.TclError:
            pass

    def _cancel_startup(self) -> None:
        job = self._startup_job
        self._startup_job = None
        if job is None:
            return
        try:
            self.host.after_cancel(job)
        except tk.TclError:
            pass

    def _poll(self) -> None:
        self._poll_job = None
        process = self.process
        if process is None or self._closing:
            return
        code = process.poll()
        if code is None:
            try:
                self._poll_job = self.host.after(200, self._poll)
            except tk.TclError:
                pass
            return
        if not self._ready.is_set():
            log.error("PyQt 计算器启动失败：code=%s", code)
            self._fallback_to_tk()
            return
        log.info("PyQt 计算器进程已退出：code=%s", code)
        self.process = None
        self._cancel_startup()
        if code not in (0, None):
            log.error("PyQt 计算器异常退出：code=%s", code)
            try:
                messagebox.showerror(
                    "计算器界面错误",
                    "PyQt 计算器窗口异常退出，请查看日志：\n\n"
                    f"{log_file()}",
                    parent=self.host.master,
                )
            except tk.TclError:
                pass
        try:
            if self.host.winfo_exists():
                self.host.destroy()
        except tk.TclError:
            pass


def log_file() -> str:
    from quicktools import paths

    return str(paths.log_file())
