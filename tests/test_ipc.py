from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from quicktools.ipc import (
    IpcServer,
    is_valid_command,
    send_command,
    send_tray_menu,
)

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Unix socket path is exercised on POSIX"
)


def test_ipc_commands(tmp_path: Path) -> None:
    endpoint = tmp_path / "quicktools-test.sock"
    received: list[str] = []
    server = IpcServer(received.append, endpoint=endpoint)
    assert server.start()
    try:
        # ping is answered but must not trigger a UI command.
        assert send_command("ping", endpoint=endpoint)
        for command in (
            "show",
            "toggle",
            "settings",
            "quit",
            "plugin screenshot capture_region",
        ):
            assert send_command(command, endpoint=endpoint)
        deadline = time.time() + 2
        while len(received) < 5 and time.time() < deadline:
            time.sleep(0.02)
        assert received == [
            "show",
            "toggle",
            "settings",
            "quit",
            "plugin screenshot capture_region",
        ]
    finally:
        server.stop()
    assert not endpoint.exists()


def test_second_server_is_rejected(tmp_path: Path) -> None:
    endpoint = tmp_path / "quicktools-test.sock"
    received: list[str] = []
    first = IpcServer(received.append, endpoint=endpoint)
    second = IpcServer(received.append, endpoint=endpoint)
    assert first.start()
    try:
        assert not second.start()
        # The rejected start probes the first server with "show".
        deadline = time.time() + 2
        while not received and time.time() < deadline:
            time.sleep(0.02)
        assert received == ["show"]
    finally:
        first.stop()
        second.stop()


def test_plugin_command_validation() -> None:
    assert is_valid_command("plugin screenshot capture_region")
    assert is_valid_command("plugin my-plugin capture_region")
    assert not is_valid_command("plugin screenshot")
    assert not is_valid_command("plugin Screenshot capture")
    assert not is_valid_command("plugin screenshot capture region")
    assert not is_valid_command("plugin screenshot " + "x" * 64)
    with pytest.raises(ValueError):
        send_command("plugin screenshot")


def test_send_without_server_returns_false(tmp_path: Path) -> None:
    assert not send_command("toggle", endpoint=tmp_path / "missing.sock")


def test_tray_menu_payload(tmp_path: Path) -> None:
    endpoint = tmp_path / "quicktools-test.sock"
    received: list[str] = []
    server = IpcServer(received.append, endpoint=endpoint)
    assert server.start()
    try:
        assert send_tray_menu(2138, 25, endpoint=endpoint)
        deadline = time.time() + 2
        while not received and time.time() < deadline:
            time.sleep(0.02)
        assert received == ["menu 2138 25"]
    finally:
        server.stop()
