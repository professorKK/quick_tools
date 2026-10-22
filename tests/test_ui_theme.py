from __future__ import annotations

from pathlib import Path

import pytest

from quicktools import ui_theme


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
