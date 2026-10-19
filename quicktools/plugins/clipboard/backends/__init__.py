"""Choose the clipboard backend for the current platform."""

from __future__ import annotations

import sys

from .base import ClipboardBackend


def create_backend() -> ClipboardBackend:
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    from .linux import create_linux_backend

    return create_linux_backend()
