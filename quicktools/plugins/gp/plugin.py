"""gp 插件入口：桌面圆形悬浮窗。

悬浮窗和它的设置对话框都在独立的 PyQt 进程里（见 ``qt_helper.py``），Tk
主进程只保留一个不可见的生命周期代理窗口。**插件不在 Tk 侧实现任何界面。**
"""

from __future__ import annotations

import logging
import tkinter as tk

from quicktools.plugin_api import PluginBase

from .host import GpFloatingHost, qt_available

log = logging.getLogger(__name__)

_QT_REQUIRED_MESSAGE = (
    "gp 插件需要 PyQt6，请先安装 PyQt6"
    "（pip install \"PyQt6>=6.6,<7\"）后重试。"
)


class GpPlugin(PluginBase):
    def __init__(self, context) -> None:
        super().__init__(context)
        self._host: GpFloatingHost | None = None

    # ------------------------------------------------------------ lifecycle
    def create_ui(self, window: tk.Toplevel) -> None:
        if not qt_available():
            raise RuntimeError(_QT_REQUIRED_MESSAGE)
        host = GpFloatingHost(
            window,
            self.context.data_dir,
            getattr(self.context, "plugin_dir", None),
        )
        self._host = host
        try:
            started = host.start()
        except Exception as exc:
            log.exception("启动 gp 悬浮窗失败")
            self._host = None
            try:
                host.close()
            except Exception:
                log.debug("清理启动失败的 gp 进程失败", exc_info=True)
            raise RuntimeError("无法启动 gp 悬浮窗，请查看日志。") from exc
        if not started:
            self._host = None
            try:
                host.close()
            except Exception:
                log.debug("清理启动失败的 gp 进程失败", exc_info=True)
            raise RuntimeError("无法启动 gp 悬浮窗，请查看日志。")
        log.info("gp 悬浮窗使用独立 PyQt 进程")

    def on_window_shown(self, window: tk.Toplevel) -> None:
        # 每次显示插件窗口时通知 helper。右键“退出”会销毁代理窗口，
        # 再点卡片会创建新实例和新 helper，同样走这里的 show。
        if self._host is not None:
            self._host.show()
