"""Public API used by QuickTools plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class PluginError(Exception):
    """Raised when a plugin cannot be loaded or opened."""


@dataclass(frozen=True)
class PluginMeta:
    id: str
    name: str
    description: str
    version: str
    entry: str
    class_name: str
    folder: Path
    icon: str = "◆"
    order: int = 100
    builtin: bool = False
    background: bool = False

    @property
    def display_icon(self) -> str:
        icon = self.icon.strip()
        # Tk 8.6 on Linux often measures emoji but draws nothing. Prefer a
        # readable monogram over an invisible glyph.
        if icon and not _is_emoji_like(icon):
            return icon[:2]
        name = self.name.strip()
        return name[:1].upper() if name else "◆"


def _is_emoji_like(text: str) -> bool:
    for char in text:
        code = ord(char)
        if (
            code > 0xFFFF
            or 0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or 0xFE00 <= code <= 0xFE0F
        ):
            return True
    return False


@dataclass(frozen=True)
class PluginActions:
    """Optional core services available to built-in plugins.

    ``post_action`` is the only thread-safe member. The other callables must
    be invoked on the Tk main thread.
    """

    post_action: Callable[[str], None]
    open_window: Callable[[], None]
    hide_windows: Callable[[], Callable[[], None]]
    copy_png_to_clipboard: Callable[[bytes], None]
    app_hotkey_display: Callable[[], str]


@dataclass(frozen=True)
class PluginContext:
    """Useful services and paths exposed to a plugin.

    A plugin creates its UI inside the ``window`` passed to
    :meth:`PluginBase.create_ui`. ``data_dir`` is private to the plugin.
    """

    root: Any
    plugin_id: str
    plugin_dir: Path
    data_dir: Path
    actions: PluginActions | None = None


class PluginBase(ABC):
    """Base class every QuickTools plugin must inherit from."""

    def __init__(self, context: PluginContext) -> None:
        self.context = context

    @abstractmethod
    def create_ui(self, window: Any) -> None:
        """Populate the Toplevel window owned by the launcher."""

    def start_service(self) -> None:
        """Start background work for a manifest marked ``background``.

        The launcher calls this once while QuickTools is running, even if the
        plugin window has never been opened. The default is a no-op.
        """

    def stop_service(self) -> None:
        """Stop background work started by :meth:`start_service`.

        Called on application shutdown and when a background plugin is
        removed or changed on disk. The default is a no-op.
        """

    def handle_action(self, action: str) -> None:
        """Handle a named action on the Tk main thread.

        Actions are ASCII identifiers and carry no payload. Plugins should
        ignore unknown actions. Long-running work must be moved to a worker
        thread; this method must return promptly. The default is a no-op.
        """
