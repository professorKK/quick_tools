"""gp 悬浮窗的 Qt 场景，在独立子进程里运行。

在 pytest 主进程创建 QApplication 会改变 fontconfig 的当前配置，导致随后的
Tk 测试读不到内置 Material Icons 字体。生产程序里 Tk 与 Qt 本来就分属两个
进程，测试也照此办理：``test_gp_qt_window.py`` 用用例名启动本文件。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    # 离屏平台不支持窗口透明度与 raise()，没有显示环境时只能退而求其次。
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QContextMenuEvent, QEnterEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from quicktools.plugins.gp import qt_widget as qt_widget_module
from quicktools.plugins.gp.geometry import Rect, ScreenArea, screen_for_rect
from quicktools.plugins.gp.qt_helper import GpController, configure_application
from quicktools.plugins.gp.qt_screens import rect_for, screen_areas
from quicktools.plugins.gp.qt_settings import read_plugin_info
from quicktools.plugins.gp.qt_widget import FloatingWidget
from quicktools.plugins.gp.settings import GpSettings, load_settings

_app = QApplication([])

_SHIFT = Qt.KeyboardModifier.ShiftModifier
_NO_MOD = Qt.KeyboardModifier.NoModifier
_LEFT = Qt.MouseButton.LeftButton
_NO_BUTTON = Qt.MouseButton.NoButton
_NO_BUTTONS = Qt.MouseButton.NoButton


def _process() -> None:
    _app.processEvents()


class _FakeApp:
    """Stand-in for QApplication so quit() does not stop the test process."""

    def __init__(self) -> None:
        self.quit_called = False

    def quit(self) -> None:
        self.quit_called = True


def _new_widget(settings: GpSettings | None = None):
    events: list[str] = []
    saved: list[GpSettings] = []
    opened: list[bool] = []
    quit_calls: list[bool] = []
    widget = FloatingWidget(
        settings or GpSettings(),
        on_open_settings=lambda: opened.append(True),
        on_exit=lambda: quit_calls.append(True),
        emit=events.append,
        persist=saved.append,
    )
    return widget, events, saved, opened, quit_calls


def _new_controller(
    data_dir: Path, settings: GpSettings | None = None
):
    app = _FakeApp()
    controller = GpController(
        app, data_dir, None, settings or GpSettings()
    )
    return controller, app


def _mouse(
    kind: QEvent.Type,
    local: QPoint,
    global_pos: QPoint,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
    modifiers: Qt.KeyboardModifier,
) -> QMouseEvent:
    return QMouseEvent(
        kind,
        QPointF(local),
        QPointF(global_pos),
        button,
        buttons,
        modifiers,
    )


def _drag(
    widget: FloatingWidget,
    start: QPoint,
    target: QPoint,
    *,
    press_modifiers: Qt.KeyboardModifier = _SHIFT,
    move_modifiers: Qt.KeyboardModifier = _NO_MOD,
    release_modifiers: Qt.KeyboardModifier = _NO_MOD,
) -> None:
    """Drive a drag with explicit global coordinates.

    The widget records the offset as ``global - pos()``; we press at the
    widget's local (20, 20), so the target global position is ``target+20``.
    """
    local_press = QPoint(20, 20)
    widget.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            local_press,
            start + local_press,
            _LEFT,
            _LEFT,
            press_modifiers,
        )
    )
    global_move = target + local_press
    widget.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove,
            QPoint(80, 80),
            global_move,
            _NO_BUTTON,
            _LEFT,
            move_modifiers,
        )
    )
    widget.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease,
            QPoint(80, 80),
            global_move,
            _LEFT,
            _NO_BUTTONS,
            release_modifiers,
        )
    )
    _process()


def case_defaults() -> None:
    widget, _, _, _, _ = _new_widget()
    assert widget.width() == 120
    assert widget.height() == 120
    assert abs(widget.windowOpacity() - 0.5) < 0.02
    flags = widget.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool
    assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert widget.settings.fill_background is False


def case_transparent_background() -> None:
    """背景色关闭：圆形外角完全透明，圆环与文字不透明。"""
    widget, _, _, _, _ = _new_widget()
    widget.show()
    _process()
    QTest.qWait(100)
    image = widget.grab().toImage()
    assert image.hasAlphaChannel()
    corner = image.pixelColor(1, 1).alpha()
    ring = image.pixelColor(widget.width() // 2, 4).alpha()
    assert corner == 0, f"圆形外的角应当完全透明，实际 alpha={corner}"
    assert ring > 0, f"圆环应当可见，实际 alpha={ring}"


def case_hover_opacity() -> None:
    widget, _, _, _, _ = _new_widget()
    widget.show()
    _process()
    widget.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert abs(widget.windowOpacity() - 1.0) < 0.02
    widget.leaveEvent(QEvent(QEvent.Type.Leave))
    assert abs(widget.windowOpacity() - 0.5) < 0.02


def case_commands() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, app = _new_controller(data_dir)
    widget = controller._widget
    controller.show()
    _process()
    assert widget.isVisible()
    controller.handle_command("hide")
    _process()
    assert not widget.isVisible()
    controller.handle_command("show")
    _process()
    assert widget.isVisible()
    # 坏命令与未知命令都不能让进程崩掉。
    controller.handle_command("nonsense")
    controller.handle_command("")
    assert not app.quit_called
    controller.handle_command("quit")
    assert app.quit_called


def case_drag_requires_shift() -> None:
    widget, events, saved, _, _ = _new_widget()
    widget.show()
    # 窗口管理器会异步摆放无边框窗口，先等它稳定再记录起始位置。
    QTest.qWait(400)
    _process()
    start = widget.pos()

    target = start + QPoint(60, 60)
    _drag(
        widget,
        start,
        target,
        press_modifiers=_NO_MOD,
        move_modifiers=_NO_MOD,
        release_modifiers=_NO_MOD,
    )
    assert widget.pos() == start
    assert events == []
    assert saved == []

    _drag(widget, start, target)
    assert widget.pos() != start
    assert any(event.startswith("position ") for event in events)
    # 松手即保存位置。
    assert saved and saved[-1].x == widget.x() and saved[-1].y == widget.y()


def case_drag_shift_released_midway() -> None:
    widget, events, saved, _, _ = _new_widget()
    widget.show()
    QTest.qWait(400)
    _process()
    start = widget.pos()
    target = start + QPoint(40, 50)
    # 按下时按住 Shift，移动/释放时不按：仍然完成拖动。
    _drag(widget, start, target)
    assert widget.pos() == target
    assert saved
    assert any(event.startswith("position ") for event in events)


def case_drag_clamps_and_saves() -> None:
    widget, events, saved, _, _ = _new_widget()
    widget.show()
    QTest.qWait(400)
    _process()
    # 模拟拖到远离所有显示器的位置后松手。
    widget.move(QPoint(-5000, -5000))
    _process()
    widget._finish_drag()
    _process()
    rect = rect_for(widget)
    area = screen_for_rect(rect, screen_areas())
    assert area is not None
    assert rect.x >= area.x
    assert rect.y >= area.y
    assert rect.right <= area.right
    assert rect.bottom <= area.bottom
    assert saved and saved[-1].screen == area.name
    assert any(event.startswith("position ") for event in events)


def case_position_persists_via_controller() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(400)
    _process()
    widget = controller._widget
    start = widget.pos()
    target = start + QPoint(30, 20)
    _drag(widget, start, target)
    controller.flush()

    stored = load_settings(data_dir)
    assert stored.x == widget.x()
    assert stored.y == widget.y()
    area = screen_for_rect(rect_for(widget), screen_areas())
    assert area is not None
    assert stored.screen == (area.name or None)

    # 隐藏后把窗口挪到别处，再次 show 必须回到保存的位置。
    saved_pos = widget.pos()
    widget.hide()
    _process()
    widget.move(saved_pos + QPoint(200, 100))
    _process()
    controller.show()
    _process()
    assert widget.pos() == saved_pos


def case_fallback_does_not_overwrite_saved_position() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    saved = GpSettings(x=100000, y=100000, screen="__missing_display__")
    controller, _ = _new_controller(data_dir, saved)
    controller.show()
    _process()
    widget = controller._widget

    rect = rect_for(widget)
    area = screen_for_rect(rect, screen_areas())
    assert area is not None
    # 显示到最近屏幕并完整可见……
    assert rect.x >= area.x
    assert rect.y >= area.y
    assert rect.right <= area.right
    assert rect.bottom <= area.bottom

    # ……但自动回退不能覆盖用户保存的屏幕和坐标。
    controller.flush()
    stored = load_settings(data_dir)
    assert stored.x == 100000
    assert stored.y == 100000
    assert stored.screen == "__missing_display__"


def case_drag_across_screens() -> None:
    areas = screen_areas()
    if len(areas) < 2:
        print("single screen: skipped")
        return
    widget, _, saved, _, _ = _new_widget()
    widget.show()
    QTest.qWait(400)
    _process()
    target_area = areas[1]
    widget.move(QPoint(target_area.x + 100, target_area.y + 100))
    _process()
    widget._finish_drag()
    _process()
    assert saved
    assert saved[-1].screen == target_area.name


class _FakeAction:
    """Mimics QAction closely enough for identity comparisons."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMenu:
    """Stand-in for QMenu so the context menu can be driven in tests."""

    chosen_text = "设置"
    on_exec: Callable[[], None] | None = None

    def __init__(self, parent=None) -> None:
        self.actions: list[_FakeAction] = []

    def addAction(self, text: str) -> _FakeAction:
        action = _FakeAction(text)
        self.actions.append(action)
        return action

    def exec(self, pos=None) -> _FakeAction | None:
        if _FakeMenu.on_exec is not None:
            _FakeMenu.on_exec()
        for action in self.actions:
            if action.text == _FakeMenu.chosen_text:
                return action
        return None


