"""gp 悬浮窗 helper 进程入口（PyQt6）。

主进程用 ``--gp-qt-helper --data-dir <dir> --plugin-dir <dir>`` 拉起这个
进程：Qt 与 Tk 各跑各的事件循环，互不干扰。进程通过 stdin 收命令、
stdout 回事件。悬浮窗与它的设置对话框都在这个进程里，主进程不参与。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from .geometry import Size, place_dialog, screen_for_rect
from .qt_screens import rect_for, screen_areas
from .qt_settings import SettingsDialog, read_plugin_info
from .qt_widget import FloatingWidget
from .settings import GpSettings, load_settings, save_settings

log = logging.getLogger(__name__)

SAVE_DELAY_MS = 400


def emit_line(line: str) -> None:
    """Write one protocol line to stdout (the Tk side reads it)."""
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        try:
            os.write(1, (line + "\n").encode("utf-8"))
        except OSError:
            pass


def configure_application(app: QApplication) -> None:
    """Apply the helper process settings shared by production and tests."""
    app.setApplicationName("QuickTools")
    app.setApplicationDisplayName("gp 插件")
    # Fusion keeps the look deterministic across Linux and Windows.
    app.setStyle("Fusion")
    # 悬浮窗带 Qt.Tool 标志，不参与“最后一个主窗口”判定。保持默认的
    # quitOnLastWindowClosed=True 时，关闭设置对话框会被 Qt 当成最后一个
    # 主窗口关闭，直接退出 helper，表现为整个 gp 插件消失。
    # helper 只应在收到 quit 命令或 stdin EOF 时退出。
    app.setQuitOnLastWindowClosed(False)


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
            log.debug("读取 gp 悬浮窗宿主命令失败", exc_info=True)
        finally:
            # The host closes the pipe when the plugin window is destroyed.
            self.command.emit("quit")


class GpController(QObject):
    """Own the widget, the single settings dialog and the only writer."""

    def __init__(
        self,
        app: QApplication,
        data_dir: Path | None,
        plugin_dir: Path | None,
        settings: GpSettings,
    ) -> None:
        super().__init__()
        self._app = app
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self._info = read_plugin_info(plugin_dir)
        self._dialog: SettingsDialog | None = None
        self._closing = False
        self._widget = FloatingWidget(
            settings,
            on_open_settings=self.open_settings,
            on_exit=self.quit,
            emit=emit_line,
            persist=self._persist_widget,
        )
        # 设置项改动先即时生效，写盘合并到这个防抖定时器。
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_now)

    # ------------------------------------------------------------ commands
    def show(self) -> None:
        self._widget.show_widget()
        # 悬浮窗会 raise 自己；如果设置对话框还开着，保持它在最上面。
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()

    def hide(self) -> None:
        self.flush()
        self._hide_dialog()
        self._widget.hide()

    def quit(self) -> None:
        self.flush()
        self._hide_dialog()
        self._closing = True
        self._app.quit()

    def handle_command(self, command: str) -> None:
        if self._closing:
            return
        text = (command or "").strip()
        if not text:
            return
        if text == "show":
            self.show()
        elif text == "hide":
            self.hide()
        elif text == "quit":
            self.quit()

    # ----------------------------------------------------------- settings
    def flush(self) -> None:
        """Write pending changes immediately; safe to call more than once."""
        self.save_now()

    def save_now(self) -> None:
        self._save_timer.stop()
        if self._closing or self._data_dir is None:
            return
        try:
            save_settings(self._data_dir, self._widget.settings)
        except OSError:
            # 绝不能把异常抛出 PyQt 槽：未捕获异常会直接中止 helper 进程。
            log.exception("保存 gp 设置失败")

    def _persist_widget(self, settings: GpSettings) -> None:
        """Widget requested an immediate save after a position change."""
        self.save_now()

    def _hide_dialog(self) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.hide()

    # ------------------------------------------------------------ dialog
    def open_settings(self) -> None:
        try:
            if self._dialog is None:
                self._dialog = SettingsDialog(
                    self._info,
                    self._data_dir if self._data_dir is not None else Path("."),
                    current_settings=lambda: self._widget.settings,
                )
                self._dialog.appearanceChanged.connect(
                    self._on_appearance_changed
                )
                self._dialog.resetPositionRequested.connect(
                    self._on_reset_position
                )
                self._dialog.finished.connect(lambda _result=0: self.flush())
            self._dialog.set_settings(self._widget.settings)
            # 先完成布局再测宽高；否则会用到过时的默认尺寸，对话框可能
            # 被摆到屏幕外。
            self._dialog.adjustSize()
            self._place_dialog()
            self._dialog.show()
            # 某些窗口管理器会在 show() 时重新摆放顶层窗口，显示后再校正
            # 一次，确保对话框仍在悬浮窗旁边。
            self._dialog.adjustSize()
            self._place_dialog()
            self._dialog.raise_()
            self._dialog.activateWindow()
            log.info("用户操作：打开 gp 设置对话框")
        except Exception:
            log.exception("打开 gp 设置对话框失败")

    def _place_dialog(self) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        widget_rect = rect_for(self._widget)
        # 使用悬浮窗所在屏幕，而不是主屏；多显示器下对话框必须跟过去。
        area = screen_for_rect(widget_rect, screen_areas())
        if area is None:
            return
        x, y = place_dialog(
            widget_rect,
            Size(dialog.width(), dialog.height()),
            area,
        )
        dialog.move(x, y)

    def _on_appearance_changed(self, settings: object) -> None:
        if not isinstance(settings, GpSettings):
            return
        try:
            self._widget.apply_appearance(settings)
            # 直径滑块会连续触发 valueChanged，统一走 400ms 防抖；拖动悬浮窗
            # 和“恢复默认位置”仍然在 FloatingWidget 里立即落盘。
            self._save_timer.start()
            # 注意：不要在这里重新摆放设置对话框。用户可能已经把它拖到
            # 别处；调整透明度/直径时强制归位会覆盖用户的手动位置。
            # 对话框只在 open_settings() 打开时定位一次。
        except Exception:
            log.exception("应用 gp 外观设置失败")

    def _on_reset_position(self) -> None:
        try:
            # reset_position() 内部已经通过 persist 回调立即写盘。
            # 同样不移动设置对话框，尊重用户手动摆放的位置。
            self._widget.reset_position()
        except Exception:
            log.exception("恢复 gp 默认位置失败")


def run_helper(
    data_dir: Path | None, plugin_dir: Path | None = None
) -> int:
    """Start the floating widget and run the Qt event loop."""
    try:
        app = QApplication(sys.argv[:1])
    except Exception:
        log.exception("gp 悬浮窗启动失败")
        return 1
    configure_application(app)
    settings = load_settings(data_dir) if data_dir is not None else GpSettings()
    try:
        controller = GpController(app, data_dir, plugin_dir, settings)
        app.aboutToQuit.connect(controller.flush)
        reader = CommandReader()
        reader.command.connect(controller.handle_command)
        # 窗口创建后再启动读线程，避免命令丢失。
        reader.start()
        controller.show()
        log.info("gp 悬浮窗已启动：data_dir=%s", data_dir)
        emit_line("ready")
        code = app.exec()
        log.info("gp 悬浮窗已退出：code=%s", code)
        return code
    except Exception:
        log.exception("gp 悬浮窗运行失败")
        return 1
