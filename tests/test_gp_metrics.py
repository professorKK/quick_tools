from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from quicktools.plugins.gp import metrics
from quicktools.plugins.gp.metrics import (
    GIB,
    METRICS_INTERVAL_MS,
    MetricsSampler,
    SystemUsage,
    UsageStat,
    format_gb,
    format_percent,
    format_usage_detail,
    parse_meminfo,
    system_disk_path,
    usage_from_counts,
)

_MEMINFO = """\
MemTotal:       16777216 kB
MemFree:         2000000 kB
MemAvailable:    7025459 kB
Buffers:          100000 kB
Cached:          3000000 kB
"""

_MEMINFO_WITHOUT_AVAILABLE = """\
MemTotal:       16777216 kB
MemFree:         2000000 kB
Buffers:          100000 kB
Cached:          3000000 kB
"""


def test_parse_meminfo_uses_mem_available() -> None:
    usage = parse_meminfo(_MEMINFO)
    assert usage.total == 16 * GIB
    assert usage.used == (16777216 - 7025459) * 1024
    assert usage.percent is not None
    assert 58.0 < usage.percent < 58.2


def test_parse_meminfo_falls_back_to_free_buffers_cached() -> None:
    usage = parse_meminfo(_MEMINFO_WITHOUT_AVAILABLE)
    assert usage.total == 16 * GIB
    assert usage.used == (16777216 - 5100000) * 1024
    assert usage.percent is not None
    assert 69.5 < usage.percent < 69.7


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no colon here",
        "MemTotal: 0 kB",
        "MemTotal: not-a-number kB",
        "MemFree: 100 kB",
    ],
)
def test_parse_meminfo_invalid_returns_empty(text: str) -> None:
    assert parse_meminfo(text) == UsageStat()


def test_usage_from_counts_clamps_and_handles_zero_total() -> None:
    assert usage_from_counts(100, 400).percent == 25.0
    assert usage_from_counts(500, 400).used == 400
    assert usage_from_counts(-10, 400).used == 0
    assert usage_from_counts(10, 0) == UsageStat()
    assert usage_from_counts(None, 400) == UsageStat()
    assert usage_from_counts(10, None) == UsageStat()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0%"),
        (42.4, "42%"),
        (42.5, "43%"),
        (99.6, "100%"),
        (120, "100%"),
        (-5, "0%"),
        (None, "--%"),
        (float("nan"), "--%"),
        (float("inf"), "--%"),
        ("bad", "--%"),
        (True, "--%"),
    ],
)
def test_format_percent(value: object, expected: str) -> None:
    assert format_percent(value) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (int(6.7 * GIB), "6.7"),
        (16 * GIB, "16"),
        (340 * GIB, "340"),
        (int(9.5 * GIB), "9.5"),
        (int(9.96 * GIB), "10"),
        (0, "0"),
        (None, "--"),
        (-1, "--"),
        (True, "--"),
    ],
)
def test_format_gb(value: object, expected: str) -> None:
    assert format_gb(value) == expected  # type: ignore[arg-type]


def test_format_usage_detail() -> None:
    assert format_usage_detail(int(6.7 * GIB), 16 * GIB) == "6.7 / 16 GB"
    assert format_usage_detail(340 * GIB, 500 * GIB) == "340 / 500 GB"
    assert format_usage_detail(None, 16 * GIB) == "--"
    assert format_usage_detail(1 * GIB, None) == "--"


def test_system_disk_path_follows_platform(monkeypatch) -> None:
    monkeypatch.setattr(metrics.sys, "platform", "win32")
    monkeypatch.setenv("SystemDrive", "D:")
    assert system_disk_path() == "D:\\"
    monkeypatch.delenv("SystemDrive", raising=False)
    assert system_disk_path() == "C:\\"
    monkeypatch.setattr(metrics.sys, "platform", "linux")
    assert system_disk_path() == "/"


def test_metrics_sampler_reads_both_metrics() -> None:
    memory = UsageStat(percent=42.0, used=1, total=2)
    disk = UsageStat(percent=68.0, used=3, total=4)
    sampler = MetricsSampler(
        memory_reader=lambda: memory,
        disk_reader=lambda: disk,
    )
    assert sampler.sample() == SystemUsage(memory=memory, disk=disk)


def test_metrics_sampler_logs_failure_once_and_recovers(caplog) -> None:
    state = {"fail": True, "value": UsageStat(percent=50.0, used=1, total=2)}

    def reader() -> UsageStat:
        if state["fail"]:
            raise OSError("read failed")
        return state["value"]

    sampler = MetricsSampler(memory_reader=reader, disk_reader=reader)
    with caplog.at_level(logging.WARNING, logger=metrics.__name__):
        first = sampler.sample()
        second = sampler.sample()
    assert first == SystemUsage.empty()
    assert second == SystemUsage.empty()
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    # 内存和磁盘各一次；重复失败不再刷日志。
    assert len(warnings) == 2

    state["fail"] = False
    with caplog.at_level(logging.INFO, logger=metrics.__name__):
        recovered = sampler.sample()
    assert recovered.memory == state["value"]
    assert recovered.disk == state["value"]
    assert any(
        record.levelno == logging.INFO for record in caplog.records
    )


def test_metrics_sampler_rejects_invalid_reader_result() -> None:
    sampler = MetricsSampler(
        memory_reader=lambda: None,  # type: ignore[return-value]
        disk_reader=lambda: UsageStat(),
    )
    usage = sampler.sample()
    assert usage.memory == UsageStat()
    assert usage.disk == UsageStat()


def test_metrics_interval_is_positive() -> None:
    assert METRICS_INTERVAL_MS == 2000


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="仅 Linux 读取 /proc/meminfo"
)
def test_read_memory_usage_linux_smoke() -> None:
    if not Path("/proc/meminfo").exists():
        pytest.skip("/proc/meminfo 不存在")
    usage = metrics.read_memory_usage()
    assert usage.total and usage.total > 0
    assert usage.used is not None and 0 <= usage.used <= usage.total


def test_read_disk_usage_smoke() -> None:
    usage = metrics.read_disk_usage()
    assert usage.total and usage.total > 0
    assert usage.used is not None and 0 <= usage.used <= usage.total


@pytest.mark.skipif(
    sys.platform != "win32", reason="仅 Windows 调用 GlobalMemoryStatusEx"
)
def test_read_memory_usage_windows_smoke() -> None:
    usage = metrics.read_memory_usage()
    assert usage.total and usage.total > 0
