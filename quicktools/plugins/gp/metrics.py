"""gp 悬浮窗使用的系统内存与磁盘占用采样。

纯标准库实现，不导入 Qt，便于在没有显示环境的测试里直接验证解析和
格式化逻辑。Linux 读取 ``/proc/meminfo``，Windows 使用
``GlobalMemoryStatusEx``；磁盘统一用 ``shutil.disk_usage()`` 统计系统盘。
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# 悬浮窗刷新周期；放在这里方便测试和文档引用同一个值。
METRICS_INTERVAL_MS = 2000

# 达到该百分比时，悬浮窗用红色加粗进度条提醒。
CRITICAL_USAGE_PERCENT = 95.0

GIB = 1024**3
MEMINFO_PATH = Path("/proc/meminfo")


@dataclass(frozen=True)
class UsageStat:
    """一项占用指标；字段为 ``None`` 表示本次读取失败或不可用。"""

    percent: float | None = None
    used: int | None = None
    total: int | None = None


@dataclass(frozen=True)
class SystemUsage:
    """一次采样得到的内存和磁盘快照。"""

    memory: UsageStat = field(default_factory=UsageStat)
    disk: UsageStat = field(default_factory=UsageStat)

    @classmethod
    def empty(cls) -> "SystemUsage":
        return cls()


def usage_from_counts(used: int | None, total: int | None) -> UsageStat:
    """把字节数转换为百分比；无效总量返回空指标。"""
    if used is None or total is None:
        return UsageStat()
    try:
        total_value = int(total)
        used_value = int(used)
    except (TypeError, ValueError):
        return UsageStat()
    if total_value <= 0:
        return UsageStat()
    used_value = max(0, min(used_value, total_value))
    return UsageStat(
        percent=used_value * 100.0 / total_value,
        used=used_value,
        total=total_value,
    )


def parse_meminfo(text: str) -> UsageStat:
    """解析 ``/proc/meminfo`` 文本，优先使用 ``MemAvailable``。"""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, rest = line.partition(":")
        if not separator:
            continue
        parts = rest.split()
        if not parts:
            continue
        try:
            values[key.strip()] = int(parts[0]) * 1024
        except ValueError:
            continue
    total = values.get("MemTotal")
    if not total:
        return UsageStat()
    available = values.get("MemAvailable")
    if available is None:
        available = (
            values.get("MemFree", 0)
            + values.get("Buffers", 0)
            + values.get("Cached", 0)
        )
    return usage_from_counts(max(0, total - available), total)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _read_windows_memory() -> UsageStat:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GlobalMemoryStatusEx.argtypes = [
        ctypes.POINTER(_MemoryStatusEx)
    ]
    kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    total = int(status.ullTotalPhys)
    available = int(status.ullAvailPhys)
    return usage_from_counts(max(0, total - available), total)


def read_memory_usage() -> UsageStat:
    """读取当前内存占用；不支持的平台返回空指标。"""
    if sys.platform == "win32":
        return _read_windows_memory()
    if sys.platform.startswith("linux"):
        return parse_meminfo(
            MEMINFO_PATH.read_text(encoding="utf-8", errors="replace")
        )
    return UsageStat()


def system_disk_path() -> str:
    """返回要统计的磁盘根路径：Windows 系统盘，其他平台 ``/``。"""
    if sys.platform == "win32":
        drive = os.environ.get("SystemDrive", "C:")
        return drive if drive.endswith("\\") else drive + "\\"
    return "/"


def read_disk_usage() -> UsageStat:
    usage = shutil.disk_usage(system_disk_path())
    return usage_from_counts(int(usage.used), int(usage.total))


def is_critical(percent: float | None) -> bool:
    """Whether a usage percentage should be shown as a critical warning."""
    if percent is None or isinstance(percent, bool):
        return False
    try:
        value = float(percent)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value >= CRITICAL_USAGE_PERCENT


def format_percent(value: float | None) -> str:
    """格式化为整数百分比；无效值显示 ``--%``。"""
    if value is None or isinstance(value, bool):
        return "--%"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--%"
    if not math.isfinite(number):
        return "--%"
    number = max(0.0, min(100.0, number))
    return f"{int(number + 0.5)}%"


def format_gb(value: int | None) -> str:
    """字节数转 GB 文本；小于 10GB 保留一位小数。"""
    if value is None or isinstance(value, bool):
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number) or number < 0:
        return "--"
    gigabytes = number / GIB
    if gigabytes < 10:
        text = f"{gigabytes:.1f}"
        return text[:-2] if text.endswith(".0") else text
    return str(int(gigabytes + 0.5))


def format_usage_detail(used: int | None, total: int | None) -> str:
    """格式化为参考图里的 ``已用 / 总量 GB``；缺任一项返回 ``--``。"""
    used_text = format_gb(used)
    total_text = format_gb(total)
    if used_text == "--" or total_text == "--":
        return "--"
    return f"{used_text} / {total_text} GB"


class MetricsSampler:
    """周期采样器；同一指标的失败只记一次日志，恢复后再记一条。"""

    def __init__(
        self,
        memory_reader: Callable[[], UsageStat] = read_memory_usage,
        disk_reader: Callable[[], UsageStat] = read_disk_usage,
    ) -> None:
        self._memory_reader = memory_reader
        self._disk_reader = disk_reader
        self._failed: set[str] = set()

    def sample(self) -> SystemUsage:
        return SystemUsage(
            memory=self._sample_one("内存", "memory", self._memory_reader),
            disk=self._sample_one("磁盘", "disk", self._disk_reader),
        )

    def _sample_one(
        self,
        label: str,
        key: str,
        reader: Callable[[], UsageStat],
    ) -> UsageStat:
        try:
            value = reader()
        except Exception:
            if key not in self._failed:
                self._failed.add(key)
                log.warning(
                    "读取系统%s占用失败，悬浮窗显示 --", label, exc_info=True
                )
            return UsageStat()
        if not isinstance(value, UsageStat):
            if key not in self._failed:
                self._failed.add(key)
                log.warning("读取系统%s占用返回无效数据，悬浮窗显示 --", label)
            return UsageStat()
        if key in self._failed:
            self._failed.remove(key)
            log.info("系统%s占用读取已恢复", label)
        return value


def read_system_usage() -> SystemUsage:
    """一次性读取两项指标，供调试和测试使用。"""
    return MetricsSampler().sample()
