"""Path, time and OS helpers shared by the clipboard UI and store."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import url2pathname

from .models import ClipboardError, current_platform, platform_label


def is_file_uri_list(text: str) -> bool:
    """Return True when the clipboard text looks like a file URI list."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line.lower().startswith("file:")
    return False


def parse_uri_list(text: str) -> list[str]:
    """Parse an X11/Wayland ``text/uri-list`` payload.

    Only local ``file:`` URIs are returned. The original path text is kept
    otherwise, so a Windows path is never rewritten on Linux.
    """
    paths: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parsed = urlsplit(line)
        except ValueError:
            continue
        if parsed.scheme.lower() != "file":
            continue
        host = (parsed.netloc or "").lower()
        if host not in ("", "localhost"):
            # Network shares are intentionally out of scope for v1.
            continue
        try:
            path = url2pathname(parsed.path)
        except (OSError, ValueError):
            continue
        if not path:
            continue
        if path not in paths:
            paths.append(path)
    return paths


def path_to_uri(path: str) -> str:
    """Encode a native path as a local file URI without changing separators."""
    candidate = path
    if current_platform() == "win32" or (
        len(candidate) >= 3 and candidate[1] == ":" and candidate[2] in "\\/"
    ):
        candidate = candidate.replace("\\", "/")
        if not candidate.startswith("/"):
            candidate = "/" + candidate
    elif not candidate.startswith("/"):
        candidate = "/" + candidate
    return "file://" + quote(candidate, safe="/:@!$&'()*+,;=")


def paths_to_uri_list(paths: tuple[str, ...] | list[str]) -> str:
    return "\r\n".join(path_to_uri(path) for path in paths) + "\r\n"


def path_accessibility(paths: tuple[str, ...] | list[str], source_platform: str) -> list[bool]:
    """Check paths only when they belong to the platform we are running on."""
    if source_platform != current_platform():
        return [False for _ in paths]
    result = []
    for path in paths:
        try:
            result.append(os.path.exists(path))
        except (OSError, ValueError):
            result.append(False)
    return result


def accessible_paths(
    paths: tuple[str, ...] | list[str], source_platform: str
) -> tuple[list[str], list[str]]:
    flags = path_accessibility(paths, source_platform)
    available = [path for path, ok in zip(paths, flags) if ok]
    missing = [path for path, ok in zip(paths, flags) if not ok]
    return available, missing


def format_size(size: int | None) -> str:
    value = max(0, int(size or 0))
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.0f} KB"
    if value < 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    return f"{value / (1024 * 1024 * 1024):.2f} GB"


def format_count(entry_kind: str, char_count: int, byte_size: int) -> str:
    if entry_kind == "text":
        return f"文本 · {char_count} 字"
    if entry_kind == "image":
        return f"图片 · {format_size(byte_size)}"
    return f"文件 · {format_size(byte_size)}"


def format_time(timestamp: float, *, detail: bool = False, now: float | None = None) -> str:
    local = time.localtime(timestamp)
    if detail:
        return time.strftime("%Y-%m-%d %H:%M:%S", local)
    current = time.localtime(now if now is not None else time.time())
    if (local.tm_year, local.tm_yday) == (current.tm_year, current.tm_yday):
        return time.strftime("%H:%M", local)
    if local.tm_year == current.tm_year:
        return time.strftime("%m-%d", local)
    return time.strftime("%Y-%m-%d", local)


def first_line(text: str, limit: int = 72) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return truncate(stripped, limit)
    return "文本"


def preview_text(text: str, limit: int = 110) -> str:
    compact = " ".join(text.split())
    return truncate(compact, limit) if compact else "（空文本）"


def truncate(text: str, limit: int) -> str:
    if limit <= 1 or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def middle_ellipsis(text: str, limit: int) -> str:
    if limit <= 3 or len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return text[:head] + "…" + text[-tail:]


def source_label(source: str | None) -> str:
    value = (source or "").strip()
    return value or "系统剪贴板"


def foreign_note(source_platform: str) -> str:
    if source_platform == current_platform():
        return ""
    return f"不可访问（来自 {platform_label(source_platform)} 的路径）"


def reveal_path(path: str) -> None:
    """Show a file in the platform file manager or open its folder."""
    target = Path(path)
    if not target.exists():
        raise ClipboardError(f"文件已移动或删除：\n{path}")
    parent = target.parent if target.parent.exists() else target
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer", f"/select,{target}"])
            return
        except OSError:
            pass
        os.startfile(str(parent))  # type: ignore[attr-defined]
        return
    opener = "xdg-open"
    try:
        subprocess.Popen([opener, str(parent)])
    except FileNotFoundError as exc:
        raise ClipboardError(f"无法打开文件管理器：找不到 {opener}") from exc
    except OSError as exc:
        raise ClipboardError(f"无法打开文件管理器：{exc}") from exc


def open_directory(path: Path) -> None:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    try:
        subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        raise ClipboardError(f"无法打开目录：{exc}") from exc
