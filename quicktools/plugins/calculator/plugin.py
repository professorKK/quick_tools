"""Calculator plugin entry point."""

from __future__ import annotations

import logging
import tkinter as tk

from quicktools.plugin_api import PluginBase
from quicktools.plugins.calculator.qt_host import (
    ExternalCalculatorWindow,
    qt_available,
)

log = logging.getLogger(__name__)

_QT_REQUIRED_MESSAGE = (
    "计算器需要 PyQt6，请先安装 PyQt6"
    "（pip install \"PyQt6>=6.6,<7\"）后重试。"
)


class CalculatorPlugin(PluginBase):
    settings_cards = True

    def __init__(self, context) -> None:
        super().__init__(context)
        self._external: ExternalCalculatorWindow | None = None

    def create_ui(self, window: tk.Toplevel) -> None:
        if not qt_available():
            raise RuntimeError(_QT_REQUIRED_MESSAGE)
        external = ExternalCalculatorWindow(window, self.context.data_dir)
        try:
            started = external.start()
        except Exception as exc:
            log.exception("启动 PyQt 计算器界面失败")
            try:
                external.close()
            except Exception:
                log.debug("清理启动失败的计算器进程失败", exc_info=True)
            raise RuntimeError("无法启动计算器界面，请查看日志。") from exc
        if not started:
            try:
                external.close()
            except Exception:
                log.debug("清理启动失败的计算器进程失败", exc_info=True)
            raise RuntimeError("无法启动计算器界面，请查看日志。")
        self._external = external
        log.info("计算器使用 PyQt 独立窗口")

    def on_window_shown(self, window: tk.Toplevel) -> None:
        # The launcher hides plugin windows instead of destroying them, so a
        # re-entry must show the Qt window and focus a fresh input row.
        if self._external is not None:
            self._external.show()

    def create_settings_ui(self, parent: tk.Misc) -> None:
        from quicktools.settings_widgets import Card
        from quicktools.ui_theme import CARD_BG, TEXT

        card = Card(parent)
        card.pack(fill="x")
        tk.Label(
            card.body,
            text="计算器使用独立的 PyQt 窗口，请在计算器窗口顶部的齿轮按钮中打开设置。",
            bg=CARD_BG,
            fg=TEXT,
            font=("TkDefaultFont", 10),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")
