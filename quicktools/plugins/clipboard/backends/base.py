"""Platform-independent clipboard backend contract."""

from __future__ import annotations

from typing import Callable, Protocol, Sequence

from ..models import BackendStatus, ClipboardContent, ClipboardError, ClipboardKind


class ClipboardBackend(Protocol):
    name: str
    status: BackendStatus

    def start(self, on_change: Callable[[ClipboardContent], None]) -> None: ...

    def stop(self) -> None: ...

    def read_text(self) -> str | None: ...

    def read_image(self) -> bytes | None: ...

    def read_files(self) -> list[str] | None: ...

    def write_text(self, text: str) -> None: ...

    def write_image(self, png: bytes) -> None: ...

    def write_files(self, paths: Sequence[str]) -> None: ...


class BaseBackend:
    """Small helpers shared by the concrete backends."""

    name = "base"

    def __init__(self) -> None:
        self.status = BackendStatus(False, "未初始化", "剪贴板后端尚未启动")
        self._on_change: Callable[[ClipboardContent], None] | None = None

    def set_status(self, status: BackendStatus) -> None:
        self.status = status

    def source_name(self) -> str | None:
        return None

    def snapshot(self) -> ClipboardContent | None:
        """Read a snapshot with files > image > text priority.

        Backends can override this to avoid querying the clipboard multiple
        times. The default is sufficient for subprocess/ctypes backends.
        """
        source = self.source_name()
        files = self.read_files()
        if files:
            return ClipboardContent(
                kind=ClipboardKind.FILES,
                paths=tuple(files),
                source=source,
            )
        image = self.read_image()
        if image:
            return ClipboardContent(
                kind=ClipboardKind.IMAGE, image_png=image, source=source
            )
        text = self.read_text()
        if text and text.strip():
            return ClipboardContent(
                kind=ClipboardKind.TEXT, text=text, source=source
            )
        return None


class UnavailableBackend(BaseBackend):
    """A backend that reports why clipboard monitoring cannot run."""

    def __init__(
        self,
        detail: str,
        *,
        mode: str = "监听不可用",
        install_hint: str = "",
    ) -> None:
        super().__init__()
        self.name = "unavailable"
        self.status = BackendStatus(
            False, mode, detail=detail, install_hint=install_hint
        )

    def start(self, on_change: Callable[[ClipboardContent], None]) -> None:
        self._on_change = on_change

    def stop(self) -> None:
        return

    def read_text(self) -> str | None:
        return None

    def read_image(self) -> bytes | None:
        return None

    def read_files(self) -> list[str] | None:
        return None

    def _unavailable(self) -> ClipboardError:
        message = self.status.detail or "剪贴板功能不可用"
        if self.status.install_hint:
            message += f"\n\n{self.status.install_hint}"
        return ClipboardError(message)

    def write_text(self, text: str) -> None:
        raise self._unavailable()

    def write_image(self, png: bytes) -> None:
        raise self._unavailable()

    def write_files(self, paths: Sequence[str]) -> None:
        raise self._unavailable()
