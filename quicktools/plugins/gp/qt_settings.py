"""gp 悬浮窗的 PyQt 设置对话框。

设置界面完全在 Qt 侧：修改即生效，控制器做一次防抖落盘，没有“保存设置”
按钮。对话框**不设父窗口**：把无边框圆形悬浮窗当父级会被窗口管理器摆到
屏幕外，定位由控制器在 ``adjustSize()`` 之后显式计算。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from .settings import (
    GpSettings,
    MAX_DIAMETER,
    MAX_OPACITY,
    MIN_DIAMETER,
    MIN_OPACITY,
    SLIDER_MAX_DIAMETER,
    SLIDER_MIN_DIAMETER,
)

_QSS = """
QWidget {
    color: #1f2937;
    font-family: "Noto Sans CJK SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel#Title {
    font-size: 15px;
    font-weight: 600;
}
QLabel#Subtitle {
    color: #6b7280;
    font-size: 11px;
}
QGroupBox {
    border: 1px solid #e4e8ef;
    border-radius: 10px;
    margin-top: 10px;
    padding: 10px 12px 12px 12px;
    background: #f6f7f9;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: #6b7280;
    font-size: 11px;
}
QPushButton {
    background: #f1f3f5;
    border: 1px solid #d8dde5;
    border-radius: 8px;
    padding: 6px 14px;
}
QPushButton:hover { background: #e6e9ee; }
QSlider::groove:horizontal {
    height: 4px;
    background: #d8dde5;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #2563eb;
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
}
"""


@dataclass(frozen=True)
class PluginInfo:
    """Manifest information shown in the About block."""

    name: str = "gp插件"
    version: str = ""
    author: str = ""
    description: str = ""
    folder: str = ""


def read_plugin_info(plugin_dir: Path | None) -> PluginInfo:
    """Read ``plugin.json`` so the dialog can show the About block."""
    if plugin_dir is None:
        return PluginInfo()
    manifest = Path(plugin_dir) / "plugin.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PluginInfo(folder=str(plugin_dir))
    if not isinstance(raw, dict):
        return PluginInfo(folder=str(plugin_dir))

    def text(key: str) -> str:
        value = raw.get(key)
        return value.strip() if isinstance(value, str) else ""

    return PluginInfo(
        name=text("name") or "gp插件",
        version=text("version"),
        author=text("author"),
        description=text("description"),
        folder=str(plugin_dir),
    )


class SettingsDialog(QDialog):
    """Non-modal settings window; changes are emitted and applied at once."""

    appearanceChanged = pyqtSignal(object)
    resetPositionRequested = pyqtSignal()

    def __init__(
        self,
        info: PluginInfo,
        data_dir: Path,
        *,
        current_settings: Callable[[], GpSettings],
    ) -> None:
        super().__init__(None)
        self._info = info
        self._data_dir = Path(data_dir)
        self._current_settings = current_settings
        self._loading = False
        self.setWindowTitle("gp 插件设置")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumWidth(380)
        self.setStyleSheet(_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        title = QLabel("gp 插件设置", self)
        title.setObjectName("Title")
        layout.addWidget(title)

        layout.addWidget(self._build_appearance())
        layout.addWidget(self._build_position())
        layout.addWidget(self._build_about())

        hint = QLabel("修改会自动保存并立即生效。", self)
        hint.setObjectName("Subtitle")
        layout.addWidget(hint)

    # -------------------------------------------------------------- 界面
    def _build_appearance(self) -> QGroupBox:
        group = QGroupBox("外观", self)
        form = QFormLayout(group)
        form.setContentsMargins(0, 4, 0, 0)
        form.setSpacing(8)

        self._idle_slider = QSlider(Qt.Orientation.Horizontal, group)
        self._idle_slider.setRange(
            int(MIN_OPACITY * 100), int(MAX_OPACITY * 100)
        )
        self._idle_value = QLabel("", group)
        self._idle_value.setObjectName("Subtitle")
        idle_row = QHBoxLayout()
        idle_row.addWidget(self._idle_slider, 1)
        idle_row.addWidget(self._idle_value)
        form.addRow("未聚焦透明度", idle_row)

        self._active_slider = QSlider(Qt.Orientation.Horizontal, group)
        self._active_slider.setRange(
            int(MIN_OPACITY * 100), int(MAX_OPACITY * 100)
        )
        self._active_value = QLabel("", group)
        self._active_value.setObjectName("Subtitle")
        active_row = QHBoxLayout()
        active_row.addWidget(self._active_slider, 1)
        active_row.addWidget(self._active_value)
        form.addRow("悬停透明度", active_row)

        self._diameter_slider = QSlider(Qt.Orientation.Horizontal, group)
        self._diameter_slider.setRange(
            SLIDER_MIN_DIAMETER, SLIDER_MAX_DIAMETER
        )
        self._diameter_slider.setSingleStep(1)
        self._diameter_slider.setPageStep(10)
        self._diameter_spin = QSpinBox(group)
        self._diameter_spin.setRange(MIN_DIAMETER, MAX_DIAMETER)
        diameter_row = QHBoxLayout()
        diameter_row.addWidget(self._diameter_slider, 1)
        diameter_row.addWidget(self._diameter_spin)
        form.addRow("悬浮窗直径", diameter_row)

        self._fill_check = QCheckBox("填充圆圈背景色", group)
        form.addRow("", self._fill_check)

        self._idle_slider.valueChanged.connect(self._on_slider_changed)
        self._active_slider.valueChanged.connect(self._on_slider_changed)
        self._diameter_slider.valueChanged.connect(
            self._on_diameter_slider
        )
        self._diameter_spin.valueChanged.connect(self._on_diameter_spin)
        self._fill_check.toggled.connect(self._changed)
        return group

    def _build_position(self) -> QGroupBox:
        group = QGroupBox("位置", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)
        hint = QLabel(
            "按住 Shift 再左键拖动悬浮窗可以移动它，位置会自动记住。",
            group,
        )
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        reset_button = QPushButton("恢复右下角默认位置", group)
        reset_button.clicked.connect(self.resetPositionRequested.emit)
        layout.addWidget(reset_button, 0, Qt.AlignmentFlag.AlignLeft)
        return group

    def _build_about(self) -> QGroupBox:
        group = QGroupBox("关于", self)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        title = QLabel(self._info.name, group)
        title.setObjectName("Title")
        layout.addWidget(title)
        meta = QLabel(
            "版本 {} · 作者 {}".format(
                self._info.version or "未知",
                self._info.author or "未提供",
            ),
            group,
        )
        meta.setObjectName("Subtitle")
        layout.addWidget(meta)
        if self._info.description:
            description = QLabel(self._info.description, group)
            description.setObjectName("Subtitle")
            description.setWordWrap(True)
            layout.addWidget(description)
        data_label = QLabel(f"数据目录：{self._data_dir}", group)
        data_label.setObjectName("Subtitle")
        data_label.setWordWrap(True)
        layout.addWidget(data_label)
        return group

    # -------------------------------------------------------------- 行为
    @staticmethod
    def _percent(value: int) -> str:
        return f"{value}%"

    def set_settings(self, settings: GpSettings) -> None:
        """Refresh the controls without emitting change signals."""
        normalized = settings.normalized()
        self._loading = True
        try:
            self._idle_slider.setValue(
                int(round(normalized.idle_opacity * 100))
            )
            self._active_slider.setValue(
                int(round(normalized.active_opacity * 100))
            )
            self._diameter_spin.setValue(normalized.diameter)
            self._diameter_slider.setValue(
                max(
                    SLIDER_MIN_DIAMETER,
                    min(SLIDER_MAX_DIAMETER, normalized.diameter),
                )
            )
            self._fill_check.setChecked(normalized.fill_background)
            self._idle_value.setText(
                self._percent(self._idle_slider.value())
            )
            self._active_value.setText(
                self._percent(self._active_slider.value())
            )
        finally:
            self._loading = False

    def _on_slider_changed(self, value: int) -> None:
        # 两个透明度滑块共用回调，按发送者更新对应数值。
        if self.sender() is self._active_slider:
            self._active_value.setText(self._percent(value))
        else:
            self._idle_value.setText(self._percent(value))
        self._changed()

    def _on_diameter_slider(self, value: int) -> None:
        if self._loading:
            return
        # 滑块覆盖常用范围；同时把数值同步到手写输入框。
        self._loading = True
        try:
            self._diameter_spin.setValue(value)
        finally:
            self._loading = False
        self._changed()

    def _on_diameter_spin(self, value: int) -> None:
        if self._loading:
            return
        # 手写输入允许 0–1000；滑块只显示 10–250，超出时停在端点。
        self._loading = True
        try:
            self._diameter_slider.setValue(
                max(SLIDER_MIN_DIAMETER, min(SLIDER_MAX_DIAMETER, value))
            )
        finally:
            self._loading = False
        self._changed()

    def _current(self) -> GpSettings:
        base = self._current_settings()
        return GpSettings(
            idle_opacity=self._idle_slider.value() / 100.0,
            active_opacity=self._active_slider.value() / 100.0,
            diameter=int(self._diameter_spin.value()),
            text=base.text,
            fill_background=bool(self._fill_check.isChecked()),
            x=base.x,
            y=base.y,
            screen=base.screen,
        )

    def _changed(self, *_args) -> None:
        if self._loading:
            return
        self.appearanceChanged.emit(self._current())
