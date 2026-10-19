"""System-tray / top-bar icon.

On Linux we prefer the desktop's native StatusNotifierItem/AppIndicator
implementation, so the menu is rendered by GNOME/Ubuntu exactly like other
application indicators. The indicator lives in a child process using the
system Python and its Ayatana AppIndicator/GI packages.

If those system packages are unavailable, we fall back to pystray's XEmbed
backend and a Tk dropdown. Windows uses the native pystray tray menu.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

try:
    import pystray
    from PIL import Image, ImageDraw

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - broken optional dependency
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc

log = logging.getLogger(__name__)


def _make_icon_image():
    from . import paths

    filename = "tray-linux.png" if sys.platform.startswith("linux") else "tray.png"
    try:
        with Image.open(paths.assets_dir() / filename) as source:
            return source.convert("RGBA")
    except Exception as exc:
        log.warning("无法加载 %s，使用内置状态栏图标：%s", filename, exc)
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(91, 140, 255, 255))
    draw.rounded_rectangle((16, 17, 48, 26), radius=3, fill=(255, 255, 255, 255))
    draw.rounded_rectangle((16, 33, 48, 42), radius=3, fill=(255, 255, 255, 255))
    return image


def _tray_backend():
    if pystray is None:
        raise RuntimeError(f"pystray 不可用：{_IMPORT_ERROR}")
    if sys.platform.startswith("linux"):
        # XEmbed works in the current Ubuntu X11 top bar. It also keeps the
        # PyInstaller build independent of PyGObject/AppIndicator.
        from pystray import _xorg

        return _xorg
    return pystray


def _icon_anchor(icon) -> tuple[int, int]:
    """Return the X11 tray icon's screen anchor, if the backend exposes it."""
    display = getattr(icon, "_display", None)
    window = getattr(icon, "_window", None)
    if display is None or window is None:
        return -1, -1
    try:
        root = display.screen().root
        window_geom = window.get_geometry()
        x = y = 0
        current = window
        while current is not None:
            geom = current.get_geometry()
            x += geom.x
            y += geom.y
            if current.id == root.id:
                break
            current = current.query_tree().parent
        return int(x + window_geom.width // 2), int(y + window_geom.height + 4)
    except Exception:
        return -1, -1


def run_tray_helper() -> int:
    """Entry point for the ``--tray-helper`` child process."""
    from .ipc import send_command, send_tray_menu

    try:
        backend = _tray_backend()
        image = _make_icon_image()

        def send(command: str) -> None:
            try:
                send_command(command)
            except Exception:
                log.exception("状态栏命令发送失败：%s", command)

        def open_menu(icon, _item=None) -> None:
            x, y = _icon_anchor(icon)
            try:
                if not send_tray_menu(x, y):
                    log.warning("无法通知主程序显示状态栏菜单")
            except Exception:
                log.exception("状态栏菜单请求失败")

        if sys.platform.startswith("linux"):
            # Xorg's backend has no native menu. Left-clicking the icon sends
            # its screen anchor to the main process, which pops up a Tk menu.
            menu = pystray.Menu(
                pystray.MenuItem("显示", open_menu, default=True),
                pystray.MenuItem(
                    "退出", lambda _icon, _item: send("quit")
                ),
            )
        else:
            menu = pystray.Menu(
                pystray.MenuItem(
                    "显示",
                    lambda _icon, _item: send("show"),
                    default=True,
                ),
                pystray.MenuItem(
                    "退出", lambda _icon, _item: send("quit")
                ),
            )
        # The Xorg backend requires a Latin-1-safe window title.
        icon = backend.Icon("quicktools", image, "QuickTools", menu)
        icon_window = getattr(icon, "_window", None)
        if icon_window is not None:
            log.info("状态栏图标窗口：%#x", icon_window.id)
        stop_watchdog = threading.Event()

        def watchdog() -> None:
            misses = 0
            while not stop_watchdog.wait(3.0):
                if send_command("ping"):
                    misses = 0
                else:
                    misses += 1
                    if misses >= 2:
                        log.info("主实例已退出，关闭状态栏图标")
                        try:
                            icon.stop()
                        except Exception:
                            pass
                        return

        watchdog_thread = threading.Thread(
            target=watchdog, name="quicktools-tray-watchdog", daemon=True
        )
        watchdog_thread.start()
        log.info("状态栏助手已启动")
        try:
            icon.run()
        finally:
            stop_watchdog.set()
            try:
                icon.stop()
            except Exception:
                pass
        return 0
    except Exception:
        log.exception("状态栏助手启动失败")
        return 1


class TrayController:
    """Starts and supervises the tray helper child process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self.available = False
        self.mode = ""

    @staticmethod
    def _native_helper_path():
        from . import paths

        return paths.package_dir() / "helpers" / "tray_appindicator.py"

    def _system_python(self) -> str | None:
        """Find a system Python with GTK3/Ayatana AppIndicator available."""
        if not sys.platform.startswith("linux"):
            return None
        helper = self._native_helper_path()
        icon = None
        try:
            from . import paths

            icon = paths.assets_dir() / "tray-linux.png"
        except Exception:
            return None
        if not helper.is_file() or icon is None or not icon.is_file():
            return None

        probe = (
            "import gi;"
            "gi.require_version('Gtk','3.0');"
            "gi.require_version('AyatanaAppIndicator3','0.1');"
            "from gi.repository import Gtk, AyatanaAppIndicator3"
        )
        for python in ("/usr/bin/python3", "/usr/bin/python3.10"):
            if not os.path.isfile(python):
                continue
            try:
                result = subprocess.run(
                    [python, "-c", probe],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=False,
                )
                if result.returncode == 0:
                    return python
            except Exception:
                continue
        return None

    def _start_native(self, python: str) -> bool:
        from . import paths

        helper = self._native_helper_path()
        icon = paths.assets_dir() / "tray-linux.png"
        endpoint = paths.ipc_runtime_file()
        command = [
            python,
            str(helper),
            "--endpoint",
            str(endpoint),
            "--icon",
            str(icon),
        ]
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
            "start_new_session": True,
        }
        try:
            self._process = subprocess.Popen(command, **kwargs)
            self.available = True
            self.mode = "appindicator"
            log.info(
                "原生状态栏助手已启动（AppIndicator/SNI）：pid=%s",
                self._process.pid,
            )
            return True
        except Exception as exc:
            log.warning("原生状态栏启动失败：%s", exc)
            self._process = None
            self.available = False
            return False

    def _start_pystray(self) -> bool:
        if pystray is None:
            log.warning("状态栏图标不可用：%s", _IMPORT_ERROR)
            return False
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--tray-helper"]
        else:
            command = [sys.executable, "-m", "quicktools", "--tray-helper"]
        kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            self._process = subprocess.Popen(command, **kwargs)
            self.available = True
            self.mode = "pystray"
            log.info("回退状态栏助手进程已启动：pid=%s", self._process.pid)
            return True
        except Exception as exc:
            log.warning("状态栏助手启动失败：%s", exc)
            self._process = None
            self.available = False
            return False

    def start(self) -> bool:
        if sys.platform.startswith("linux"):
            python = self._system_python()
            if python is not None and self._start_native(python):
                return True
        return self._start_pystray()

    def stop(self) -> None:
        process = self._process
        self._process = None
        self.available = False
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=0.5)
            except Exception:
                pass
        except Exception:
            log.debug("停止状态栏助手失败", exc_info=True)