def _context_menu_event() -> QContextMenuEvent:
    return QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse,
        QPoint(10, 10),
        QPoint(10, 10),
    )


def case_context_menu() -> None:
    original = qt_widget_module.QMenu
    qt_widget_module.QMenu = _FakeMenu
    try:
        widget, events, _, opened, quit_calls = _new_widget()
        widget.show()
        _process()

        _FakeMenu.chosen_text = "设置"
        widget.contextMenuEvent(_context_menu_event())
        # 设置通过 0ms 定时器在菜单退出后打开。
        QTest.qWait(50)
        _process()
        assert opened == [True]
        assert events == []

        _FakeMenu.chosen_text = "退出"
        widget.contextMenuEvent(_context_menu_event())
        assert events == ["closed"]
        assert quit_calls == [True]
        _process()
        assert not widget.isVisible()
    finally:
        qt_widget_module.QMenu = original


def case_context_menu_exit_quits_helper() -> None:
    """右键“退出”必须结束 helper，而不是只把悬浮窗藏起来。"""
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, fake_app = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    controller.open_settings()
    _process()
    dialog = controller._dialog
    widget = controller._widget
    assert dialog is not None and dialog.isVisible()

    original = qt_widget_module.QMenu
    qt_widget_module.QMenu = _FakeMenu
    try:
        _FakeMenu.chosen_text = "退出"
        widget.contextMenuEvent(_context_menu_event())
        _process()
    finally:
        qt_widget_module.QMenu = original

    assert fake_app.quit_called is True
    assert not widget.isVisible()
    assert not dialog.isVisible()


