"""Small local IPC channel used for single-instance and --toggle."""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable

from . import paths

log = logging.getLogger(__name__)

VALID_COMMANDS = frozenset({"toggle", "show", "settings", "quit", "ping"})
WINDOWS_PORT = 50517
_MAX_MESSAGE = 64


def _endpoint_path(endpoint: Path | None = None) -> Path:
    return endpoint or paths.ipc_runtime_file()


def _connect(endpoint: Path | None = None) -> socket.socket:
    if sys.platform == "win32":
        sock = socket.create_connection(("127.0.0.1", WINDOWS_PORT), timeout=0.6)
        return sock
    path = _endpoint_path(endpoint)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(0.6)
    sock.connect(str(path))
    return sock


def _send_payload(payload: str, endpoint: Path | None = None) -> bool:
    if sys.platform != "win32":
        path = _endpoint_path(endpoint)
        if not path.exists():
            return False
    try:
        with _connect(endpoint) as sock:
            sock.sendall((payload + "\n").encode("ascii"))
            sock.settimeout(0.6)
            reply = sock.recv(16)
        return reply.startswith(b"OK")
    except OSError:
        return False


def send_command(command: str, endpoint: Path | None = None) -> bool:
    """Send a command to the primary instance. Returns True on success."""
    if command not in VALID_COMMANDS:
        raise ValueError(f"unknown IPC command: {command}")
    return _send_payload(command, endpoint)


def send_tray_menu(x: int, y: int, endpoint: Path | None = None) -> bool:
    """Ask the primary instance to show the tray menu at screen coordinates."""
    return _send_payload(f"menu {int(x)} {int(y)}", endpoint)


class IpcServer:
    def __init__(
        self,
        callback: Callable[[str], None],
        endpoint: Path | None = None,
    ) -> None:
        self.callback = callback
        self.endpoint = _endpoint_path(endpoint)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        if self._socket is not None:
            return True
        try:
            if sys.platform == "win32":
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("127.0.0.1", WINDOWS_PORT))
            else:
                path = self.endpoint
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    # Remove a stale socket only after verifying nobody answers.
                    if send_command("show", endpoint=path):
                        log.warning("已有 QuickTools 实例在运行")
                        return False
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.bind(str(path))
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
            sock.listen(8)
            sock.settimeout(0.4)
            self._socket = sock
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._serve, name="quicktools-ipc", daemon=True
            )
            self._thread.start()
            log.info("单实例 IPC 服务已启动：%s", self._describe_endpoint())
            return True
        except OSError as exc:
            log.warning("单实例 IPC 启动失败：%s", exc)
            try:
                if "sock" in locals() and sock is not None:
                    sock.close()
            except OSError:
                pass
            return False

    def _describe_endpoint(self) -> str:
        if sys.platform == "win32":
            return f"127.0.0.1:{WINDOWS_PORT}"
        return str(self.endpoint)

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                conn, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    conn.settimeout(0.4)
                    data = conn.recv(_MAX_MESSAGE)
                    command = data.decode("ascii", errors="ignore").strip()
                    if command == "ping":
                        try:
                            conn.sendall(b"OK\n")
                        except OSError:
                            pass
                    elif command.startswith("menu "):
                        parts = command.split()
                        valid = False
                        if len(parts) == 3:
                            try:
                                x, y = int(parts[1]), int(parts[2])
                                valid = abs(x) <= 100_000 and abs(y) <= 100_000
                            except ValueError:
                                valid = False
                        if valid:
                            self.callback(command)
                            try:
                                conn.sendall(b"OK\n")
                            except OSError:
                                pass
                    elif command in VALID_COMMANDS:
                        self.callback(command)
                        try:
                            conn.sendall(b"OK\n")
                        except OSError:
                            pass
                except OSError:
                    continue

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if sys.platform != "win32":
            try:
                self.endpoint.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                log.debug("清理 IPC socket 失败", exc_info=True)
