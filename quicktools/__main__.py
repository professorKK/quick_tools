"""QuickTools command-line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

from . import DISPLAY_NAME, __version__
from .app import QuickToolsApp
from .ipc import send_command
from .logging_setup import setup_logging
from .paths import ensure_app_dirs

log = logging.getLogger(__name__)

_DETACH_ENV = "QUICKTOOLS_DETACHED"
_DETACH_VALUE = "1"
_SCREENSHOT_ACTIONS = {
    "region": "capture_region",
    "window": "capture_window",
    "freeform": "capture_freeform",
    "scroll": "capture_scroll",
    "open": "open",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quicktools",
        description=f"{DISPLAY_NAME}：全局快捷键唤出的 Tkinter 插件启动器",
    )
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--toggle", action="store_true", help="切换启动器显示状态")
    commands.add_argument("--show", action="store_true", help="显示启动器")
    commands.add_argument("--quit", action="store_true", help="退出已运行的实例")
    commands.add_argument(
        "--background",
        action="store_true",
        help="后台启动（登录自启动使用；已有实例时静默退出）",
    )
    commands.add_argument(
        "--screenshot",
        nargs="?",
        const="region",
        choices=tuple(_SCREENSHOT_ACTIONS),
        metavar="MODE",
        help="触发截图：region（默认）/ window / freeform / scroll / open",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="在前台运行，不脱离终端（Linux 打包版调试用）",
    )
    parser.add_argument(
        "--tray-helper", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _stream_is_tty(stream: object) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def _has_terminal() -> bool:
    return any(
        _stream_is_tty(stream) for stream in (sys.stdin, sys.stdout, sys.stderr)
    )


def _already_detached() -> bool:
    return os.environ.get(_DETACH_ENV) == _DETACH_VALUE


def _should_detach(args: argparse.Namespace) -> bool:
    return (
        _is_linux()
        and _is_frozen()
        and _has_terminal()
        and not args.foreground
        and not args.tray_helper
        and not args.quit
        and not _already_detached()
    )


def _detach_command(argv: list[str]) -> list[str]:
    if _is_frozen():
        return [sys.executable, *argv]
    return [sys.executable, "-m", "quicktools", *argv]


def _spawn_detached(argv: list[str]) -> bool:
    """Relaunch this invocation in a new session, detached from the terminal."""
    env = os.environ.copy()
    env[_DETACH_ENV] = _DETACH_VALUE
    try:
        process = subprocess.Popen(
            _detach_command(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            env=env,
        )
    except OSError:
        log.exception("无法在后台启动 QuickTools")
        return False
    log.info("QuickTools 已转入后台运行：pid=%s", process.pid)
    return True


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(effective_argv)
    ensure_app_dirs()
    setup_logging()

    if args.tray_helper:
        from .tray import run_tray_helper

        return run_tray_helper()

    start_visible = True
    startup_command: str | None = None
    if args.background:
        # Login autostart: never surface the launcher. "ping" is answered
        # directly by the IPC server, so it does not trigger any UI.
        if send_command("ping"):
            return 0
        start_visible = False
    elif args.screenshot:
        action = _SCREENSHOT_ACTIONS[args.screenshot]
        startup_command = f"plugin screenshot {action}"
        if send_command(startup_command):
            return 0
        # No primary instance: start hidden, then run the action once the
        # Tk main loop is draining commands.
        start_visible = False
    elif args.toggle or args.show or args.quit:
        command = "toggle" if args.toggle else ("show" if args.show else "quit")
        if send_command(command):
            return 0
        if command == "quit":
            log.info("没有正在运行的快捷工具实例")
            return 0
        # No primary instance: --toggle/--show start the app. Route --toggle
        # through the command queue so a cold start behaves exactly like a
        # hotkey wake-up (including click-outside auto-hide).
        if command == "toggle":
            start_visible = False
            startup_command = "toggle"
    else:
        # A normal second launch should surface the existing launcher.
        if send_command("show"):
            return 0

    # Pre-flight is done, so this process is about to own the GUI. In the
    # packaged Linux build launched from a terminal, hand it to a detached
    # copy so the shell prompt returns and closing the terminal is safe.
    if _should_detach(args):
        if not _spawn_detached(effective_argv):
            message = "后台启动 QuickTools 失败，请使用 --foreground 前台运行以查看错误。"
            log.error(message)
            if sys.stderr is not None:
                print(message, file=sys.stderr)
            return 1
        return 0

    try:
        app = QuickToolsApp(start_visible=start_visible)
        if startup_command is not None:
            app.commands.put(startup_command)
        app.run()
        return 0
    except Exception as exc:
        log.exception("快捷工具启动失败")
        if sys.stderr is not None:
            print(f"快捷工具启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