def case_settings_dialog_single_instance_and_placement() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(400)
    _process()
    widget = controller._widget
    before = widget.pos()

    controller.open_settings()
    _process()
    dialog = controller._dialog
    assert dialog is not None
    # 不能挂在圆形悬浮窗上，否则窗口管理器会把它摆到屏幕外。
    assert dialog.parent() is None
    assert dialog.isVisible()
    assert dialog.width() >= 380
    # 设置页不再提供底部“关闭”按钮，关闭使用标题栏 X 或 Esc。
    assert not any(
        button.text() == "关闭"
        for button in dialog.findChildren(QPushButton)
    ), "设置对话框不应再有底部关闭按钮"

    rect = rect_for(dialog)
    area = screen_for_rect(rect_for(widget), screen_areas())
    assert area is not None
    assert rect.x >= area.x
    assert rect.y >= area.y
    if rect.width <= area.width:
        assert rect.right <= area.right
    if rect.height <= area.height:
        assert rect.bottom <= area.bottom

    # 重复打开必须复用同一个对话框，并且不能移动悬浮窗。
    first = controller._dialog
    controller.open_settings()
    _process()
    assert controller._dialog is first
    assert widget.pos() == before
    dialog.close()
    _process()


def case_context_menu_keeps_hover_opacity() -> None:
    """右键菜单弹出/关闭期间不能把悬停透明度降到未聚焦状态。"""
    original = qt_widget_module.QMenu
    qt_widget_module.QMenu = _FakeMenu
    try:
        widget, _, _, opened, _ = _new_widget()
        widget.show()
        _process()
        widget.enterEvent(
            QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))
        )
        assert abs(widget.windowOpacity() - 1.0) < 0.02

        # 真实坐标判定：鼠标在窗口矩形内/外。
        original_cursor = qt_widget_module.QCursor

        class _FakeCursor:
            point = QPoint(0, 0)

            @classmethod
            def pos(cls):
                return cls.point

        qt_widget_module.QCursor = _FakeCursor
        try:
            widget.move(QPoint(200, 200))
            _process()
            _FakeCursor.point = QPoint(widget.x() + 10, widget.y() + 10)
            assert FloatingWidget._cursor_inside(widget) is True
            _FakeCursor.point = QPoint(widget.x() - 50, widget.y() - 50)
            assert FloatingWidget._cursor_inside(widget) is False
        finally:
            qt_widget_module.QCursor = original_cursor

        # 鼠标仍在悬浮窗上；模拟菜单弹出导致 leaveEvent。
        widget._cursor_inside = lambda: True
        during_menu: list[float] = []

        def hook() -> None:
            widget.leaveEvent(QEvent(QEvent.Type.Leave))
            during_menu.append(widget.windowOpacity())

        _FakeMenu.on_exec = hook
        _FakeMenu.chosen_text = "设置"
        widget.contextMenuEvent(_context_menu_event())
        QTest.qWait(50)
        _process()
        assert during_menu == [1.0], during_menu
        assert abs(widget.windowOpacity() - 1.0) < 0.02
        assert opened == [True]

        # 菜单关闭时鼠标已经离开悬浮窗，才恢复未聚焦透明度。
        widget._cursor_inside = lambda: False
        widget.contextMenuEvent(_context_menu_event())
        QTest.qWait(50)
        _process()
        assert abs(widget.windowOpacity() - 0.5) < 0.02
    finally:
        _FakeMenu.on_exec = None
        qt_widget_module.QMenu = original


