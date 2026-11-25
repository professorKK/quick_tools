"""gp 悬浮窗：桌面上的圆角方形系统监控卡片。

这个模块只运行在 helper 进程里（PyQt6 独立进程），主进程的 Tk 永远不会
导入它，避免两套事件循环混用。卡片周期显示内存与系统盘占用，采样由
``metrics.py`` 负责，绘制时只读最新快照。
"""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass, replace
from typing import Callable

from PyQt6.QtCore import QPoint, QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import QMenu, QWidget

from .geometry import (
    SCREEN_MARGIN,
    Rect,
    Size,
    clamp_into,
    default_position,
    position_after_resize,
    resolve_position,
    screen_by_name,
    screen_for_rect,
)
from .input_mode import InputMode, UnsupportedInputMode, create_input_mode
from .metrics import (
    METRICS_INTERVAL_MS,
    MetricsSampler,
    SystemUsage,
    UsageStat,
    format_percent,
    format_usage_detail,
    is_critical,
)
from .qt_screens import (
    primary_screen_name,
    rect_for,
    screen_areas,
)
from .settings import GpSettings

log = logging.getLogger(__name__)

# Shift 是唯一的交互修饰键：松开时窗口点击穿透，按住时恢复交互。
INPUT_POLL_INTERVAL_MS = 30
# Windows 分层窗口的 alpha=0 像素会被命中测试跳过；用几乎不可见的
# alpha=1/255 铺满整个矩形，保证 Shift 按住时透明角落也能点击。
WIN32_HIT_FILL_ALPHA = 1

# 小于该边长时使用紧凑布局（名称 + 百分比 + 细进度条）。
FULL_LAYOUT_MIN_DIAMETER = 160
# 再小就只画卡片，避免文字和进度条挤成噪点；10px 恢复入口仍可右键。
MIN_TEXT_DIAMETER = 48

# 深色卡片配色，参考用户提供的系统监控卡片。
CARD_COLOR = QColor("#1b2430")
CARD_BORDER_COLOR = QColor("#334155")
CARD_TEXT_COLOR = QColor("#f8fafc")
CARD_SECONDARY_TEXT_COLOR = QColor("#94a3b8")
CARD_DIVIDER_COLOR = QColor("#334155")
CARD_TRACK_COLOR = QColor("#334155")
MEMORY_COLOR = QColor("#2dd4bf")
DISK_COLOR = QColor("#3b82f6")
# 达到 95% 时的警示色；深色卡片用亮红，透明背景用更深的红。
CRITICAL_COLOR = QColor("#ef4444")
CRITICAL_BAR_SCALE = 1.6

# 关闭填充时的透明背景配色：深色文字加白色描边，浅色桌面上也能读。
RING_COLOR = QColor("#94a3b8")
TEXT_COLOR = QColor("#0f172a")
SECONDARY_TEXT_COLOR = QColor("#475569")
TEXT_HALO_COLOR = QColor("#ffffff")
DIVIDER_COLOR = QColor(148, 163, 184, 150)
TRACK_COLOR = QColor("#cbd5e1")
LIGHT_MEMORY_COLOR = QColor("#0d9488")
LIGHT_DISK_COLOR = QColor("#2563eb")
LIGHT_CRITICAL_COLOR = QColor("#dc2626")

EVENT_CLOSED = "closed"

# 手动输入允许边长 0，但窗口至少保留这么大的可点击区域，避免完全消失后
# 无法再右键打开设置恢复。
MIN_RENDER_DIAMETER = 10


@dataclass(frozen=True)
class _Palette:
    card: QColor | None
    border: QColor
    primary: QColor
    secondary: QColor
    divider: QColor
    track: QColor
    memory: QColor
    disk: QColor
    critical: QColor
    halo: QColor | None


