from __future__ import annotations

from pathlib import Path

from quicktools.plugins.clipboard.models import (
    ClipboardContent,
    ClipboardKind,
    content_digest,
    current_platform,
    display_name_for_paths,
)
from quicktools.plugins.clipboard.platform_utils import (
    accessible_paths,
    format_size,
    middle_ellipsis,
    parse_uri_list,
    path_accessibility,
    path_to_uri,
    paths_to_uri_list,
    truncate,
)


def test_parse_uri_list_with_unicode_and_spaces() -> None:
    payload = (
        "file:///home/kk/a%20b.txt\r\n"
        "# comment\r\n"
        "file:///tmp/中文.txt\r\n"
        "https://example.com/nope\r\n"
        "file://remotehost/share/file.txt\r\n"
    )
    assert parse_uri_list(payload) == ["/home/kk/a b.txt", "/tmp/中文.txt"]


def test_parse_uri_list_localhost() -> None:
    assert parse_uri_list("file://localhost/tmp/x.txt") == ["/tmp/x.txt"]


def test_path_to_uri_and_back() -> None:
    path = "/tmp/目录 with space.txt"
    uri = path_to_uri(path)
    assert uri.startswith("file:///")
    assert "%20" in uri
    assert parse_uri_list(uri) == [path]


def test_paths_to_uri_list_crlf() -> None:
    result = paths_to_uri_list(["/tmp/a", "/tmp/b"])
    assert result.endswith("\r\n")
    assert result.count("\r\n") == 2


def test_windows_paths_are_not_rewritten() -> None:
    paths = (r"C:\Users\kk\Documents\example.pdf",)
    assert display_name_for_paths(paths, "win32") == "example.pdf"
    # Running on Linux: a Windows entry is never treated as accessible.
    if current_platform() != "win32":
        assert path_accessibility(paths, "win32") == [False]
        available, missing = accessible_paths(paths, "win32")
        assert available == []
        assert missing == list(paths)


def test_current_platform_paths(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("x", encoding="utf-8")
    assert path_accessibility([str(path)], current_platform()) == [True]
    assert path_accessibility([str(tmp_path / "missing")], current_platform()) == [
        False
    ]


def test_digest_is_stable_and_kind_specific() -> None:
    first = ClipboardContent(kind=ClipboardKind.TEXT, text="hello")
    second = ClipboardContent(kind=ClipboardKind.TEXT, text="hello")
    different = ClipboardContent(kind=ClipboardKind.TEXT, text="hello!")
    assert content_digest(first) == content_digest(second)
    assert content_digest(first) != content_digest(different)
    image_a = ClipboardContent(kind=ClipboardKind.IMAGE, image_png=b"png-a")
    image_b = ClipboardContent(kind=ClipboardKind.IMAGE, image_png=b"png-b")
    assert content_digest(image_a) != content_digest(image_b)


def test_digest_windows_paths_are_case_insensitive() -> None:
    upper = ClipboardContent(
        kind=ClipboardKind.FILES,
        paths=(r"C:\Users\KK\File.TXT",),
        platform="win32",
    )
    lower = ClipboardContent(
        kind=ClipboardKind.FILES,
        paths=(r"c:\users\kk\file.txt",),
        platform="win32",
    )
    assert content_digest(upper) == content_digest(lower)
    # Different platforms are not conflated.
    linux = ClipboardContent(
        kind=ClipboardKind.FILES,
        paths=("C:\\Users\\KK\\File.TXT",),
        platform="linux",
    )
    assert content_digest(upper) != content_digest(linux)


def test_format_helpers() -> None:
    assert format_size(0) == "0 B"
    assert format_size(512) == "512 B"
    assert format_size(1024) == "1 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024 * 1024 * 1024) == "1.00 GB"
    assert truncate("abcdef", 4) == "abc…"
    assert middle_ellipsis("abcdefghij", 5) == "ab…ij"


def test_file_digest_keeps_platform_separate() -> None:
    paths = (str(Path("/tmp") / "x"),)
    linux = ClipboardContent(kind=ClipboardKind.FILES, paths=paths, platform="linux")
    windows = ClipboardContent(kind=ClipboardKind.FILES, paths=paths, platform="win32")
    assert content_digest(linux) != content_digest(windows)