def case_diameter_slider_sync() -> None:
    """直径滑块 10–120 与手动输入 0–200 联动。"""
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    controller.open_settings()
    _process()
    dialog = controller._dialog
    widget = controller._widget
    assert dialog is not None

    dialog._diameter_slider.setValue(80)
    QTest.qWait(100)
    _process()
    assert dialog._diameter_spin.value() == 80
    assert widget.settings.diameter == 80
    assert widget.width() == 80

    dialog._diameter_spin.setValue(300)
    QTest.qWait(100)
    _process()
    assert dialog._diameter_slider.value() == 250
    assert widget.settings.diameter == 300
    assert widget.width() == 300

    dialog._diameter_spin.setValue(0)
    QTest.qWait(100)
    _process()
    assert dialog._diameter_slider.value() == 10
    assert widget.settings.diameter == 0
    # 0 直径仍保留非零可点击区域；窗口管理器可能把极小窗口抬到它的
    # 最小尺寸，因此这里只要求小于上一步，不强制恰好 10px。
    assert 10 <= widget.width() < 300

    dialog._diameter_spin.setValue(1000)
    QTest.qWait(100)
    _process()
    assert dialog._diameter_slider.value() == 250
    assert widget.settings.diameter == 1000
    assert widget.width() == 1000

    controller.flush()
    assert load_settings(data_dir).diameter == 1000
    dialog.close()
    _process()


