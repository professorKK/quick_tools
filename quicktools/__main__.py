"""QuickTools command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from . import DISPLAY_NAME, __version__
from .app import QuickToolsApp
from .ipc import send_command
from .logging_setup import setup_logging
from .paths import ensure_app_dirs

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quicktools",
        description=f"{DISPLAY_NAME}：全局快捷键唤出的 Tkinter 插件启动器",
    )
    parser.add_argument("--toggle", action="store_true", help="切换启动器显示状态")
    parser.add_argument("--show", action="store_true", help="显示启动器")
    parser.add_argument("--quit", action="store_true", help="退出已运行的实例")
    parser.add_argument(
        "--tray-helper", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_app_dirs()
    setup_logging()

    if args.tray_helper:
        from .tray import run_tray_helper

        return run_tray_helper()

    if args.toggle or args.show or args.quit:
        command = "toggle" if args.toggle else ("show" if args.show else "quit")
        if send_command(command):
            return 0
        if command == "quit":
            log.info("没有正在运行的快捷工具实例")
            return 0
        # No primary instance: --toggle/--show start the app.
    else:
        # A normal second launch should surface the existing launcher.
        if send_command("show"):
            return 0

    try:
        app = QuickToolsApp(start_visible=True)
        app.run()
        return 0
    except Exception as exc:
        log.exception("快捷工具启动失败")
        if sys.stderr is not None:
            print(f"快捷工具启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
