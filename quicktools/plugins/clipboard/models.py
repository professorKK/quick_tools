"""Shared data types for the clipboard plugin.

This module deliberately has no Tk or platform-specific imports so the store,
path helpers, and backend format tests can run on any supported platform.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import posixpath
import sys
from dataclasses import dataclass, field
from enum import Enum


class ClipboardError(Exception):
    """Base error for clipboard capture and copy operations."""


class ClipboardTooLarge(ClipboardError):
    """Raised when an image exceeds the configured single-item limit."""


class PartialFilesError(ClipboardError):
    """Some files in a copied file list no longer exist."""

    def __init__(self, available: list[str], missing: list[str]) -> None:
        self.available = list(available)
        self.missing = list(missing)
        super().__init__(f"{len(missing)} 个文件已移动或删除")


class ClipboardKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    FILES = "files"

    @property
    def label(self) -> str:
        return {
            ClipboardKind.TEXT: "文本",
            ClipboardKind.IMAGE: "图片",
            ClipboardKind.FILES: "文件",
        }[self]


PLATFORM_LABELS = {"linux": "Linux", "win32": "Windows"}


def kind_value(kind: object) -> str:
    """Return a kind's string value, tolerating a second module identity.

    QuickTools imports plugins under a generated package name, so tests or
    helper scripts that also import this package normally can end up with two
    distinct Enum classes. Comparing by value keeps capture logic correct.
    """
    return str(getattr(kind, "value", kind))


def current_platform() -> str:
    """Return the platform key used in the database.

    Only Linux and Windows are supported by the clipboard plugin; other POSIX
    systems are treated as Linux so the UI still opens instead of crashing.
    """
    return "win32" if sys.platform == "win32" else "linux"


def platform_label(key: str) -> str:
    return PLATFORM_LABELS.get(key, key or "未知系统")


@dataclass(frozen=True)
class BackendStatus:
    """Availability of the current platform clipboard backend."""

    available: bool
    mode: str
    detail: str = ""
    install_hint: str = ""

    @property
    def label(self) -> str:
        if self.available:
            return self.mode or "系统剪贴板"
        return self.detail or "监听不可用"


@dataclass(frozen=True)
class ClipboardContent:
    """A single clipboard snapshot produced by a platform backend."""

    kind: ClipboardKind
    text: str | None = None
    image_png: bytes | None = None
    paths: tuple[str, ...] = ()
    source: str | None = None
    platform: str = field(default_factory=current_platform)

    def __post_init__(self) -> None:
        kind = kind_value(self.kind)
        if kind == "text" and not (self.text or "").strip():
            raise ClipboardError("空文本")
        if kind == "image" and not self.image_png:
            raise ClipboardError("空图片")
        if kind == "files" and not self.paths:
            raise ClipboardError("空文件列表")


def content_digest(content: ClipboardContent) -> str:
    """Stable digest used to merge repeated copies of the same content."""
    kind = kind_value(content.kind)
    if kind == "text":
        payload = (content.text or "").encode("utf-8")
    elif kind == "image":
        payload = content.image_png or b""
    else:
        # Windows paths are case-insensitive; normalise only for the digest,
        # never for the value stored and shown in the UI.
        path_values = [
            ntpath.normcase(path) if content.platform == "win32" else path
            for path in content.paths
        ]
        payload = json.dumps(path_values, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(kind.encode("ascii") + b"\0" + payload).hexdigest()


def display_name_for_paths(paths: tuple[str, ...], platform: str) -> str:
    """Human-friendly title for a file-list entry."""
    if not paths:
        return "文件"
    if len(paths) > 1:
        return f"{len(paths)} 个文件"
    raw = paths[0].rstrip("\\/")
    basename = ntpath.basename(raw) if platform == "win32" else posixpath.basename(raw)
    return basename or raw or "文件"


@dataclass(frozen=True)
class ClipboardEntry:
    """One row from the clipboard history database."""

    id: int
    kind: ClipboardKind
    digest: str
    title: str
    text_content: str | None
    image_path: str | None
    thumb_path: str | None
    paths: tuple[str, ...]
    byte_size: int
    char_count: int
    source: str | None
    source_platform: str
    copy_count: int
    created_at: float
    last_copied_at: float

    @property
    def is_multi_file(self) -> bool:
        return self.kind is ClipboardKind.FILES and len(self.paths) > 1
