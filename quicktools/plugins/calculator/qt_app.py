"""Process entry point for the PyQt6 calculator window.

The Tk application launches this module in a helper process (see
``qt_host.py``) so Tk and Qt never share an event loop.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from quicktools.plugins.calculator.qt_window import create_window

log = logging.getLogger(__name__)


class CommandReader(QThread):
    """Read newline commands from the Tk host without blocking Qt."""

    command = pyqtSignal(str)

    def run(self) -> None:
        try:
            for line in sys.stdin:
                command = line.strip()
                if command:
                    self.command.emit(command)
        except Exception:
            log.debug("读取计算器宿主命令失败", exc_info=True)
        finally:
            # The host closes the pipe when the Tk window is destroyed.
            self.command.emit("quit")


def run_helper(data_dir: Path | None) -> int:
    try:
        app = QApplication(sys.argv[:1])
    except Exception:
        log.exception("PyQt 计算器启动失败")
        return 1
    app.setApplicationName("QuickTools")
    app.setApplicationDisplayName("计算器")
    # Fusion keeps the stylesheet deterministic across Linux and Windows.
    app.setStyle("Fusion")
    try:
        window = create_window(data_dir)
    except Exception:
        log.exception("创建 PyQt 计算器窗口失败")
        return 1
    reader = CommandReader()
    reader.command.connect(window.handle_command)
    reader.start()
    log.info("PyQt 计算器界面已启动：data_dir=%s", data_dir)
    window.show_initial()
    try:
        sys.stdout.write("ready\n")
        sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        try:
            os.write(1, b"ready\n")
        except OSError:
            pass
    code = app.exec()
    log.info("PyQt 计算器界面已退出：code=%s", code)
    return code
