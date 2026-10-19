from __future__ import annotations

import sys
from pathlib import Path

import pytest

from quicktools import autostart

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="XDG autostart is Linux-only"
)


@pytest.fixture()
def xdg_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_startup_command_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart.sys, "executable", "/opt/venv/bin/python")
    monkeypatch.delattr(autostart.sys, "frozen", raising=False)
    assert autostart.startup_command() == [
        "/opt/venv/bin/python",
        "-m",
        "quicktools",
        "--background",
    ]


def test_startup_command_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autostart.sys, "executable", "/opt/QuickTools/QuickTools")
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    assert autostart.startup_command() == [
        "/opt/QuickTools/QuickTools",
        "--background",
    ]


def test_windows_command_quotes_paths_with_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        autostart.sys, "executable", r"C:\Program Files\QuickTools\QuickTools.exe"
    )
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    assert (
        autostart._windows_command()
        == r'"C:\Program Files\QuickTools\QuickTools.exe" --background'
    )


def test_quote_exec_arg_escapes_desktop_entry_specials() -> None:
    assert autostart._quote_exec_arg("/plain/path") == '"/plain/path"'
    assert (
        autostart._quote_exec_arg('/a b/$x`y"z\\w/%')
        == '"/a b/\\$x\\`y\\"z\\\\w/%%"'
    )


@linux_only
def test_linux_enable_creates_desktop_entry(
    xdg_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autostart.sys, "executable", "/opt/venv/bin/python")
    monkeypatch.delattr(autostart.sys, "frozen", raising=False)
    assert not autostart.is_enabled()

    autostart.enable()

    path = xdg_home / "autostart" / "quicktools.desktop"
    assert path.is_file()
    assert autostart.is_enabled()
    content = path.read_text(encoding="utf-8")
    assert content.startswith("[Desktop Entry]\n")
    assert "Type=Application\n" in content
    assert "Terminal=false\n" in content
    assert (
        'Exec="/opt/venv/bin/python" "-m" "quicktools" "--background"\n' in content
    )
    assert not list(path.parent.glob("*.tmp"))


@linux_only
def test_linux_disable_removes_entry_and_is_idempotent(xdg_home: Path) -> None:
    autostart.enable()
    assert autostart.is_enabled()

    autostart.disable()
    assert not autostart.is_enabled()
    autostart.disable()
    assert not autostart.is_enabled()


@linux_only
def test_linux_enable_overwrites_stale_entry(xdg_home: Path) -> None:
    path = xdg_home / "autostart" / "quicktools.desktop"
    path.parent.mkdir(parents=True)
    path.write_text("stale", encoding="utf-8")

    autostart.enable()

    assert "Exec=" in path.read_text(encoding="utf-8")


@linux_only
def test_xdg_config_home_falls_back_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    expected = tmp_path / ".config" / "autostart" / "quicktools.desktop"
    assert autostart.linux_desktop_file() == expected

    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    assert autostart.linux_desktop_file() == expected

    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert autostart.linux_desktop_file() == expected


@linux_only
def test_linux_mechanism_hint_mentions_desktop_file(xdg_home: Path) -> None:
    hint = autostart.mechanism_hint()
    assert str(xdg_home) in hint
    assert "自启动文件" in hint
