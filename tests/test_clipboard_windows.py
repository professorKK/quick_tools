"""Windows-only integration tests for the native clipboard backend.

These tests are skipped on Linux/macOS. They exercise the real Win32
clipboard and listener, so run them on Windows before treating the Windows
backend as validated.
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows clipboard backend"
)


@pytest.fixture()
def backend():
    from quicktools.plugins.clipboard.backends.windows import WindowsBackend

    received: list = []
    instance = WindowsBackend()
    instance.start(received.append)
    assert instance.status.available, instance.status.detail
    try:
        yield instance, received
    finally:
        instance.stop()


def test_write_and_read_text(backend) -> None:
    instance, _received = backend
    text = "Windows 剪贴板测试 ✓\n第二行"
    instance.write_text(text)
    assert instance.read_text() == text


def test_write_and_read_image(backend) -> None:
    instance, _received = backend
    source = Image.new("RGB", (24, 16), (30, 60, 90))
    buffer = io.BytesIO()
    source.save(buffer, "PNG")
    source.close()
    instance.write_image(buffer.getvalue())
    png = instance.read_image()
    assert png is not None
    with Image.open(io.BytesIO(png)) as result:
        result.load()
        assert result.size == (24, 16)


def test_write_and_read_files(backend, tmp_path: Path) -> None:
    instance, _received = backend
    first = tmp_path / "文件 1.txt"
    second = tmp_path / "two.txt"
    first.write_text("1", encoding="utf-8")
    second.write_text("2", encoding="utf-8")
    instance.write_files([str(first), str(second)])
    paths = instance.read_files()
    assert paths == [str(first), str(second)]


def test_listener_receives_changes(backend) -> None:
    instance, received = backend
    unique = f"listener-{time.time_ns()}"
    instance.write_text(unique)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if any(
            content.kind.value == "text"
            and content.text == unique
            for content in received
        ):
            break
        time.sleep(0.05)
    else:
        pytest.fail("Windows clipboard listener did not receive the change")
