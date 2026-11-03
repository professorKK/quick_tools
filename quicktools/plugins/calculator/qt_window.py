"""PyQt6 calculator window.

This module runs inside the calculator helper process started by
``qt_host.py``.  The Tk application never imports PyQt6, so the two toolkits
keep separate event loops and native windows.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from quicktools import DISPLAY_NAME, PROJECT_URL, paths
from quicktools.plugins.calculator.engine import (
    BASE_LABELS,
    SUPPORTED_BASES,
    ExpressionError,
    convert_bases,
    evaluate_live,
    filter_input,
    format_result,
    normalize_text,
)
from quicktools.plugins.calculator.scratchpad_store import (
    ScratchEntry,
    ScratchpadState,
    load_scratchpad,
    save_scratchpad,
)
from quicktools.plugins.calculator.settings import (
    MAX_MAX_RECORDS,
    MAX_RESULT_GROUP_SIZE,
    MIN_MAX_RECORDS,
    MIN_RESULT_GROUP_SIZE,
    atomic_write_json,
    load_max_records,
    load_result_group_size,
    load_scientific_mode,
    save_max_records,
    save_result_group_size,
    save_scientific_mode,
)

log = logging.getLogger(__name__)

BG = "#f3f5f9"
CARD = "#ffffff"
PANEL = "#f7f9fc"
BORDER = "#dfe5ee"
TEXT = "#1f2937"
MUTED = "#6b7280"
SUBTLE = "#9aa3af"
ACCENT = "#2563eb"
ACCENT_SOFT = "#eef4ff"
ACCENT_SOFT_HOVER = "#dbeafe"
SUCCESS = "#15803d"
DANGER = "#c5221f"

_WINDOW_STATE_FILE = "qt_window.json"
_SAVE_DEBOUNCE_MS = 400
_AUTO_HIDE_DELAY_MS = 260
_DEFAULT_SIZE = (660, 740)
_MIN_SIZE = (560, 600)

_ICON_CODEPOINTS = {
    "settings": "\ue8b8",
    "pin": "\uf10d",
    "minimize": "\ue15b",
    "maximize": "\ue5d0",
    "restore": "\uf1cf",
    "close": "\ue5cd",
    "copy": "\ue14d",
    "delete": "\ue872",
}

_QSS = f"""
QWidget {{
    color: {TEXT};
    font-family: "Noto Sans CJK SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QFrame#Card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 15px;
}}
QWidget#TitleBar {{
    background: transparent;
    border: none;
}}
QLabel#Title {{
    font-size: 14px;
    font-weight: 600;
}}
QLabel#Subtitle {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#Badge {{
    background: {ACCENT};
    color: #ffffff;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 700;
}}
QToolButton#TitleButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {MUTED};
    padding: 0;
}}
QToolButton#TitleButton:hover {{
    background: #e8eef7;
    color: {TEXT};
}}
QToolButton#TitleButton:pressed {{
    background: #dce5f1;
}}
QToolButton#TitleButton:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
QToolButton#CloseButton:hover {{
    background: #fde8e7;
    color: {DANGER};
}}
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 600;
}}
QFrame#PaperCard {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QScrollArea#PaperScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#PaperScroll > QWidget > QWidget {{
    background: transparent;
}}
QFrame#Row {{
    background: {CARD};
    border: none;
    border-radius: 8px;
}}
QFrame#Row[active="true"] {{
    background: {ACCENT_SOFT};
}}
QFrame#RowStripe {{
    background: transparent;
    border-radius: 1px;
}}
QFrame#Row[active="true"] QFrame#RowStripe {{
    background: {ACCENT};
}}
QLineEdit#Expression {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-family: "DejaVu Sans Mono", "Consolas", "Cascadia Mono", monospace;
    font-size: 15px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLabel#Result {{
    color: {ACCENT};
    font-family: "DejaVu Sans Mono", "Consolas", "Cascadia Mono", monospace;
    font-size: 13px;
}}
QLabel#Result[state="error"] {{
    color: {DANGER};
}}
QLabel#Result[state="muted"] {{
    color: {MUTED};
}}
QToolButton#RowDelete {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {DANGER};
    padding: 0;
}}
QToolButton#RowDelete:hover {{
    background: #fde8e7;
}}
QFrame#Conversion {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#ConvCell {{
    background: transparent;
    border-radius: 8px;
}}
QWidget#ConvCell[active="true"] {{
    background: {ACCENT_SOFT};
}}
QLabel#ConvTag {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 600;
}}
QLabel#ConvTag[active="true"] {{
    color: {ACCENT};
}}
QLineEdit#ConvValue {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-family: "DejaVu Sans Mono", "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLabel#BaseLabel {{
    color: {MUTED};
    font-size: 11px;
}}
QPushButton#Base {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {MUTED};
    padding: 6px 10px;
    font-size: 11px;
}}
QPushButton#Base:hover {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
QPushButton#Base:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#Key {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {TEXT};
    font-size: 15px;
    padding: 4px;
}}
QPushButton#Key:hover {{
    background: #f4f7fc;
}}
QPushButton#Key:pressed {{
    background: #e9eef6;
}}
QPushButton#Key:disabled {{
    background: #f7f8fa;
    color: #c3c9d2;
    border-color: #edf0f4;
}}
QPushButton#Key[role="function"] {{
    background: {PANEL};
    color: #4b5563;
    font-size: 12px;
}}
QPushButton#Key[role="function"]:hover {{
    background: #e9eef6;
}}
QPushButton#Key[role="plus"] {{
    background: #fdecea;
    border-color: #f6d5d1;
    color: #b3261e;
    font-size: 18px;
}}
QPushButton#Key[role="plus"]:hover {{
    background: #fad2cf;
}}
QPushButton#Key[role="minus"] {{
    background: #fff7e0;
    border-color: #f5e4b8;
    color: #a16207;
    font-size: 18px;
}}
QPushButton#Key[role="minus"]:hover {{
    background: #feecb3;
}}
QPushButton#Key[role="multiply"] {{
    background: #e6f4ea;
    border-color: #cfe8d8;
    color: #137333;
    font-size: 18px;
}}
QPushButton#Key[role="multiply"]:hover {{
    background: #ceead6;
}}
QPushButton#Key[role="divide"] {{
    background: #e8f0fe;
    border-color: #d2e3fc;
    color: #1a56db;
    font-size: 18px;
}}
QPushButton#Key[role="divide"]:hover {{
    background: #d2e3fc;
}}
QPushButton#Key[role="equals"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-size: 20px;
}}
QPushButton#Key[role="equals"]:hover {{
    background: #3b82f6;
}}
QLabel#Status {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#Status[tone="success"] {{
    color: {SUCCESS};
}}
QLabel#Status[tone="error"] {{
    color: {DANGER};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #cfd6e0;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _icon_family() -> str:
    path = paths.assets_dir() / "fonts" / "MaterialIcons-Regular.ttf"
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        return ""
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else ""


