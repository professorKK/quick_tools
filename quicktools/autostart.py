"""Register QuickTools to start with the user's desktop session.

Linux uses the freedesktop XDG Autostart specification; Windows uses the
per-user ``Run`` registry key. The operating-system entry is the single source
of truth, so no autostart flag is stored in settings.json.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "QuickTools"
LINUX_DESKTOP_NAME = "quicktools.desktop"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINDOWS_VALUE_NAME = "QuickTools"
BACKGROUND_FLAG = "--background"


def is_supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def startup_command() -> list[str]:
    """The exact command the session manager should run at login."""
    if getattr(sys, "frozen", False):
        return [sys.executable, BACKGROUND_FLAG]
    return [sys.executable, "-m", "quicktools", BACKGROUND_FLAG]


# --------------------------------------------------------------------- Linux
def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        candidate = Path(raw).expanduser()
        # The XDG spec says relative values must be ignored.
        if candidate.is_absolute():
            return candidate
    return Path.home() / ".config"


def linux_desktop_file() -> Path:
    return _xdg_config_home() / "autostart" / LINUX_DESKTOP_NAME


def _quote_exec_arg(value: str) -> str:
    """Quote one Exec argument per the Desktop Entry specification.

    Shell quoting is wrong here: the spec quotes with double quotes and only
    escapes double quote, backtick, dollar sign and backslash; a literal ``%``
    starts a field code and must be doubled. Quote every argument
    unconditionally.
    """
    value = value.replace("%", "%%")
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("`", "\\`")
    value = value.replace("$", "\\$")
    return f'"{value}"'


def _desktop_entry(command: list[str]) -> str:
    exec_line = " ".join(_quote_exec_arg(part) for part in command)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Start QuickTools in the background at login\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _linux_is_enabled() -> bool:
    return linux_desktop_file().is_file()


def _linux_enable() -> None:
    path = linux_desktop_file()
    _write_atomic(path, _desktop_entry(startup_command()))
    log.info("已写入 Linux 自启动项：%s", path)


def _linux_disable() -> None:
    path = linux_desktop_file()
    try:
        path.unlink()
    except FileNotFoundError:
        return
    log.info("已删除 Linux 自启动项：%s", path)


# ------------------------------------------------------------------- Windows
def _winreg():
    import winreg  # only available on Windows

    return winreg


def _windows_command() -> str:
    return subprocess.list2cmdline(startup_command())


def _windows_is_enabled() -> bool:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            winreg.QueryValueEx(key, WINDOWS_VALUE_NAME)
    except FileNotFoundError:
        return False
    return True


def _windows_enable() -> None:
    winreg = _winreg()
    command = _windows_command()
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, WINDOWS_VALUE_NAME, 0, winreg.REG_SZ, command)
    log.info("已写入 Windows 登录启动项 %s：%s", WINDOWS_VALUE_NAME, command)


def _windows_disable() -> None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, WINDOWS_VALUE_NAME)
    except FileNotFoundError:
        return
    log.info("已删除 Windows 登录启动项：%s", WINDOWS_VALUE_NAME)


# ---------------------------------------------------------------- public API
def is_enabled() -> bool:
    if sys.platform == "win32":
        return _windows_is_enabled()
    if sys.platform.startswith("linux"):
        return _linux_is_enabled()
    return False


def enable() -> None:
    if sys.platform == "win32":
        _windows_enable()
        return
    if sys.platform.startswith("linux"):
        _linux_enable()
        return
    raise RuntimeError("当前平台不支持开机启动")


def disable() -> None:
    if sys.platform == "win32":
        _windows_disable()
        return
    if sys.platform.startswith("linux"):
        _linux_disable()
        return
    raise RuntimeError("当前平台不支持开机启动")


def mechanism_hint() -> str:
    if sys.platform == "win32":
        return rf"Windows 登录启动项：HKCU\{WINDOWS_RUN_KEY}\{WINDOWS_VALUE_NAME}"
    if sys.platform.startswith("linux"):
        return f"Linux 自启动文件：{linux_desktop_file()}"
    return "当前平台不支持开机启动。"