def case_settings_dialog_stays_put_when_changed() -> None:
    """用户拖动设置对话框后，调整选项不能把它移回原位。"""
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    controller.open_settings()
    _process()
    dialog = controller._dialog
    assert dialog is not None
    area = screen_for_rect(rect_for(controller._widget), screen_areas())
    assert area is not None

    dialog.move(QPoint(area.x + 80, area.y + 80))
    # 窗口管理器会异步落位（标题栏 frame 可能让客户区偏移几十像素），
    # 等位置稳定后再记录基准。
    QTest.qWait(300)
    _process()
    moved_to = dialog.pos()

    # 改透明度不能触发重新摆放。
    dialog._idle_slider.setValue(70)
    QTest.qWait(150)
    _process()
    assert dialog.pos() == moved_to

    # 改直径可能移动悬浮窗，但对话框必须留在用户放的位置。
    dialog._diameter_spin.setValue(180)
    QTest.qWait(150)
    _process()
    assert dialog.pos() == moved_to

    # 恢复默认位置只移动悬浮窗，不移动对话框。
    controller._on_reset_position()
    QTest.qWait(150)
    _process()
    assert dialog.pos() == moved_to
    dialog.close()
    _process()


def case_closing_settings_does_not_quit() -> None:
    """关闭设置对话框不能退出 helper（悬浮窗是 Tool，不参与主窗口判定）。"""
    configure_application(_app)
    assert _app.quitOnLastWindowClosed() is False

    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    controller.open_settings()
    _process()
    dialog = controller._dialog
    widget = controller._widget
    assert dialog is not None and dialog.isVisible()

    still_visible: list[bool] = []
    QTimer.singleShot(100, dialog.close)
    QTimer.singleShot(650, lambda: still_visible.append(widget.isVisible()))
    QTimer.singleShot(700, _app.quit)
    start = time.monotonic()
    _app.exec()
    elapsed = time.monotonic() - start

    # 没有 setQuitOnLastWindowClosed(False) 时，关闭对话框会让 exec() 在
    # 100ms 左右直接返回；修复后必须由 700ms 的定时器正常结束事件循环。
    assert elapsed >= 0.5, (
        f"关闭设置对话框后 helper 提前退出：{elapsed:.2f}s"
    )
    assert still_visible == [True], "关闭设置对话框后悬浮窗不应消失"


def case_settings_dialog_flips_at_left_edge() -> None:
    """左侧没有空间时，对话框必须翻到悬浮窗右侧且不超出屏幕。"""
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    _process()
    widget = controller._widget
    area = screen_for_rect(rect_for(widget), screen_areas())
    assert area is not None
    widget.move(QPoint(area.x + 4, area.center_y))
    _process()

    controller.open_settings()
    _process()
    dialog = controller._dialog
    assert dialog is not None and dialog.isVisible()
    # 左侧放不下，必须翻到右侧。
    assert dialog.x() >= widget.x() + widget.width()
    rect = rect_for(dialog)
    assert rect.x >= area.x
    assert rect.right <= area.right
    assert rect.y >= area.y
    assert rect.bottom <= area.bottom
    dialog.close()
    _process()