def _glyph_pixmap(family: str, glyph: str, color: str) -> QPixmap:
    """Render a Material Icons glyph like the Tk title bar's 30 px grid."""
    size = 30
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont(family)
    font.setPointSize(18)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(
        QRectF(0, 0, size, size),
        Qt.AlignmentFlag.AlignCenter,
        glyph,
    )
    painter.end()
    return pixmap


def _glyph_icon(family: str, glyph: str) -> QIcon:
    """Build a QIcon with the same idle/hover/checked colors as Tk."""
    icon = QIcon()
    states = (
        (QIcon.Mode.Normal, QIcon.State.Off, MUTED),
        (QIcon.Mode.Normal, QIcon.State.On, ACCENT),
        (QIcon.Mode.Active, QIcon.State.Off, TEXT),
        (QIcon.Mode.Active, QIcon.State.On, ACCENT),
        (QIcon.Mode.Selected, QIcon.State.Off, TEXT),
        (QIcon.Mode.Selected, QIcon.State.On, ACCENT),
        (QIcon.Mode.Disabled, QIcon.State.Off, SUBTLE),
    )
    for mode, state, color in states:
        icon.addPixmap(_glyph_pixmap(family, glyph, color), mode, state)
    return icon


def _set_x11_topmost(window: QWidget, enabled: bool) -> bool:
    """Set EWMH ``_NET_WM_STATE_ABOVE`` without recreating the window."""
    try:
        from Xlib import X, display, protocol

        connection = display.Display()
        root = connection.screen().root
        state_atom = connection.intern_atom("_NET_WM_STATE")
        above_atom = connection.intern_atom("_NET_WM_STATE_ABOVE")
        target = connection.create_resource_object(
            "window", int(window.winId())
        )
        event = protocol.event.ClientMessage(
            window=target,
            client_type=state_atom,
            data=(32, [1 if enabled else 0, above_atom, 0, 0, 0]),
        )
        root.send_event(
            event,
            event_mask=X.SubstructureRedirectMask
            | X.SubstructureNotifyMask,
        )
        connection.flush()
        connection.close()
        return True
    except Exception:
        log.debug("设置 X11 置顶状态失败", exc_info=True)
        return False


def _set_win32_topmost(window: QWidget, enabled: bool) -> bool:
    """Call SetWindowPos so the frameless window is not recreated."""
    try:
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_bool
        insert_after = ctypes.wintypes.HWND(-1 if enabled else -2)
        user32.SetWindowPos(
            ctypes.wintypes.HWND(int(window.winId())),
            insert_after,
            0,
            0,
            0,
            0,
            0x0001 | 0x0002 | 0x0010,  # NOSIZE | NOMOVE | NOACTIVATE
        )
        return True
    except Exception:
        log.debug("设置 Windows 置顶状态失败", exc_info=True)
        return False


class ClickableLabel(QLabel):
    clicked = pyqtSignal()
    context_requested = pyqtSignal(QPoint)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.context_requested.emit(event.globalPos())


class CalculatorEntry(QLineEdit):
    submitted = pyqtSignal()
    focus_entered = pyqtSignal()
    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submitted.emit()
            return
        if (
            event.text() == "="
            and not event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().focusInEvent(event)
        self.focus_entered.emit()


class Switch(QAbstractButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(44, 24)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 3, 42, 18)
        color = QColor(ACCENT if self.isChecked() else "#cbd3de")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, 9, 9)
        knob_x = 23.0 if self.isChecked() else 3.0
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, 5, 14, 14))
        painter.end()