class FloatingWidget(QWidget):
    """A rounded-square, always-on-top system monitor widget."""

    def __init__(
        self,
        settings: GpSettings,
        *,
        on_open_settings: Callable[[], None],
        on_exit: Callable[[], None],
        emit: Callable[[str], None],
        persist: Callable[[GpSettings], None],
        input_mode: InputMode | None = None,
        metrics_source: MetricsSampler | None = None,
    ) -> None:
        super().__init__(None)
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit
        self._emit = emit
        self._persist = persist
        self._settings = settings.normalized()
        self._hovered = False
        # 右键菜单是独立弹窗，会抢走鼠标并触发本窗口的 leaveEvent。
        # 菜单打开期间保持悬停透明度，关闭后再按鼠标实际位置重新判定。
        self._menu_open = False
        self._dragging = False
        self._drag_offset: QPoint | None = None

        self._input_mode = input_mode or self._create_input_mode()
        try:
            self._input_supported = bool(self._input_mode.supported())
        except Exception:
            log.exception("初始化 gp 输入模式失败")
            self._input_mode = UnsupportedInputMode()
            self._input_supported = False
        self._input_failed = False
        self._input_interactive = True
        self._input_click_through: bool | None = None
        self._shift_down = False
        self._shutdown = False
        self._shift_timer = QTimer(self)
        self._shift_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._shift_timer.setInterval(INPUT_POLL_INTERVAL_MS)
        self._shift_timer.timeout.connect(self._poll_shift)

        self._metrics_source = metrics_source or MetricsSampler()
        self._usage = SystemUsage.empty()
        self._metrics_failed = False
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(METRICS_INTERVAL_MS)
        self._metrics_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._metrics_timer.timeout.connect(self._refresh_metrics)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 不抢焦点，悬浮窗只是安静地待在桌面上。
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle("gp 系统监控")
        render_diameter = max(self._settings.diameter, MIN_RENDER_DIAMETER)
        self.setFixedSize(render_diameter, render_diameter)
        self._apply_opacity()

    @staticmethod
    def _create_input_mode() -> InputMode:
        try:
            return create_input_mode()
        except Exception:
            log.exception("创建 gp 输入模式失败，保持可交互")
            return UnsupportedInputMode()

    # ------------------------------------------------------------- settings
    @property
    def settings(self) -> GpSettings:
        return self._settings

    def apply_appearance(self, values: GpSettings) -> bool:
        """Apply appearance fields and keep the saved position in control.

        Returns True when a saved position changed (the caller should persist
        immediately instead of waiting for the debounce timer).
        """
        normalized = values.normalized()
        old_rect = rect_for(self)
        old_diameter = self.width()
        self._settings = replace(
            self._settings,
            idle_opacity=normalized.idle_opacity,
            active_opacity=normalized.active_opacity,
            diameter=normalized.diameter,
            fill_background=normalized.fill_background,
        )
        moved = False
        render_diameter = max(normalized.diameter, MIN_RENDER_DIAMETER)
        if render_diameter != old_diameter:
            self.setFixedSize(render_diameter, render_diameter)
            moved = self._reposition_after_resize(old_rect)
        self._apply_opacity()
        self.update()
        return moved

    def _reposition_after_resize(self, old_rect: Rect) -> bool:
        """Keep the widget centered and fully inside a screen after resizing."""
        screens = screen_areas()
        size = Size(self.width(), self.height())
        if self._settings.x is None or self._settings.y is None:
            area = screen_by_name(primary_screen_name(), screens)
            if area is None and screens:
                area = screens[0]
            if area is not None:
                x, y = default_position(size, area, SCREEN_MARGIN)
                self.move(x, y)
            # 默认位置模式不写入坐标，继续跟随右下角。
            return False
        x, y, screen_name = position_after_resize(old_rect, size, screens)
        self.move(x, y)
        self._settings = replace(
            self._settings, x=x, y=y, screen=screen_name
        )
        return True

    # -------------------------------------------------------------- display
    def show_widget(self) -> None:
        """Show the widget at its saved (or default) position."""
        x, y = resolve_position(
            self._settings.x,
            self._settings.y,
            self._settings.screen,
            Size(self.width(), self.height()),
            screen_areas(),
            primary_screen_name(),
            SCREEN_MARGIN,
        )
        self.move(x, y)
        self.show()
        self.raise_()
        self._sync_input_mode(force=True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._start_input_polling()
        if self._shift_timer.isActive():
            self._poll_shift()
        self._sync_input_mode(force=True)
        self._start_metrics_polling()

    def reset_position(self) -> None:
        """Forget the saved coordinates and go back to the default corner."""
        self._settings = replace(self._settings, x=None, y=None, screen=None)
        screens = screen_areas()
        area = screen_by_name(primary_screen_name(), screens)
        if area is None and screens:
            area = screens[0]
        if area is not None:
            x, y = default_position(
                Size(self.width(), self.height()), area, SCREEN_MARGIN
            )
            self.move(x, y)
        self._persist(self._settings)
        self._emit(f"position {self.x()} {self.y()}")

    def _apply_opacity(self) -> None:
        value = (
            self._settings.active_opacity
            if self._hovered
            else self._settings.idle_opacity
        )
        self.setWindowOpacity(max(0.05, min(1.0, float(value))))

    # ------------------------------------------------------------ metrics
    def _start_metrics_polling(self) -> None:
        if self._shutdown:
            return
        self._refresh_metrics()
        if not self._metrics_timer.isActive():
            self._metrics_timer.start()

    def _refresh_metrics(self) -> None:
        if self._shutdown:
            return
        try:
            usage = self._metrics_source.sample()
        except Exception:
            if not self._metrics_failed:
                self._metrics_failed = True
                log.exception("刷新 gp 系统指标失败，悬浮窗显示 --")
            usage = SystemUsage.empty()
        else:
            if self._metrics_failed:
                self._metrics_failed = False
                log.info("gp 系统指标刷新已恢复")
        if not isinstance(usage, SystemUsage):
            usage = SystemUsage.empty()
        if usage != self._usage:
            self._usage = usage
            self.update()

    # ----------------------------------------------------------- input mode
    def _start_input_polling(self) -> None:
        if self._shutdown or not self._input_supported:
            return
        if self._input_failed and self._input_click_through is not True:
            return
        if not self._shift_timer.isActive():
            self._shift_timer.start()

    def _poll_shift(self) -> None:
        if self._shutdown or not self._input_supported:
            return
        if self._input_failed:
            # 恢复输入区域失败时继续重试；恢复成功后定时器会在
            # _sync_input_mode 里停止。未知状态（None）也按“可能仍穿透”
            # 处理，避免窗口点不到。
            if self._input_click_through is not False:
                self._sync_input_mode(force=True)
            else:
                self._shift_timer.stop()
            return
        try:
            down = bool(self._input_mode.shift_down())
        except Exception:
            log.exception("读取 gp Shift 状态失败，悬浮窗保持可交互")
            self._degrade_input_mode()
            return
        self._set_shift_down(down)

    def _set_shift_down(self, down: bool) -> None:
        down = bool(down)
        if down == self._shift_down:
            return
        self._shift_down = down
        self._sync_input_mode()

    def _apply_click_through(self, enabled: bool) -> bool:
        try:
            applied = bool(self._input_mode.set_click_through(self, enabled))
        except Exception:
            log.exception("设置 gp 点击穿透失败")
            return False
        if applied:
            self._input_click_through = enabled
        return applied

    def _degrade_input_mode(self) -> None:
        if self._input_failed:
            return
        self._input_failed = True
        log.warning("gp 点击穿透不可用，悬浮窗保持可交互")
        self._sync_input_mode(force=True)

    def _sync_input_mode(self, force: bool = False) -> None:
        if self._shutdown:
            return
        if self._input_failed:
            # 失败后永久保持可交互；如果最后一次已知状态仍是穿透，继续
            # 重试恢复，绝不能把窗口留在点不到的状态。
            self._input_interactive = True
            if self._input_click_through is not False:
                if self._apply_click_through(False):
                    self._shift_timer.stop()
            if self._input_click_through is False:
                self._shift_timer.stop()
            self._refresh_hover()
            self._apply_opacity()
            self.update()
            return
        if not self._input_supported:
            self._input_interactive = True
            self._refresh_hover()
            self._apply_opacity()
            self.update()
            return
        interactive = self._shift_down or self._dragging or self._menu_open
        desired_click_through = not interactive
        if force or self._input_click_through != desired_click_through:
            if not self._apply_click_through(desired_click_through):
                self._degrade_input_mode()
                return
        self._input_interactive = interactive
        self._refresh_hover()
        self._apply_opacity()
        self.update()

    def _refresh_hover(self) -> None:
        if self._menu_open:
            self._hovered = True
        elif self._shift_down and self._input_interactive:
            self._hovered = self._cursor_inside()
        else:
            self._hovered = False

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._shift_timer.stop()
        self._metrics_timer.stop()
        self._dragging = False
        self._drag_offset = None
        try:
            self._input_mode.close()
        except Exception:
            log.debug("关闭 gp 输入模式失败", exc_info=True)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.shutdown()
        super().closeEvent(event)

    # ---------------------------------------------------------------- paint
    @staticmethod
    def _windows_hit_fill_enabled() -> bool:
        return sys.platform == "win32"

    def _palette(self) -> _Palette:
        if self._settings.fill_background:
            return _Palette(
                card=CARD_COLOR,
                border=CARD_BORDER_COLOR,
                primary=CARD_TEXT_COLOR,
                secondary=CARD_SECONDARY_TEXT_COLOR,
                divider=CARD_DIVIDER_COLOR,
                track=CARD_TRACK_COLOR,
                memory=MEMORY_COLOR,
                disk=DISK_COLOR,
                critical=CRITICAL_COLOR,
                halo=None,
            )
        return _Palette(
            card=None,
            border=RING_COLOR,
            primary=TEXT_COLOR,
            secondary=SECONDARY_TEXT_COLOR,
            divider=DIVIDER_COLOR,
            track=TRACK_COLOR,
            memory=LIGHT_MEMORY_COLOR,
            disk=LIGHT_DISK_COLOR,
            critical=LIGHT_CRITICAL_COLOR,
            halo=TEXT_HALO_COLOR,
        )

    def _card_box(self) -> QRectF:
        size = min(self.width(), self.height())
        margin = max(2.0, size * 0.07)
        return QRectF(
            margin,
            margin,
            max(1.0, self.width() - 2 * margin),
            max(1.0, self.height() - 2 * margin),
        )

    @staticmethod
    def _card_radius(box: QRectF) -> float:
        return max(2.0, min(box.width(), box.height()) * 0.14)

    def _is_compact_layout(self) -> bool:
        return min(self.width(), self.height()) < FULL_LAYOUT_MIN_DIAMETER

    def _content_rect(self, box: QRectF) -> QRectF:
        size = min(self.width(), self.height())
        pad = max(4.0, min(10.0, size * 0.045))
        return box.adjusted(pad, pad, -pad, -pad)

    def _section_rects(self, box: QRectF) -> tuple[QRectF, QRectF]:
        content = self._content_rect(box)
        half = content.height() / 2.0
        return (
            QRectF(content.left(), content.top(), content.width(), half),
            QRectF(
                content.left(),
                content.top() + half,
                content.width(),
                half,
            ),
        )

    def _pixel_font(
        self,
        pixel_size: float,
        *,
        min_px: int,
        max_px: int,
        bold: bool,
    ) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(
            max(min_px, min(max_px, int(round(pixel_size))))
        )
        font.setBold(bold)
        return font

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._windows_hit_fill_enabled():
            # Windows 分层窗口会跳过完全透明的像素，导致 Shift 按住时圆角
            # 外区域仍不可点击；铺一层 alpha=1/255 的底色让整个方形可命中。
            painter.fillRect(
                self.rect(), QColor(0, 0, 0, WIN32_HIT_FILL_ALPHA)
            )
        palette = self._palette()
        box = self._card_box()
        radius = self._card_radius(box)
        self._draw_card_background(painter, box, radius, palette)
        if min(self.width(), self.height()) < MIN_TEXT_DIAMETER:
            return
        self._draw_divider(painter, box, palette)
        if self._is_compact_layout():
            self._draw_compact_layout(painter, box, palette)
        else:
            self._draw_full_layout(painter, box, palette)

    def _draw_card_background(
        self,
        painter: QPainter,
        box: QRectF,
        radius: float,
        palette: _Palette,
    ) -> None:
        if palette.card is None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setBrush(palette.card)
        border_width = max(
            1.0, min(3.0, min(self.width(), self.height()) / 160.0)
        )
        painter.setPen(QPen(palette.border, border_width))
        painter.drawRoundedRect(box, radius, radius)

    def _draw_divider(
        self, painter: QPainter, box: QRectF, palette: _Palette
    ) -> None:
        size = min(self.width(), self.height())
        inset = max(6.0, size * 0.08)
        y = box.center().y()
        painter.setPen(QPen(palette.divider, 1.0))
        painter.drawLine(
            QPointF(box.left() + inset, y),
            QPointF(box.right() - inset, y),
        )

    def _bar_height(
        self, size: float, *, compact: bool, critical: bool
    ) -> float:
        if compact:
            base = max(3.0, min(12.0, size * 0.035))
        else:
            base = max(4.0, min(24.0, size * 0.035))
        return base * (CRITICAL_BAR_SCALE if critical else 1.0)

    def _draw_full_layout(
        self, painter: QPainter, box: QRectF, palette: _Palette
    ) -> None:
        sections = self._section_rects(box)
        entries = (
            ("内存", self._usage.memory, palette.memory, self._draw_memory_icon),
            ("磁盘", self._usage.disk, palette.disk, self._draw_disk_icon),
        )
        for rect, (label, usage, accent, icon) in zip(sections, entries):
            self._draw_full_section(
                painter, rect, label, usage, accent, icon, palette
            )

    def _draw_full_section(
        self,
        painter: QPainter,
        rect: QRectF,
        label: str,
        usage: UsageStat,
        accent: QColor,
        icon: Callable[[QPainter, QRectF, QColor], None],
        palette: _Palette,
    ) -> None:
        size = min(self.width(), self.height())
        label_font = self._pixel_font(
            size * 0.065, min_px=9, max_px=52, bold=True
        )
        percent_font = self._pixel_font(
            size * 0.095, min_px=12, max_px=96, bold=True
        )
        detail_font = self._pixel_font(
            size * 0.052, min_px=8, max_px=40, bold=False
        )
        gap = max(3.0, size * 0.03)
        critical = is_critical(usage.percent)
        bar_height = self._bar_height(
            size, compact=False, critical=critical
        )
        detail_height = float(QFontMetrics(detail_font).height())
        header_height = max(
            float(QFontMetrics(percent_font).height()),
            size * 0.12,
        )
        icon_size = max(
            10.0, min(header_height * 0.9, size * 0.13)
        )
        block_height = (
            header_height + gap + bar_height + gap + detail_height
        )
        top = rect.top() + max(0.0, (rect.height() - block_height) / 2.0)

        icon_rect = QRectF(
            rect.left(),
            top + (header_height - icon_size) / 2.0,
            icon_size,
            icon_size,
        )
        icon(painter, icon_rect, accent)
        label_left = icon_rect.right() + max(2.0, size * 0.03)
        label_right = rect.left() + rect.width() * 0.55
        label_rect = QRectF(
            label_left,
            top,
            max(0.0, label_right - label_left),
            header_height,
        )
        percent_rect = QRectF(
            rect.left() + rect.width() * 0.55,
            top,
            rect.width() * 0.45,
            header_height,
        )
        self._draw_text(
            painter,
            label_rect,
            label,
            label_font,
            palette.primary,
            palette.halo,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self._draw_text(
            painter,
            percent_rect,
            format_percent(usage.percent),
            percent_font,
            palette.primary,
            palette.halo,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        bar_top = top + header_height + gap
        bar_rect = QRectF(rect.left(), bar_top, rect.width(), bar_height)
        bar_color = palette.critical if critical else accent
        self._draw_bar(
            painter, bar_rect, usage.percent, bar_color, palette.track
        )

        detail_top = bar_rect.bottom() + gap
        detail_rect = QRectF(
            rect.left(),
            detail_top,
            rect.width(),
            detail_height,
        )
        self._draw_text(
            painter,
            detail_rect,
            format_usage_detail(usage.used, usage.total),
            detail_font,
            palette.secondary,
            palette.halo,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    def _draw_compact_layout(
        self, painter: QPainter, box: QRectF, palette: _Palette
    ) -> None:
        sections = self._section_rects(box)
        size = min(self.width(), self.height())
        label_font = self._pixel_font(
            size * 0.10, min_px=8, max_px=24, bold=True
        )
        percent_font = self._pixel_font(
            size * 0.115, min_px=9, max_px=36, bold=True
        )
        label_metrics = QFontMetrics(label_font)
        percent_metrics = QFontMetrics(percent_font)
        header_height = float(
            max(label_metrics.height(), percent_metrics.height())
        )
        gap = max(3.0, size * 0.035)

        entries = (
            ("内存", self._usage.memory, palette.memory),
            ("磁盘", self._usage.disk, palette.disk),
        )
        for rect, (label, usage, accent) in zip(sections, entries):
            critical = is_critical(usage.percent)
            bar_height = self._bar_height(
                size, compact=True, critical=critical
            )
            block_height = header_height + gap + bar_height
            top = rect.top() + max(
                0.0, (rect.height() - block_height) / 2.0
            )
            percent_text = format_percent(usage.percent)
            label_width = float(label_metrics.horizontalAdvance(label))
            percent_width = float(
                percent_metrics.horizontalAdvance(percent_text)
            )
            show_label = (
                label_width + percent_width + max(2.0, size * 0.04)
                <= rect.width()
            )
            if show_label:
                label_rect = QRectF(
                    rect.left(), top, rect.width() * 0.45, header_height
                )
                percent_rect = QRectF(
                    rect.left() + rect.width() * 0.45,
                    top,
                    rect.width() * 0.55,
                    header_height,
                )
                self._draw_text(
                    painter,
                    label_rect,
                    label,
                    label_font,
                    palette.primary,
                    palette.halo,
                    Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter,
                )
            else:
                percent_rect = QRectF(
                    rect.left(), top, rect.width(), header_height
                )
            self._draw_text(
                painter,
                percent_rect,
                percent_text,
                percent_font,
                palette.primary,
                palette.halo,
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter,
            )
            bar_rect = QRectF(
                rect.left(),
                top + header_height + gap,
                rect.width(),
                bar_height,
            )
            bar_color = palette.critical if critical else accent
            self._draw_bar(
                painter, bar_rect, usage.percent, bar_color, palette.track
            )

    def _draw_text(
        self,
        painter: QPainter,
        rect: QRectF,
        text: str,
        font: QFont,
        color: QColor,
        halo: QColor | None,
        alignment: Qt.AlignmentFlag,
    ) -> None:
        if not text or rect.width() <= 0 or rect.height() <= 0:
            return
        painter.setFont(font)
        if halo is not None:
            halo_width = max(
                1.5, min(3.0, min(self.width(), self.height()) / 70.0)
            )
            painter.setPen(QPen(halo, halo_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawText(rect, int(alignment), text)
        painter.setPen(QPen(color))
        painter.setBrush(color)
        painter.drawText(rect, int(alignment), text)

    def _draw_bar(
        self,
        painter: QPainter,
        rect: QRectF,
        percent: float | None,
        color: QColor,
        track: QColor,
    ) -> None:
        radius = rect.height() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)
        if percent is None:
            return
        try:
            value = float(percent)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return
        value = max(0.0, min(100.0, value))
        if value <= 0:
            return
        width = rect.width() * value / 100.0
        width = max(0.0, min(width, rect.width()))
        if width <= 0:
            return
        fill_radius = min(radius, width / 2.0)
        fill = QRectF(rect.left(), rect.top(), width, rect.height())
        painter.setBrush(color)
        painter.drawRoundedRect(fill, fill_radius, fill_radius)

    def _draw_memory_icon(
        self, painter: QPainter, rect: QRectF, color: QColor
    ) -> None:
        painter.save()
        pen_width = max(1.0, min(4.0, rect.width() * 0.09))
        pen = QPen(color, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        body = rect.adjusted(
            rect.width() * 0.18,
            rect.height() * 0.24,
            -rect.width() * 0.18,
            -rect.height() * 0.24,
        )
        painter.drawRoundedRect(
            body, rect.width() * 0.10, rect.width() * 0.10
        )
        pin_length = rect.height() * 0.15
        for fraction in (0.30, 0.50, 0.70):
            x = body.left() + body.width() * fraction
            painter.drawLine(
                QPointF(x, body.top()),
                QPointF(x, body.top() - pin_length),
            )
            painter.drawLine(
                QPointF(x, body.bottom()),
                QPointF(x, body.bottom() + pin_length),
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        cell_width = body.width() * 0.16
        cell_height = body.height() * 0.52
        for fraction in (0.18, 0.42, 0.66):
            x = body.left() + body.width() * fraction
            painter.drawRoundedRect(
                QRectF(
                    x,
                    body.center().y() - cell_height / 2.0,
                    cell_width,
                    cell_height,
                ),
                cell_width * 0.25,
                cell_width * 0.25,
            )
        painter.restore()

    def _draw_disk_icon(
        self, painter: QPainter, rect: QRectF, color: QColor
    ) -> None:
        painter.save()
        pen_width = max(1.0, min(4.0, rect.width() * 0.09))
        pen = QPen(color, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(
            rect.left() + rect.width() * 0.08,
            rect.top() + rect.height() * 0.24,
            rect.width() * 0.84,
            rect.height() * 0.52,
        )
        painter.drawRoundedRect(
            body, rect.width() * 0.10, rect.width() * 0.10
        )
        line_y = body.top() + body.height() * 0.58
        painter.drawLine(
            QPointF(
                body.left() + body.width() * 0.12,
                line_y,
            ),
            QPointF(
                body.right() - body.width() * 0.12,
                line_y,
            ),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        led_radius = max(0.8, rect.width() * 0.035)
        painter.drawEllipse(
            QPointF(
                body.right() - body.width() * 0.18,
                line_y + body.height() * 0.22,
            ),
            led_radius,
            led_radius,
        )
        slot_height = max(1.0, rect.height() * 0.05)
        painter.drawRoundedRect(
            QRectF(
                body.left() + body.width() * 0.12,
                line_y + body.height() * 0.16,
                body.width() * 0.28,
                slot_height,
            ),
            slot_height / 2.0,
            slot_height / 2.0,
        )
        painter.restore()

    # --------------------------------------------------------------- events
    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._menu_open:
            modifiers = getattr(event, "modifiers", None)
            if callable(modifiers):
                value = modifiers()
                if not self._input_supported:
                    self._set_shift_down(
                        bool(value & Qt.KeyboardModifier.ShiftModifier)
                    )
                elif value & Qt.KeyboardModifier.ShiftModifier:
                    # 输入事件里的 Shift 比 30ms 轮询更新，先同步一次。
                    self._set_shift_down(True)
            self._refresh_hover()
            self._apply_opacity()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._menu_open:
            self._hovered = False
            self._apply_opacity()
        super().leaveEvent(event)

    def _cursor_inside(self) -> bool:
        """Whether the mouse is currently over the widget's window rect."""
        try:
            return self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        except (TypeError, RuntimeError):
            return False

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # 右键菜单只由 Shift+右键激活；没有 Shift 时窗口本来应处于穿透
        # 状态，这里再挡一次轮询间隙里的竞态。
        if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            event.ignore()
            return
        menu = QMenu(self)
        settings_action = menu.addAction("设置")
        quit_action = menu.addAction("退出")
        # 菜单弹出会抢走鼠标并触发 leaveEvent；先锁定悬停状态，菜单
        # 关闭后再根据鼠标是否仍在悬浮窗上恢复。
        self._shift_down = True
        self._menu_open = True
        self._sync_input_mode(force=True)
        try:
            chosen = menu.exec(event.globalPos())
        finally:
            self._menu_open = False
            self._sync_input_mode(force=True)
        if chosen is settings_action:
            # 等 QMenu.exec() 完全退出后再打开对话框，避免键鼠焦点竞争
            # 导致第一次点击没有反应。
            QTimer.singleShot(0, self._on_open_settings)
        elif chosen is quit_action:
            # “退出”关闭 gp 插件本身（helper 退出），QuickTools 继续运行。
            self._emit(EVENT_CLOSED)
            self._on_exit()
            self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and shift
            and not self._dragging
        ):
            self._dragging = True
            # 事件里的 Shift 比轮询更新，立即锁定交互状态。
            self._set_shift_down(True)
            # 固定按下时的全局偏移。移动过程中不再用局部坐标，避免窗口
            # 自身移动导致反馈抖动。
            self._drag_offset = (
                event.globalPosition().toPoint() - self.pos()
            )
            self._sync_input_mode(force=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        modifiers = event.modifiers()
        if not self._input_supported:
            self._set_shift_down(
                bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            )
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._set_shift_down(True)
        if self._dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_offset = None
            self._finish_drag()
            # 拖动期间即使松开 Shift 也保持可交互；释放左键后再决定
            # 是否恢复穿透。
            self._sync_input_mode(force=True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        # 隐藏时取消半途的拖动，不保存中间位置。
        self._shift_timer.stop()
        self._metrics_timer.stop()
        self._dragging = False
        self._drag_offset = None
        super().hideEvent(event)

    def _finish_drag(self) -> None:
        """Clamp the widget on screen, persist the position and report it."""
        rect = rect_for(self)
        area = screen_for_rect(rect, screen_areas())
        if area is not None:
            x, y = clamp_into(rect, area)
            if (x, y) != (self.x(), self.y()):
                self.move(x, y)
            self._settings = replace(
                self._settings, x=x, y=y, screen=area.name or None
            )
        else:
            self._settings = replace(
                self._settings, x=self.x(), y=self.y(), screen=None
            )
        self._persist(self._settings)
        self._emit(f"position {self.x()} {self.y()}")
