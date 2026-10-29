from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quicktools import ui_theme


def test_center_on_screen_uses_monitor_under_pointer(monkeypatch) -> None:
    class FakeWindow:
        def __init__(self) -> None:
            self.geometry_value = ""

        def update_idletasks(self) -> None:
            pass

        def winfo_pointerx(self) -> int:
            return 2500

        def winfo_pointery(self) -> int:
            return 100

        def winfo_screenwidth(self) -> int:
            return 1920

        def winfo_screenheight(self) -> int:
            return 1080

        def geometry(self, value: str) -> None:
            self.geometry_value = value

    monkeypatch.setattr(
        ui_theme, "work_area_for_point", lambda _point: (1920, 0, 1920, 1080)
    )
    window = FakeWindow()
    ui_theme.center_on_screen(window, 800, 600)
    assert window.geometry_value == "800x600+2480+240"


_TWO_MONITOR_OUTPUT = (
    "Monitors: 2\n"
    " 0: +*eDP-1 2560/344x1600/215+0+0  eDP-1\n"
    " 1: +HDMI-1 1920/509x1080/286+-1920+0  HDMI-1\n"
)


def test_x11_monitor_rects_uses_current_and_parses(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = _TWO_MONITOR_OUTPUT

    monkeypatch.setattr(ui_theme.sys, "platform", "linux")
    monkeypatch.setattr(ui_theme.shutil, "which", lambda _name: "/usr/bin/xrandr")
    monkeypatch.setattr(
        ui_theme.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or Result(),
    )

    assert ui_theme._x11_monitor_rects() == [
        (0, 0, 2560, 1600),
        (-1920, 0, 1920, 1080),
    ]
    assert calls == [["/usr/bin/xrandr", "--current", "--listmonitors"]]


def test_x11_monitor_rects_returns_empty_on_failure(monkeypatch) -> None:
    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(ui_theme.sys, "platform", "linux")
    monkeypatch.setattr(ui_theme.shutil, "which", lambda _name: "/usr/bin/xrandr")
    monkeypatch.setattr(
        ui_theme.subprocess, "run", lambda *_args, **_kwargs: Result()
    )
    assert ui_theme._x11_monitor_rects() == []

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="xrandr", timeout=2)

    monkeypatch.setattr(ui_theme.subprocess, "run", time_out)
    assert ui_theme._x11_monitor_rects() == []

    monkeypatch.setattr(ui_theme.shutil, "which", lambda _name: None)
    assert ui_theme._x11_monitor_rects() == []


def test_work_area_for_point_uses_cached_monitors(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = _TWO_MONITOR_OUTPUT

    monkeypatch.setattr(ui_theme.sys, "platform", "linux")
    monkeypatch.setattr(ui_theme.shutil, "which", lambda _name: "/usr/bin/xrandr")
    monkeypatch.setattr(
        ui_theme.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or Result(),
    )
    monkeypatch.setattr(ui_theme, "_x11_monitor_cache", (0.0, []))

    assert ui_theme.work_area_for_point((100, 100)) == (0, 0, 2560, 1600)
    assert ui_theme.work_area_for_point((-1000, 500)) == (-1920, 0, 1920, 1080)
    assert len(calls) == 1


def test_reveal_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ui_theme.reveal_in_file_manager(tmp_path / "missing.png")


def test_reveal_linux_uses_file_manager1(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "shot.png"
    target.write_bytes(b"png")
    calls: list[list[str]] = []
    opened: list[Path] = []

    class Result:
        returncode = 0

    monkeypatch.setattr(ui_theme.sys, "platform", "linux")
    monkeypatch.setattr(
        ui_theme.shutil, "which", lambda _name: "/usr/bin/dbus-send"
    )
    monkeypatch.setattr(
        ui_theme.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(args) or Result(),
    )
    monkeypatch.setattr(
        ui_theme, "open_in_file_manager", lambda path: opened.append(path)
    )

    ui_theme.reveal_in_file_manager(target)

    assert calls
    assert "org.freedesktop.FileManager1.ShowItems" in calls[0]
    assert f"array:string:{target.resolve().as_uri()}" in calls[0]
    assert opened == []


def test_reveal_linux_falls_back_to_parent(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "shot.png"
    target.write_bytes(b"png")
    opened: list[Path] = []

    class Result:
        returncode = 1

    monkeypatch.setattr(ui_theme.sys, "platform", "linux")
    monkeypatch.setattr(
        ui_theme.shutil, "which", lambda _name: "/usr/bin/dbus-send"
    )
    monkeypatch.setattr(
        ui_theme.subprocess,
        "run",
        lambda *_args, **_kwargs: Result(),
    )
    monkeypatch.setattr(
        ui_theme, "open_in_file_manager", lambda path: opened.append(path)
    )

    ui_theme.reveal_in_file_manager(target)

    assert opened == [tmp_path]


def test_reveal_windows_selects_file(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "shot.png"
    target.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setattr(ui_theme.sys, "platform", "win32")
    monkeypatch.setattr(
        ui_theme.subprocess, "Popen", lambda args: calls.append(args)
    )

    ui_theme.reveal_in_file_manager(target)

    assert calls == [["explorer", f"/select,{target}"]]


def test_open_url_opens_default_browser(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        ui_theme.webbrowser,
        "open",
        lambda url: opened.append(url) or True,
    )

    assert ui_theme.open_url("https://example.com/repo") is True
    assert opened == ["https://example.com/repo"]


def test_open_url_returns_false_when_browser_fails(monkeypatch) -> None:
    def explode(_url: str) -> bool:
        raise RuntimeError("no browser")

    monkeypatch.setattr(ui_theme.webbrowser, "open", explode)

    assert ui_theme.open_url("https://example.com/repo") is False