def case_settings_dialog_auto_saves() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    controller.open_settings()
    _process()
    dialog = controller._dialog
    widget = controller._widget
    assert dialog is not None

    dialog._idle_slider.setValue(30)
    dialog._active_slider.setValue(80)
    dialog._diameter_spin.setValue(150)
    dialog._fill_check.setChecked(True)
    _process()

    assert abs(widget.settings.idle_opacity - 0.3) < 1e-6
    assert abs(widget.settings.active_opacity - 0.8) < 1e-6
    assert widget.width() == 150
    # 手动值 150 在滑块范围内，滑块同步到 150。
    assert dialog._diameter_slider.value() == 150
    assert widget.settings.fill_background is True

    controller.flush()
    stored = load_settings(data_dir)
    assert abs(stored.idle_opacity - 0.3) < 1e-6
    assert abs(stored.active_opacity - 0.8) < 1e-6
    assert stored.diameter == 150
    assert stored.fill_background is True

    dialog.close()
    _process()
    # 重新打开时控件值必须恢复为已保存的设置。
    controller.open_settings()
    _process()
    assert dialog._idle_slider.value() == 30
    assert dialog._active_slider.value() == 80
    assert dialog._diameter_spin.value() == 150
    assert dialog._diameter_slider.value() == 150
    assert dialog._fill_check.isChecked() is True
    dialog.close()
    _process()


def case_settings_dialog_reset_position() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-gp-"))
    controller, _ = _new_controller(data_dir)
    controller.show()
    QTest.qWait(300)
    widget = controller._widget
    # 先制造一个非默认位置。
    widget.move(widget.pos() + QPoint(80, 60))
    _process()
    widget._finish_drag()
    _process()
    assert widget.settings.x is not None
    assert widget.settings.y is not None

    controller.open_settings()
    _process()
    controller._on_reset_position()
    _process()
    assert widget.settings.x is None
    assert widget.settings.y is None
    assert widget.settings.screen is None
    stored = load_settings(data_dir)
    assert stored.x is None
    assert stored.y is None
    assert stored.screen is None
    controller._dialog.close()
    _process()


def case_diameter_change_keeps_reachable() -> None:
    widget, _, _, _, _ = _new_widget()
    widget.show()
    QTest.qWait(300)
    _process()
    widget.apply_appearance(GpSettings(diameter=250))
    _process()
    rect = rect_for(widget)
    area = screen_for_rect(rect, screen_areas())
    assert area is not None
    assert rect.x >= area.x
    assert rect.y >= area.y
    assert rect.right <= area.right
    assert rect.bottom <= area.bottom
    assert widget.width() == 250


_CASES = {
    "defaults": case_defaults,
    "transparent_background": case_transparent_background,
    "hover_opacity": case_hover_opacity,
    "commands": case_commands,
    "drag_requires_shift": case_drag_requires_shift,
    "drag_shift_released_midway": case_drag_shift_released_midway,
    "drag_clamps_and_saves": case_drag_clamps_and_saves,
    "position_persists_via_controller": case_position_persists_via_controller,
    "fallback_does_not_overwrite_saved_position": (
        case_fallback_does_not_overwrite_saved_position
    ),
    "drag_across_screens": case_drag_across_screens,
    "context_menu": case_context_menu,
    "settings_dialog_single_instance_and_placement": (
        case_settings_dialog_single_instance_and_placement
    ),
    "context_menu_keeps_hover_opacity": (
        case_context_menu_keeps_hover_opacity
    ),
    "context_menu_exit_quits_helper": case_context_menu_exit_quits_helper,
    "diameter_slider_sync": case_diameter_slider_sync,
    "settings_dialog_stays_put_when_changed": (
        case_settings_dialog_stays_put_when_changed
    ),
    "closing_settings_does_not_quit": case_closing_settings_does_not_quit,
    "settings_dialog_flips_at_left_edge": (
        case_settings_dialog_flips_at_left_edge
    ),
    "settings_dialog_auto_saves": case_settings_dialog_auto_saves,
    "settings_dialog_reset_position": case_settings_dialog_reset_position,
    "diameter_change_keeps_reachable": case_diameter_change_keeps_reachable,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _CASES:
        print(f"unknown case: {argv}", file=sys.stderr)
        return 2
    try:
        _CASES[argv[0]]()
    except Exception:
        traceback.print_exc()
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