class ExpressionRow(QFrame):
    """One editable scratchpad row."""

    def __init__(self, window: "CalculatorWindow", base: int = 10) -> None:
        super().__init__(window.paper_inner)
        self.window = window
        self.entry_base = base
        self.result_value: int | float | None = None
        self.result_base: int | None = None
        self.evaluated_expression: str | None = None
        self._suppress = False
        self.active = False

        self.setObjectName("Row")
        self.setProperty("active", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setMinimumHeight(48)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self.stripe = QFrame(self)
        self.stripe.setObjectName("RowStripe")
        self.stripe.setFixedWidth(3)
        self.stripe.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout.addWidget(self.stripe)

        self.entry = CalculatorEntry(self)
        self.entry.setObjectName("Expression")
        self.entry.setPlaceholderText("输入表达式")
        self.entry.setClearButtonEnabled(False)
        self.entry.setFrame(False)
        palette = self.entry.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(SUBTLE))
        self.entry.setPalette(palette)
        layout.addWidget(self.entry, 1)

        self.result_label = ClickableLabel(self)
        self.result_label.setObjectName("Result")
        self.result_label.setProperty("state", "muted")
        self.result_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.result_label.setMinimumWidth(148)
        self.result_label.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.result_label)

        self.delete_button = QToolButton(self)
        self.delete_button.setObjectName("RowDelete")
        self.delete_button.setFixedSize(26, 26)
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setToolTip("删除这一行")
        self.delete_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_button.setFont(
            QFont(window.icon_family, 15) if window.icon_family else QFont()
        )
        self.delete_button.setText(
            _ICON_CODEPOINTS["delete"] if window.icon_family else "×"
        )
        layout.addWidget(self.delete_button)

        self.entry.focus_entered.connect(lambda: self.window.activate_row(self))
        self.entry.clicked.connect(lambda: self.window.select_row(self))
        self.entry.textChanged.connect(self._on_text_changed)
        self.entry.submitted.connect(lambda: self.window.evaluate_row(self))
        self.delete_button.clicked.connect(
            lambda _checked=False: self.window.delete_row(self)
        )
        self.result_label.clicked.connect(self._copy_result)
        self.result_label.context_requested.connect(self._show_context_menu)

    @property
    def expression(self) -> str:
        return self.entry.text()

    def set_active(self, active: bool) -> None:
        if self.active == active:
            return
        self.active = active
        self.setProperty("active", active)
        _repolish(self)
        _repolish(self.stripe)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.select_row(self)
            self.focus_entry()
        super().mousePressEvent(event)

    def restore_expression(self, expression: str) -> None:
        self._suppress = True
        try:
            self.entry.setText(expression)
            self.entry.setCursorPosition(len(expression))
        finally:
            self._suppress = False
        self.clear_result()

    def focus_entry(self, *, move_to_end: bool = True) -> None:
        self.entry.setFocus(Qt.FocusReason.OtherFocusReason)
        if move_to_end:
            self.entry.setCursorPosition(len(self.entry.text()))

    def _on_text_changed(self, _text: str) -> None:
        if self._suppress:
            return
        raw = self.entry.text()
        cursor = self.entry.cursorPosition()
        normalized = normalize_text(raw)
        filtered = filter_input(normalized, self.window.base)
        if filtered != raw:
            new_cursor = len(
                filter_input(normalized[:cursor], self.window.base)
            )
            self._suppress = True
            try:
                self.entry.setText(filtered)
                self.entry.setCursorPosition(min(new_cursor, len(filtered)))
            finally:
                self._suppress = False
            raw = filtered
        self.entry_base = self.window.base
        if (
            self.evaluated_expression is not None
            and raw != self.evaluated_expression
        ):
            self.clear_result()
        self.window.on_row_text_changed(self)

    def set_result(self, value: int | float, base: int, formatted: str) -> None:
        self.result_value = value
        self.result_base = base
        self.evaluated_expression = self.entry.text()
        self.result_label.setText(f"= {formatted}")
        self.result_label.setProperty("state", "normal")
        _repolish(self.result_label)

    def set_error(self, message: str = "错误") -> None:
        self.result_value = None
        self.result_base = None
        self.evaluated_expression = None
        self.result_label.setText(message)
        self.result_label.setProperty("state", "error")
        _repolish(self.result_label)

    def clear_result(self) -> None:
        self.result_value = None
        self.result_base = None
        self.evaluated_expression = None
        self.result_label.setText("")
        self.result_label.setProperty("state", "muted")
        _repolish(self.result_label)

    def clear_all(self) -> None:
        self._suppress = True
        try:
            self.entry.clear()
            self.entry.setCursorPosition(0)
        finally:
            self._suppress = False
        self.clear_result()
        self.window.on_row_text_changed(self)

    def full_expression_text(self) -> str:
        if self.result_value is None or self.result_base is None:
            return ""
        try:
            formatted = format_result(
                self.result_value,
                self.result_base,
                self.window.result_group_size,
            )
        except Exception:
            log.exception("计算器结果格式化失败")
            return ""
        return f"{self.expression.strip()}={formatted}"

    def _copy_result(self) -> None:
        if self.result_value is None or self.result_base is None:
            self.focus_entry()
            return
        try:
            text = format_result(
                self.result_value,
                self.result_base,
                self.window.result_group_size,
            )
        except Exception:
            log.exception("计算器结果格式化失败")
            self.window.set_status("结果过大，无法复制", error=True)
            return
        QApplication.clipboard().setText(text)
        self.window.set_status(f"已复制结果：{text}", success=True)

    def _copy_full_expression(self) -> None:
        text = self.full_expression_text()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.window.set_status(f"已复制完整算式：{text}", success=True)

    def _show_context_menu(self, pos: QPoint) -> None:
        if self.result_value is None or self.result_base is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background: {CARD};
                border: 1px solid {BORDER};
                padding: 6px;
                border-radius: 8px;
            }}
            QMenu::item {{
                padding: 7px 22px 7px 14px;
                border-radius: 6px;
                color: {TEXT};
            }}
            QMenu::item:selected {{
                background: {ACCENT_SOFT};
                color: {ACCENT};
            }}
            """
        )
        full_action = menu.addAction("完整复制")
        chosen = menu.exec(pos)
        menu.deleteLater()
        if chosen is full_action:
            self._copy_full_expression()
        self.window.activateWindow()


class TitleBar(QWidget):
    """Custom title bar that moves the frameless window."""

    def __init__(self, parent: QWidget, window: "CalculatorWindow") -> None:
        super().__init__(parent)
        self._window = window
        self._press_global: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self._manual_drag = False
        self.setObjectName("TitleBar")
        self.setFixedHeight(38)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_global = event.globalPosition().toPoint()
        self._drag_offset = (
            self._press_global - self._window.frameGeometry().topLeft()
        )
        self._dragging = False
        self._manual_drag = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._press_global is None or self._drag_offset is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        point = event.globalPosition().toPoint()
        if not self._dragging:
            # Delay the system move until the pointer actually moves so a
            # double-click can still toggle maximize.
            if (point - self._press_global).manhattanLength() < 4:
                return
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                self._dragging = True
                return
            self._manual_drag = True
            self._dragging = True
        if self._manual_drag:
            self._window.move(point - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._press_global = None
        self._drag_offset = None
        self._dragging = False
        self._manual_drag = False

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximize()


class ResizeGrip(QWidget):
    """Bottom-right grip that drives the manual resize logic.

    ``QSizeGrip`` delegates to the window manager, which does not resize
    frameless X11 windows reliably. Forward the drag to the window instead so
    the grip works on every platform.
    """

    def __init__(self, window: "CalculatorWindow") -> None:
        super().__init__(window.card)
        self._window = window
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("拖动调整窗口大小")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(SUBTLE))
        for offset in (4, 8, 12):
            painter.drawLine(offset, 15, 15, offset)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.start_resize(
                Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
                event.globalPosition().toPoint(),
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._window.resize_to(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.end_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CalculatorWindow(QWidget):
    """Frameless PyQt calculator with the scratchpad workflow."""

    def __init__(self, data_dir: Path | None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(f"计算器 · {DISPLAY_NAME}")
        self.setMinimumSize(*_MIN_SIZE)
        icon_path = paths.assets_dir() / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.icon_family = _icon_family()
        self.scientific_mode = load_scientific_mode(self.data_dir)
        self.max_records = load_max_records(self.data_dir)
        self.result_group_size = load_result_group_size(self.data_dir)
        self.base = 10
        self.rows: list[ExpressionRow] = []
        self.active_row: ExpressionRow | None = None
        self._pinned = False
        self._dialog_open = False
        self._quitting = False
        self._save_dirty = False
        self._start_maximized = False
        self._had_focus = False
        self._scroll_pending = False
        self._resize_edges = Qt.Edge(0)
        self._resize_origin: QPoint | None = None
        self._resize_geometry: QRect | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.flush_scratchpad)
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(500)
        self._geometry_timer.timeout.connect(self._save_window_state)
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.setInterval(_AUTO_HIDE_DELAY_MS)
        self._auto_hide_timer.timeout.connect(self._hide_if_focus_left)

        self._build_ui()
        self.setStyleSheet(_QSS)
        self._restore_scratchpad()
        self._update_base_buttons()
        self._update_digit_buttons()
        self._refresh_conversion()
        self.set_status(self._default_hint())
        self._restore_window_state()
        QApplication.instance().aboutToQuit.connect(self.flush_scratchpad)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        self._outer_layout = outer

        self.card = QFrame(self)
        self.card.setObjectName("Card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(15, 23, 42, 38))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        layout.addWidget(self._build_titlebar())

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        self.section_title = QLabel("草稿纸", self.card)
        self.section_title.setObjectName("SectionTitle")
        header.addWidget(self.section_title)
        header.addStretch(1)
        sci_label = QLabel("科学模式", self.card)
        sci_label.setObjectName("Subtitle")
        header.addWidget(sci_label)
        self.science_switch = Switch(self.card)
        self.science_switch.setChecked(self.scientific_mode)
        self.science_switch.toggled.connect(self.set_scientific_mode)
        header.addWidget(self.science_switch)
        layout.addLayout(header)

        # Growing the window vertically is meant to reveal more scratchpad
        # history, not to inflate the keypad. Give the paper most of the
        # extra height; `_update_keypad_height()` lets the keypad grow a
        # little with the window without stealing rows.
        layout.addWidget(self._build_paper(), 5)
        self.conversion_panel = self._build_conversion()
        layout.addWidget(self.conversion_panel)
        self.base_row = self._build_base_selector()
        layout.addWidget(self.base_row)
        self._keypad = self._build_keypad()
        layout.addWidget(self._keypad, 1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(2, 0, 0, 0)
        status_row.setSpacing(4)
        self.status_label = QLabel("", self.card)
        self.status_label.setObjectName("Status")
        self.status_label.setProperty("tone", "normal")
        status_row.addWidget(self.status_label, 1)
        self.size_grip = ResizeGrip(self)
        status_row.addWidget(
            self.size_grip, 0, Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignBottom
        )
        layout.addLayout(status_row)

        self._apply_scientific_visibility(self.scientific_mode, persist=False)

    def _build_titlebar(self) -> QWidget:
        bar = TitleBar(self.card, self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        badge = QLabel("=", bar)
        badge.setObjectName("Badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(26, 26)
        layout.addWidget(badge)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title = QLabel("计算器", bar)
        title.setObjectName("Title")
        subtitle = QLabel("草稿纸式实时计算", bar)
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)
        for label in (badge, title, subtitle):
            label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )

        self.settings_button = self._icon_button(
            "settings", "设置", bar, self.open_settings
        )
        self.pin_button = self._icon_button("pin", "置顶", bar, self.toggle_pin)
        self.pin_button.setCheckable(True)
        self.minimize_button = self._icon_button(
            "minimize", "隐藏", bar, self.hide_window
        )
        self.maximize_button = self._icon_button(
            "maximize", "放大", bar, self.toggle_maximize
        )
        self.close_button = self._icon_button(
            "close", "关闭", bar, self.request_close
        )
        self.close_button.setObjectName("CloseButton")
        for button in (
            self.settings_button,
            self.pin_button,
            self.minimize_button,
            self.maximize_button,
            self.close_button,
        ):
            layout.addWidget(button)

        self._title_bar = bar
        return bar

    def _icon_button(
        self,
        name: str,
        tooltip: str,
        parent: QWidget,
        callback,
        *,
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("TitleButton")
        button.setToolTip(tooltip)
        button.setFixedSize(30, 30)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCheckable(checkable)
        if self.icon_family:
            if name in ("settings", "pin"):
                # Reuse the exact Material Icons glyphs from the Tk title bar,
                # rendered at its 18pt / 30px grid instead of QToolButton text.
                button.setIcon(
                    _glyph_icon(self.icon_family, _ICON_CODEPOINTS[name])
                )
                button.setIconSize(QSize(30, 30))
            else:
                button.setFont(QFont(self.icon_family, 18))
                button.setText(_ICON_CODEPOINTS[name])
        else:
            button.setText(
                {
                    "settings": "⚙",
                    "pin": "⌖",
                    "minimize": "–",
                    "maximize": "□",
                    "restore": "❐",
                    "close": "×",
                }.get(name, name)
            )
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def _build_paper(self) -> QWidget:
        self.paper_card = QFrame(self.card)
        self.paper_card.setObjectName("PaperCard")
        card_layout = QVBoxLayout(self.paper_card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self.paper_scroll = QScrollArea(self.paper_card)
        self.paper_scroll.setObjectName("PaperScroll")
        self.paper_scroll.setWidgetResizable(True)
        self.paper_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.paper_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.paper_scroll.viewport().setAutoFillBackground(False)
        self.paper_inner = QWidget(self.paper_scroll)
        self.paper_inner.setObjectName("PaperInner")
        self.paper_layout = QVBoxLayout(self.paper_inner)
        self.paper_layout.setContentsMargins(6, 6, 6, 6)
        self.paper_layout.setSpacing(2)
        self.paper_layout.addStretch(1)
        self.paper_scroll.setWidget(self.paper_inner)
        self.paper_scroll.verticalScrollBar().rangeChanged.connect(
            self._on_scroll_range_changed
        )
        card_layout.addWidget(self.paper_scroll)
        self.paper_card.setMinimumHeight(170)
        return self.paper_card

    def _build_conversion(self) -> QWidget:
        panel = QFrame(self.card)
        panel.setObjectName("Conversion")
        grid = QGridLayout(panel)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self._conversion_cells: dict[int, QWidget] = {}
        self._conversion_tags: dict[int, QLabel] = {}
        self._conversion_values: dict[int, QLineEdit] = {}
        for index, base in enumerate((2, 10, 8, 16)):
            cell = QWidget(panel)
            cell.setObjectName("ConvCell")
            cell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(8, 4, 8, 4)
            cell_layout.setSpacing(6)
            tag = QLabel(BASE_LABELS[base], cell)
            tag.setObjectName("ConvTag")
            tag.setFixedWidth(30)
            value = QLineEdit(cell)
            value.setObjectName("ConvValue")
            value.setReadOnly(True)
            value.setFrame(False)
            value.setPlaceholderText("—")
            cell_layout.addWidget(tag)
            cell_layout.addWidget(value, 1)
            grid.addWidget(cell, index // 2, index % 2)
            self._conversion_cells[base] = cell
            self._conversion_tags[base] = tag
            self._conversion_values[base] = value
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return panel

    def _build_base_selector(self) -> QWidget:
        row = QWidget(self.card)
        row.setObjectName("BaseRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)
        label = QLabel("进制", row)
        label.setObjectName("BaseLabel")
        layout.addWidget(label)
        self._base_group = QButtonGroup(row)
        self._base_group.setExclusive(True)
        self.base_buttons: dict[int, QPushButton] = {}
        labels = {
            2: f"{BASE_LABELS[2]} 二进制",
            8: f"{BASE_LABELS[8]} 八进制",
            16: f"{BASE_LABELS[16]} 十六进制",
            10: f"{BASE_LABELS[10]} 十进制",
        }
        for base in (2, 8, 16, 10):
            button = QPushButton(labels[base], row)
            button.setObjectName("Base")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked, b=base: self.set_base(b))
            self._base_group.addButton(button)
            layout.addWidget(button)
            self.base_buttons[base] = button
        layout.addStretch(1)
        return row

    def _build_keypad(self) -> QWidget:
        keypad = QWidget(self.card)
        keypad.setObjectName("Keypad")
        layout = QVBoxLayout(keypad)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        function_row = QWidget(keypad)
        function_layout = QHBoxLayout(function_row)
        function_layout.setContentsMargins(0, 0, 0, 0)
        function_layout.setSpacing(6)
        functions = [
            ("(", lambda: self.insert_text("(")),
            (")", lambda: self.insert_text(")")),
            ("^", lambda: self.insert_text("^")),
            ("%", lambda: self.insert_text("%")),
            ("C", self.clear_active),
            ("←", self.backspace),
        ]
        for label, callback in functions:
            button = self._key_button(label, callback, keypad, role="function")
            function_layout.addWidget(button)
        layout.addWidget(function_row)

        self.hex_row = QWidget(keypad)
        hex_layout = QHBoxLayout(self.hex_row)
        hex_layout.setContentsMargins(0, 0, 0, 0)
        hex_layout.setSpacing(6)
        self._digit_buttons: dict[str, QPushButton] = {}
        for letter in "ABCDEF":
            button = self._key_button(
                letter, lambda _=False, v=letter: self.insert_text(v), keypad
            )
            hex_layout.addWidget(button)
            self._digit_buttons[letter] = button
        layout.addWidget(self.hex_row)

        numeric = QWidget(keypad)
        grid = QGridLayout(numeric)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        key_rows = [
            [("+", "+", "plus"), ("7", "7", "digit"), ("8", "8", "digit"), ("9", "9", "digit")],
            [("−", "-", "minus"), ("4", "4", "digit"), ("5", "5", "digit"), ("6", "6", "digit")],
            [("×", "*", "multiply"), ("1", "1", "digit"), ("2", "2", "digit"), ("3", "3", "digit")],
            [("÷", "/", "divide"), ("0", "0", "digit"), (".", ".", "digit"), ("=", None, "equals")],
        ]
        self.dot_button: QPushButton | None = None
        for row_index, row in enumerate(key_rows):
            grid.setRowStretch(row_index, 1)
            for col_index, (label, value, role) in enumerate(row):
                if value is None:
                    callback = self.evaluate_active
                elif value in "0123456789":
                    callback = lambda v=value: self.insert_text(v)
                elif value == ".":
                    callback = lambda: self.insert_text(".")
                else:
                    callback = lambda v=value: self.insert_text(v)
                button = self._key_button(label, callback, keypad, role=role)
                grid.addWidget(button, row_index, col_index)
                if value is not None and value in "0123456789":
                    self._digit_buttons[value] = button
                elif value == ".":
                    self.dot_button = button
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addWidget(numeric, 1)
        return keypad

    def _key_button(
        self,
        label: str,
        callback,
        parent: QWidget,
        *,
        role: str = "digit",
    ) -> QPushButton:
        button = QPushButton(label, parent)
        button.setObjectName("Key")
        button.setProperty("role", role)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        button.setMinimumHeight(34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    # ----------------------------------------------------------- lifecycle
    def show_initial(self) -> None:
        self.show()
        self.raise_()
        if self._start_maximized:
            self.showMaximized()
        QTimer.singleShot(80, self._activate_and_focus)

    def handle_command(self, command: str) -> None:
        if command == "show":
            self.request_show()
        elif command == "hide":
            self.hide()
            self.flush_scratchpad()
        elif command == "quit":
            self.request_close()

    def request_show(self) -> None:
        self._auto_hide_timer.stop()
        was_visible = self.isVisible()
        if not was_visible:
            self._had_focus = False
            self.show()
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.raise_()
        QTimer.singleShot(0, self.activateWindow)
        if not was_visible:
            QTimer.singleShot(50, self._activate_and_focus)

    def _activate_and_focus(self) -> None:
        self.raise_()
        self.activateWindow()
        self.begin_new_entry()

    def hide_window(self) -> None:
        self.flush_scratchpad()
        self._save_window_state()
        self.hide()

    def request_close(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.flush_scratchpad()
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.flush_scratchpad()
        self._save_window_state()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                self._had_focus = True
                self._auto_hide_timer.stop()
            elif self._had_focus:
                self._schedule_auto_hide()
        elif event.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            self._outer_layout.setContentsMargins(
                0 if maximized else 10,
                0 if maximized else 10,
                0 if maximized else 10,
                0 if maximized else 10,
            )
            self._update_maximize_button(maximized)
            self._geometry_timer.start()
        super().changeEvent(event)

    def _schedule_auto_hide(self) -> None:
        if (
            self._pinned
            or self._dialog_open
            or not self.isVisible()
            or self.isMinimized()
        ):
            return
        self._auto_hide_timer.start()

    def _hide_if_focus_left(self) -> None:
        if not self._had_focus:
            return
        if not self.isVisible() or self.isActiveWindow():
            return
        if self._pinned or self._dialog_open:
            return
        if QApplication.activePopupWidget() is not None:
            return
        if QApplication.activeModalWidget() is not None:
            return
        self._save_window_state()
        self.hide()
        self.flush_scratchpad()

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._update_maximize_button(self.isMaximized())

    def _update_maximize_button(self, maximized: bool) -> None:
        name = "restore" if maximized else "maximize"
        if self.icon_family:
            self.maximize_button.setFont(QFont(self.icon_family, 16))
            self.maximize_button.setText(_ICON_CODEPOINTS[name])
        else:
            self.maximize_button.setText("❐" if maximized else "□")
        self.maximize_button.setToolTip("还原" if maximized else "放大")
        self.size_grip.setVisible(not maximized)

    def _apply_topmost(self, enabled: bool) -> None:
        """Change always-on-top without recreating the native window.

        ``setWindowFlags()`` hides and recreates a visible top-level window,
        which makes the calculator flash (and can briefly lose focus). Use the
        platform APIs instead; ``_pinned`` still suppresses focus-out hiding
        on platforms without an always-on-top mechanism.
        """
        if sys.platform == "win32":
            _set_win32_topmost(self, enabled)
            return
        if sys.platform.startswith("linux"):
            platform = QGuiApplication.platformName().lower()
            if platform == "xcb":
                _set_x11_topmost(self, enabled)
            else:
                log.debug("Qt 平台 %s 无原生置顶支持", platform)
            return

    def toggle_pin(self) -> None:
        pinned = self.pin_button.isChecked()
        self._pinned = pinned
        self._apply_topmost(pinned)
        if pinned:
            self._auto_hide_timer.stop()
            self.raise_()
        self.set_status("已置顶" if pinned else "已取消置顶")

    # ------------------------------------------------------------ resizing
    def _edges_at(self, point: QPoint) -> Qt.Edge:
        if self.isMaximized():
            return Qt.Edge(0)
        margin = 10
        edges = Qt.Edge(0)
        if point.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if point.y() <= margin:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def start_resize(self, edges: Qt.Edge, global_pos: QPoint) -> None:
        """Begin a manual resize from an edge or the bottom-right grip.

        On Wayland clients cannot move/resize their own top-level windows, so
        hand the gesture to the compositor there. X11 and Windows use manual
        geometry updates because the window manager may ignore
        ``startSystemResize()`` for frameless windows.
        """
        if self.isMaximized() or not edges:
            return
        if QGuiApplication.platformName().lower().startswith("wayland"):
            handle = self.windowHandle()
            if handle is not None and handle.startSystemResize(edges):
                return
        self._resize_edges = edges
        self._resize_origin = QPoint(global_pos)
        self._resize_geometry = self.geometry()
        self._apply_resize_cursor(edges)

    def resize_to(self, global_pos: QPoint) -> None:
        if self._resize_origin is None or self._resize_geometry is None:
            return
        delta = global_pos - self._resize_origin
        start = self._resize_geometry
        x, y = start.x(), start.y()
        width, height = start.width(), start.height()
        minimum = self.minimumSize()
        min_width = max(1, minimum.width())
        min_height = max(1, minimum.height())
        if self._resize_edges & Qt.Edge.LeftEdge:
            width = width - delta.x()
            if width < min_width:
                width = min_width
                x = start.x() + start.width() - min_width
            else:
                x = start.x() + delta.x()
        elif self._resize_edges & Qt.Edge.RightEdge:
            width = max(min_width, width + delta.x())
        if self._resize_edges & Qt.Edge.TopEdge:
            height = height - delta.y()
            if height < min_height:
                height = min_height
                y = start.y() + start.height() - min_height
            else:
                y = start.y() + delta.y()
        elif self._resize_edges & Qt.Edge.BottomEdge:
            height = max(min_height, height + delta.y())
        self.setGeometry(x, y, width, height)

    def end_resize(self) -> None:
        active = self._resize_origin is not None
        self._resize_edges = Qt.Edge(0)
        self._resize_origin = None
        self._resize_geometry = None
        if active:
            self._apply_resize_cursor(Qt.Edge(0))

    def _apply_resize_cursor(self, edges: Qt.Edge) -> None:
        if not edges:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif (right and top) or (left and bottom):
            shape = Qt.CursorShape.SizeBDiagCursor
        elif left or right:
            shape = Qt.CursorShape.SizeHorCursor
        else:
            shape = Qt.CursorShape.SizeVerCursor
        self.setCursor(shape)

    # -------------------------------------------------------------- drag
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self.start_resize(
                    edges, event.globalPosition().toPoint()
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._resize_origin is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.resize_to(event.globalPosition().toPoint())
                event.accept()
                return
            self.end_resize()
        if not self.isMaximized():
            self._apply_resize_cursor(
                self._edges_at(event.position().toPoint())
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._resize_origin is not None:
            self.end_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._resize_origin is None:
            self._apply_resize_cursor(Qt.Edge(0))
        super().leaveEvent(event)

    # -------------------------------------------------------------- rows
    def add_row(self, *, focus: bool = False) -> ExpressionRow:
        row = ExpressionRow(self, self.base)
        self.rows.append(row)
        self.paper_layout.addWidget(row)
        if self.active_row is None:
            self.activate_row(row)
        if focus:
            self.activate_row(row)
            row.focus_entry()
        self._scroll_to_bottom()
        return row

    def activate_row(self, row: ExpressionRow) -> None:
        if row not in self.rows:
            return
        if self.active_row is row:
            self._refresh_conversion()
            return
        self.active_row = row
        for existing in self.rows:
            existing.set_active(existing is row)
        self._refresh_conversion()

    def select_row(self, row: ExpressionRow) -> None:
        """Clicking a row makes it the active/current input row."""
        self.activate_row(row)

    def begin_new_entry(self) -> None:
        if self.rows and not self.rows[-1].expression.strip():
            row = self.rows[-1]
        else:
            row = self.add_row(focus=False)
        self.activate_row(row)
        row.focus_entry()
        self._scroll_to_bottom()

    def evaluate_active(self) -> None:
        row = self.active_row or (self.rows[-1] if self.rows else None)
        if row is not None:
            self.evaluate_row(row)

    def evaluate_row(self, row: ExpressionRow) -> None:
        text = row.expression
        if not text.strip():
            return
        row.entry_base = self.base
        try:
            value = evaluate_live(text, self.base)
            formatted = format_result(
                value, self.base, self.result_group_size
            )
        except ExpressionError as exc:
            row.set_error("错误")
            self.set_status(str(exc), error=True)
            self._refresh_conversion()
            self._request_scratchpad_save()
            return
        except Exception:
            log.exception("计算器求值失败：%s", text)
            row.set_error("错误")
            self.set_status("计算失败，请检查表达式", error=True)
            self._refresh_conversion()
            self._request_scratchpad_save()
            return
        row.set_result(value, self.base, formatted)
        self.set_status(self._default_hint())
        self.activate_row(row)
        self._refresh_conversion()
        self._request_scratchpad_save()
        if row is self.rows[-1]:
            self.add_row(focus=True)

    def on_row_text_changed(self, row: ExpressionRow) -> None:
        self._update_live_result(row)
        if row is self.active_row:
            self._refresh_conversion()
        self.set_status(self._default_hint())
        self._request_scratchpad_save()

    def _update_live_result(self, row: ExpressionRow) -> None:
        text = row.expression
        if not text.strip():
            row.clear_result()
            return
        try:
            value = evaluate_live(text, self.base)
            formatted = format_result(
                value, self.base, self.result_group_size
            )
        except Exception:
            row.clear_result()
            return
        row.set_result(value, self.base, formatted)

    def insert_text(self, text: str) -> None:
        row = self.active_row
        if row is None:
            row = self.add_row(focus=True)
        row.entry.insert(text)
        self.activate_row(row)
        # Keep the caret where QLineEdit.insert() left it (right after the
        # inserted text); forcing it to the end would make an insertion in
        # the middle of an expression jump behind the trailing digits.
        row.focus_entry(move_to_end=False)

    def backspace(self) -> None:
        row = self.active_row
        if row is None:
            return
        if row.entry.hasSelectedText():
            row.entry.del_()
        else:
            row.entry.backspace()
        self.activate_row(row)
        row.focus_entry(move_to_end=False)

    def clear_active(self) -> None:
        row = self.active_row
        if row is None:
            return
        row.clear_all()
        row.focus_entry()
        self.activate_row(row)
        self.set_status(self._default_hint())

    def delete_row(self, row: ExpressionRow) -> None:
        if row not in self.rows:
            return
        index = self.rows.index(row)
        had_text = bool(row.expression.strip())
        was_active = self.active_row is row
        self.rows.pop(index)
        if was_active:
            self.active_row = None
        row.setParent(None)
        row.deleteLater()
        if not self.rows:
            self.add_row(focus=True)
        elif was_active:
            target = self.rows[min(index, len(self.rows) - 1)]
            self.activate_row(target)
            target.focus_entry()
        else:
            self._refresh_conversion()
        self._request_scratchpad_save(immediate=True)
        self.set_status("已删除 1 条记录" if had_text else "已删除空行")

    # -------------------------------------------------------------- bases
    def set_base(self, base: int, *, schedule_save: bool = True) -> None:
        if base not in SUPPORTED_BASES:
            return
        if not self.scientific_mode and base != 10:
            return
        self.base = base
        for value, button in self.base_buttons.items():
            button.setChecked(value == base)
        self._update_digit_buttons()
        row = self.active_row
        if row is not None:
            row.entry_base = base
            self._update_live_result(row)
        self._refresh_conversion()
        if row is not None:
            row.focus_entry()
        if schedule_save:
            self._request_scratchpad_save()

    def _update_base_buttons(self) -> None:
        for value, button in self.base_buttons.items():
            button.setChecked(value == self.base)

    def _update_digit_buttons(self) -> None:
        valid = {
            2: set("01"),
            8: set("01234567"),
            10: set("0123456789"),
            16: set("0123456789ABCDEF"),
        }[self.base]
        for label, button in self._digit_buttons.items():
            button.setEnabled(label in valid)
        if self.dot_button is not None:
            self.dot_button.setEnabled(self.base == 10)

    def _refresh_conversion(self) -> None:
        value: int | float | None = None
        active = self.active_row
        if active is not None:
            text = active.expression.strip()
            if (
                active.result_value is not None
                and active.result_base == self.base
                and active.evaluated_expression == active.expression
            ):
                value = active.result_value
            elif text:
                try:
                    value = evaluate_live(text, self.base)
                except Exception:
                    value = None
            else:
                for candidate in reversed(self.rows):
                    if candidate.result_value is not None:
                        value = candidate.result_value
                        break
        try:
            converted = (
                convert_bases(value)
                if value is not None
                else {base: None for base in SUPPORTED_BASES}
            )
        except Exception:
            log.exception("计算器进制转换失败")
            converted = {base: None for base in SUPPORTED_BASES}
        for base in SUPPORTED_BASES:
            is_active = base == self.base
            cell = self._conversion_cells[base]
            tag = self._conversion_tags[base]
            cell.setProperty("active", is_active)
            tag.setProperty("active", is_active)
            _repolish(cell)
            _repolish(tag)
            text = converted.get(base)
            self._conversion_values[base].setText(text or "")

    # ------------------------------------------------------- scientific UI
    def set_scientific_mode(self, enabled: bool) -> None:
        self._apply_scientific_visibility(bool(enabled), persist=True)

    def _apply_scientific_visibility(
        self, enabled: bool, *, persist: bool
    ) -> None:
        enabled = bool(enabled)
        if not enabled and self.base != 10:
            self.set_base(10)
        self.scientific_mode = enabled
        self.conversion_panel.setVisible(enabled)
        self.base_row.setVisible(enabled)
        self.hex_row.setVisible(enabled)
        if self.science_switch.isChecked() != enabled:
            self.science_switch.blockSignals(True)
            self.science_switch.setChecked(enabled)
            self.science_switch.blockSignals(False)
        self.setMinimumHeight(640 if enabled else 600)
        self._update_keypad_height()
        self._update_digit_buttons()
        self._refresh_conversion()
        self.set_status(self._default_hint())
        if persist:
            save_scientific_mode(self.data_dir, enabled)

    def _default_hint(self) -> str:
        text = "自动计算 · Enter 新建下一层 · 点击结果复制 · 右键完整复制"
        if self.scientific_mode:
            text += " · 支持 0x/0b/0o 前缀"
        return text

    def set_status(
        self,
        message: str,
        *,
        error: bool = False,
        success: bool = False,
    ) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty(
            "tone", "error" if error else ("success" if success else "normal")
        )
        _repolish(self.status_label)

    # ------------------------------------------------------------ settings
    def open_settings(self) -> None:
        self._dialog_open = True
        dialog = SettingsDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
            self._dialog_open = False
            QTimer.singleShot(0, self.activateWindow)

    def apply_max_records(self, value: int) -> int:
        normalized = save_max_records(self.data_dir, value)
        self.max_records = normalized
        removed = self._trim_rows()
        self._request_scratchpad_save(immediate=True)
        if removed:
            self.set_status(f"已保留最近 {normalized} 条记录", success=True)
        else:
            self.set_status(f"最多保存 {normalized} 条记录")
        return removed

    def apply_result_group_size(self, value: int) -> int:
        normalized = save_result_group_size(self.data_dir, value)
        self.result_group_size = normalized
        for row in self.rows:
            if row.result_value is None or row.result_base is None:
                continue
            try:
                formatted = format_result(
                    row.result_value, row.result_base, normalized
                )
                row.result_label.setText(f"= {formatted}")
            except Exception:
                continue
        self._refresh_conversion()
        if normalized:
            self.set_status(f"结果每 {normalized} 位加分隔符")
        else:
            self.set_status("已关闭结果分隔符")
        return normalized

    def clear_scratchpad(self) -> int:
        count = sum(1 for row in self.rows if row.expression.strip())
        for row in list(self.rows):
            row.setParent(None)
            row.deleteLater()
        self.rows.clear()
        self.active_row = None
        self.add_row(focus=True)
        self._refresh_conversion()
        self._request_scratchpad_save(immediate=True)
        self.set_status("已清空草稿纸记忆", success=True)
        return count

    def _trim_rows(self) -> int:
        records = [row for row in self.rows if row.expression.strip()]
        excess = len(records) - self.max_records
        if excess <= 0:
            return 0
        active = self.active_row
        active_index = self.rows.index(active) if active in self.rows else 0
        for row in records[:excess]:
            if row not in self.rows:
                continue
            self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        if not self.rows:
            self.active_row = None
            self.add_row()
        else:
            if active is None or active not in self.rows:
                target = self.rows[
                    max(0, min(active_index - excess, len(self.rows) - 1))
                ]
                self.active_row = None
                self.activate_row(target)
                target.focus_entry()
        self._refresh_conversion()
        return excess

    def _about_text(self) -> str:
        meta = _load_plugin_meta()
        description = str(meta.get("description", "")).replace("\n", "<br>")
        return (
            f"<b>{meta.get('name', '计算器')}</b> v{meta.get('version', '')}<br><br>"
            f"{description}<br><br>"
            f"作者：{meta.get('author', 'QuickTools')}<br>"
            f'<a href="{PROJECT_URL}">{PROJECT_URL}</a>'
        )

    # ------------------------------------------------------- persistence
    def _restore_scratchpad(self) -> None:
        state = load_scratchpad(self.data_dir, max_records=self.max_records)
        for entry in state.entries:
            row = self.add_row()
            row.entry_base = entry.base
            row.restore_expression(entry.expression)
            self._apply_saved_result(row, entry.base)
        self.add_row(focus=True)
        if self.scientific_mode and state.last_base in SUPPORTED_BASES:
            self.set_base(state.last_base, schedule_save=False)
        if self.rows:
            self.activate_row(self.rows[-1])
        self._save_timer.stop()
        self._save_dirty = False

    def _apply_saved_result(self, row: ExpressionRow, base: int) -> None:
        text = row.expression
        if not text.strip():
            row.clear_result()
            return
        try:
            value = evaluate_live(text, base)
            formatted = format_result(value, base, self.result_group_size)
        except Exception:
            row.clear_result()
            return
        row.set_result(value, base, formatted)

    def _capture_scratchpad_state(self) -> ScratchpadState:
        entries = [
            ScratchEntry(row.expression, row.entry_base)
            for row in self.rows
            if row.expression.strip()
        ]
        return ScratchpadState(
            entries=tuple(entries[-self.max_records :]),
            last_base=self.base,
        )

    def _request_scratchpad_save(self, *, immediate: bool = False) -> None:
        if self.data_dir is None:
            return
        self._save_dirty = True
        self._save_timer.stop()
        if immediate:
            self.flush_scratchpad()
        else:
            self._save_timer.start()

    def flush_scratchpad(self) -> None:
        self._save_timer.stop()
        if self.data_dir is None or not self._save_dirty:
            return
        try:
            save_scratchpad(
                self.data_dir,
                self._capture_scratchpad_state(),
                max_records=self.max_records,
            )
        except Exception:
            log.exception("保存计算器草稿纸失败")
            return
        self._save_dirty = False

    def _restore_window_state(self) -> None:
        width, height = _DEFAULT_SIZE
        self._start_maximized = False
        if self.data_dir is not None:
            path = self.data_dir / _WINDOW_STATE_FILE
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                width = int(raw.get("width", width))
                height = int(raw.get("height", height))
                self._start_maximized = bool(raw.get("maximized", False))
            except FileNotFoundError:
                pass
            except Exception:
                log.debug("读取计算器窗口状态失败", exc_info=True)
        screen = (
            QApplication.screenAt(QCursor.pos())
            or self.screen()
            or QApplication.primaryScreen()
        )
        if screen is not None:
            available = screen.availableGeometry()
            width = max(_MIN_SIZE[0], min(width, available.width() - 40))
            height = max(_MIN_SIZE[1], min(height, available.height() - 60))
            x = available.x() + (available.width() - width) // 2
            y = available.y() + (available.height() - height) // 2
            self.setGeometry(x, y, width, height)
        else:
            self.resize(width, height)

    def _save_window_state(self) -> None:
        if self.data_dir is None:
            return
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        state = {
            "width": geometry.width(),
            "height": geometry.height(),
            "maximized": self.isMaximized(),
        }
        try:
            atomic_write_json(self.data_dir / _WINDOW_STATE_FILE, state)
        except Exception:
            log.debug("保存计算器窗口状态失败", exc_info=True)

    def _update_keypad_height(self) -> None:
        """Let the keypad grow a little with tall windows.

        The 5:1 layout stretch makes the scratchpad the main beneficiary of
        extra height. Raising the keypad's minimum slightly keeps the keys
        from staying pinned at their smallest size on tall windows without
        taking rows away from the paper.
        """
        keypad = getattr(self, "_keypad", None)
        if keypad is None:
            return
        base = keypad.minimumSizeHint().height()
        if base <= 0:
            return
        spare = max(0, self.height() - self.minimumHeight())
        keypad.setMinimumHeight(base + min(56, spare // 8))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._update_keypad_height()
        if not self.isMaximized():
            self._geometry_timer.start()

    def moveEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().moveEvent(event)

    def _scroll_to_bottom(self) -> None:
        """Scroll after Qt has recalculated the paper's scroll range.

        A single 0 ms timer can run before ``QScrollArea`` updates its
        maximum, which leaves the new row out of view; keep a short pending
        window and follow ``rangeChanged`` as well.
        """
        self._scroll_pending = True
        try:
            self.paper_inner.adjustSize()
            self.paper_layout.activate()
        except RuntimeError:
            return
        self._apply_scroll_bottom()
        QTimer.singleShot(0, self._apply_scroll_bottom)
        QTimer.singleShot(50, self._apply_scroll_bottom)
        QTimer.singleShot(200, self._finish_scroll_bottom)

    def _apply_scroll_bottom(self) -> None:
        if not self._scroll_pending:
            return
        try:
            bar = self.paper_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        except RuntimeError:
            self._scroll_pending = False

    def _finish_scroll_bottom(self) -> None:
        self._apply_scroll_bottom()
        self._scroll_pending = False

    def _on_scroll_range_changed(self, _minimum: int, _maximum: int) -> None:
        if self._scroll_pending:
            self._apply_scroll_bottom()


class SettingsDialog(QDialog):
    def __init__(self, window: CalculatorWindow) -> None:
        super().__init__(window)
        self.window_ref = window
        self.setWindowTitle("计算器设置")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        title = QLabel("计算器设置与关于", self)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self.max_records_spin = QSpinBox(self)
        self.max_records_spin.setRange(MIN_MAX_RECORDS, MAX_MAX_RECORDS)
        self.max_records_spin.setValue(window.max_records)
        form.addRow("最多保存条数", self.max_records_spin)
        self.group_size_spin = QSpinBox(self)
        self.group_size_spin.setRange(
            MIN_RESULT_GROUP_SIZE, MAX_RESULT_GROUP_SIZE
        )
        self.group_size_spin.setValue(window.result_group_size)
        form.addRow("结果分隔位数", self.group_size_spin)
        layout.addLayout(form)

        hint = QLabel(
            "分隔位数为 0 时不分隔；设为 3 会把 1000 显示为 1,000。",
            self,
        )
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        data_row = QHBoxLayout()
        self.data_label = QLabel(
            str(window.data_dir) if window.data_dir else "未设置数据目录", self
        )
        self.data_label.setObjectName("Subtitle")
        self.data_label.setWordWrap(True)
        data_row.addWidget(self.data_label, 1)
        open_button = QPushButton("打开数据目录", self)
        open_button.setObjectName("Base")
        open_button.clicked.connect(self._open_data_dir)
        data_row.addWidget(open_button)
        layout.addLayout(data_row)

        clear_button = QPushButton("清空草稿纸记忆", self)
        clear_button.setObjectName("Base")
        clear_button.clicked.connect(self._clear_history)
        layout.addWidget(clear_button)

        about = QLabel(window._about_text(), self)
        about.setObjectName("Subtitle")
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        about.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(about)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        window = self.window_ref
        window.apply_max_records(self.max_records_spin.value())
        window.apply_result_group_size(self.group_size_spin.value())
        self.accept()

    def _clear_history(self) -> None:
        question = QMessageBox(self)
        question.setIcon(QMessageBox.Icon.Question)
        question.setWindowTitle("清空草稿纸记忆")
        question.setText("确定要清空全部草稿纸记录吗？此操作不可撤销。")
        clear_button = question.addButton(
            "清空", QMessageBox.ButtonRole.AcceptRole
        )
        question.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        question.exec()
        clear_confirmed = question.clickedButton() is clear_button
        question.deleteLater()
        if not clear_confirmed:
            return
        removed = self.window_ref.clear_scratchpad()
        info = QMessageBox(self)
        info.setIcon(QMessageBox.Icon.Information)
        info.setWindowTitle("已清空")
        info.setText(f"已删除 {removed} 条记录。")
        info.addButton("知道了", QMessageBox.ButtonRole.AcceptRole)
        info.exec()
        info.deleteLater()

    def _open_data_dir(self) -> None:
        data_dir = self.window_ref.data_dir
        if data_dir is None:
            return
        data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir)))


def _load_plugin_meta() -> dict:
    path = Path(__file__).with_name("plugin.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def create_window(data_dir: Path | None) -> CalculatorWindow:
    return CalculatorWindow(data_dir)
