from __future__ import annotations

import io
from pathlib import Path
from typing import Callable, Sequence

import pytest
from PIL import Image

from quicktools.plugins.clipboard.models import (
    BackendStatus,
    ClipboardContent,
    ClipboardError,
    ClipboardKind,
    PartialFilesError,
)
from quicktools.plugins.clipboard.service import ClipboardService
from quicktools.plugins.clipboard.settings import load_settings


class FakeRoot:
    def __init__(self) -> None:
        self.jobs: dict[str, Callable[[], None]] = {}
        self._counter = 0

    def after(self, _delay: int, callback: Callable[[], None]) -> str:
        self._counter += 1
        key = f"job-{self._counter}"
        self.jobs[key] = callback
        return key

    def after_cancel(self, key: str) -> None:
        self.jobs.pop(key, None)

    def run_once(self) -> None:
        jobs = list(self.jobs.items())
        self.jobs.clear()
        for _key, callback in jobs:
            callback()


class FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.status = BackendStatus(True, "Fake")
        self.callback: Callable[[ClipboardContent], None] | None = None
        self.started = False
        self.stopped = False
        self.text_writes: list[str] = []
        self.image_writes: list[bytes] = []
        self.file_writes: list[list[str]] = []

    def start(self, on_change) -> None:
        self.callback = on_change
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def emit(self, content: ClipboardContent) -> None:
        assert self.callback is not None
        self.callback(content)

    def read_text(self) -> str | None:
        return None

    def read_image(self) -> bytes | None:
        return None

    def read_files(self) -> list[str] | None:
        return None

    def write_text(self, text: str) -> None:
        self.text_writes.append(text)

    def write_image(self, png: bytes) -> None:
        self.image_writes.append(png)

    def write_files(self, paths: Sequence[str]) -> None:
        self.file_writes.append(list(paths))


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (20, 10), (1, 2, 3)).save(output, "PNG")
    return output.getvalue()


@pytest.fixture()
def service(tmp_path: Path):
    root = FakeRoot()
    backend = FakeBackend()
    instance = ClipboardService(tmp_path, root, backend=backend)
    yield instance, backend, root, tmp_path
    instance.stop()


def drain(root: FakeRoot) -> None:
    root.run_once()


def test_copy_image_png_writes_and_records(service) -> None:
    instance, backend, _root, _tmp_path = service
    instance.start()
    data = png_bytes()

    entry = instance.copy_image_png(data)

    assert entry is not None
    assert backend.image_writes == [data]
    assert instance.counts()["image"] == 1


def test_copy_image_png_without_history(service) -> None:
    instance, backend, _root, _tmp_path = service
    instance.start()
    data = png_bytes()

    entry = instance.copy_image_png(data, record=False)

    assert entry is None
    assert backend.image_writes == [data]
    assert instance.counts()["image"] == 0


def test_copy_image_png_rejects_invalid_data(service) -> None:
    instance, backend, _root, _tmp_path = service
    instance.start()

    with pytest.raises(ClipboardError):
        instance.copy_image_png(b"not a png")

    assert backend.image_writes == []
    assert instance.counts()["image"] == 0


def test_capture_pause_and_resume(service) -> None:
    instance, backend, root, tmp_path = service
    events: list[tuple[str, int | None]] = []
    instance.add_listener(lambda event, entry_id: events.append((event, entry_id)))
    instance.start()
    assert backend.started

    backend.emit(ClipboardContent(kind=ClipboardKind.TEXT, text="hello"))
    drain(root)
    assert instance.counts()["all"] == 1
    assert events and events[-1][0] == "added"

    instance.set_recording(False)
    assert load_settings(tmp_path).recording is False
    backend.emit(ClipboardContent(kind=ClipboardKind.TEXT, text="paused"))
    drain(root)
    assert instance.counts()["all"] == 1

    instance.set_recording(True)
    backend.emit(ClipboardContent(kind=ClipboardKind.TEXT, text="resumed"))
    drain(root)
    assert instance.counts()["all"] == 2


def test_image_and_file_capture_toggles(service) -> None:
    instance, backend, root, _tmp_path = service
    instance.start()
    instance.update_settings(capture_images=False, capture_files=False)

    backend.emit(
        ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes())
    )
    backend.emit(
        ClipboardContent(kind=ClipboardKind.FILES, paths=("/tmp/a",))
    )
    drain(root)
    assert instance.counts()["all"] == 0

    instance.update_settings(capture_images=True)
    backend.emit(
        ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes())
    )
    drain(root)
    assert instance.counts()["image"] == 1


def test_duplicate_updates_copy_count(service) -> None:
    instance, backend, root, _tmp_path = service
    instance.start()
    content = ClipboardContent(kind=ClipboardKind.TEXT, text="same")
    backend.emit(content)
    drain(root)
    backend.emit(content)
    drain(root)
    entries = instance.entries()
    assert len(entries) == 1
    assert entries[0].copy_count == 2


def test_copy_entry_suppresses_echo(service) -> None:
    instance, backend, root, _tmp_path = service
    instance.start()
    content = ClipboardContent(kind=ClipboardKind.TEXT, text="copy me")
    backend.emit(content)
    drain(root)
    entry = instance.entries()[0]

    updated = instance.copy_entry(entry)
    assert backend.text_writes == ["copy me"]
    assert updated is not None and updated.copy_count == 2

    # A backend notification caused by our own write must not bump it again.
    backend.emit(content)
    drain(root)
    assert instance.entries()[0].copy_count == 2


def test_copy_entry_keeps_history_order(service, monkeypatch) -> None:
    instance, _backend, root, _tmp_path = service
    instance.start()
    times = iter([100.0, 200.0])
    monkeypatch.setattr(instance.store, "_clock", lambda: next(times))
    root.run_once()
    _backend.emit(
        ClipboardContent(kind=ClipboardKind.TEXT, text="older")
    )
    drain(root)
    _backend.emit(
        ClipboardContent(kind=ClipboardKind.TEXT, text="newer")
    )
    drain(root)
    newer, older = instance.entries()

    updated = instance.copy_entry(older)

    assert updated is not None and updated.copy_count == 2
    entries = instance.entries()
    assert [entry.text_content for entry in entries] == ["newer", "older"]
    assert entries[0].id == newer.id
    assert entries[1].id == older.id


def test_copy_image_entry(service) -> None:
    instance, backend, root, _tmp_path = service
    instance.start()
    backend.emit(
        ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes())
    )
    drain(root)
    entry = instance.entries()[0]
    stored = instance.store.image_bytes(entry)
    updated = instance.copy_entry(entry)
    assert stored is not None
    assert backend.image_writes == [stored]
    assert updated is not None and updated.copy_count == 2


def test_copy_files_partial(tmp_path: Path) -> None:
    root = FakeRoot()
    backend = FakeBackend()
    instance = ClipboardService(tmp_path, root, backend=backend)
    try:
        instance.start()
        first = tmp_path / "one.txt"
        second = tmp_path / "two.txt"
        first.write_text("1", encoding="utf-8")
        second.write_text("2", encoding="utf-8")
        backend.emit(
            ClipboardContent(
                kind=ClipboardKind.FILES,
                paths=(str(first), str(second)),
            )
        )
        drain(root)
        entry = instance.entries()[0]
        second.unlink()

        with pytest.raises(PartialFilesError) as info:
            instance.copy_entry(entry)
        assert info.value.available == [str(first)]
        assert info.value.missing == [str(second)]

        instance.copy_entry(entry, paths=info.value.available)
        assert backend.file_writes == [[str(first)]]
        assert instance.entries()[0].copy_count == 2
    finally:
        instance.stop()


def test_file_copy_text_echo_is_ignored(tmp_path: Path) -> None:
    """GNOME may republish a file selection as plain paths after the app exits."""
    root = FakeRoot()
    backend = FakeBackend()
    instance = ClipboardService(tmp_path, root, backend=backend)
    try:
        instance.start()
        first = tmp_path / "one.txt"
        second = tmp_path / "two.txt"
        first.write_text("1", encoding="utf-8")
        second.write_text("2", encoding="utf-8")
        paths = (str(first), str(second))
        backend.emit(ClipboardContent(kind=ClipboardKind.FILES, paths=paths))
        drain(root)
        assert instance.counts()["all"] == 1

        backend.emit(
            ClipboardContent(
                kind=ClipboardKind.TEXT,
                text="\r\n".join(paths),
            )
        )
        drain(root)
        assert instance.counts()["all"] == 1

        backend.emit(
            ClipboardContent(kind=ClipboardKind.TEXT, text="unrelated text")
        )
        drain(root)
        assert instance.counts()["all"] == 2
    finally:
        instance.stop()


def test_copy_foreign_files_is_rejected(tmp_path: Path) -> None:
    root = FakeRoot()
    backend = FakeBackend()
    instance = ClipboardService(tmp_path, root, backend=backend)
    try:
        instance.start()
        backend.emit(
            ClipboardContent(
                kind=ClipboardKind.FILES,
                paths=(r"C:\Users\kk\a.txt",),
                platform="win32",
            )
        )
        drain(root)
        entry = instance.entries()[0]
        with pytest.raises(ClipboardError):
            instance.copy_entry(entry)
    finally:
        instance.stop()


def test_delete_clear_and_status(service) -> None:
    instance, backend, root, _tmp_path = service
    instance.start()
    backend.emit(ClipboardContent(kind=ClipboardKind.TEXT, text="one"))
    drain(root)
    entry = instance.entries()[0]
    assert instance.delete_entry(entry.id) is True
    assert instance.counts()["all"] == 0

    backend.emit(ClipboardContent(kind=ClipboardKind.TEXT, text="two"))
    drain(root)
    assert instance.clear_history() == 1
    assert instance.counts()["all"] == 0

    headline, _detail, level = instance.status_text()
    assert headline == "已在后台运行"
    assert level == "ok"

    instance.set_recording(False)
    headline, _detail, level = instance.status_text()
    assert headline == "已暂停记录"
    assert level == "warn"


def test_stop_releases_backend(service) -> None:
    instance, backend, _root, _tmp_path = service
    instance.start()
    instance.stop()
    assert backend.stopped is True


def test_drain_runs_periodic_maintenance(service, monkeypatch) -> None:
    from quicktools.plugins.clipboard.store import MaintenanceStats

    instance, _backend, _root, _tmp = service
    calls: list[int] = []
    monkeypatch.setattr(
        instance.store,
        "maintenance",
        lambda: calls.append(1) or MaintenanceStats(missing_images=1),
    )
    events: list[tuple[str, int | None]] = []
    instance.add_listener(lambda event, entry_id: events.append((event, entry_id)))
    instance.start()
    instance._last_maintenance = 0.0

    instance._drain()

    assert calls == [1]
    assert ("settings", None) in events


def test_maintenance_is_throttled(service, monkeypatch) -> None:
    from quicktools.plugins.clipboard.store import MaintenanceStats

    instance, _backend, _root, _tmp = service
    calls: list[int] = []
    monkeypatch.setattr(
        instance.store,
        "maintenance",
        lambda: calls.append(1) or MaintenanceStats(),
    )
    instance._last_maintenance = 0.0

    instance.maintenance()
    instance.maintenance()
    assert len(calls) == 1

    instance.maintenance(force=True)
    assert len(calls) == 2


def test_entries_limit_and_offset(service) -> None:
    instance, _backend, _root, _tmp = service
    entries = [
        instance.store.add(
            ClipboardContent(kind=ClipboardKind.TEXT, text=f"entry {index}")
        )
        for index in range(5)
    ]
    page = instance.entries(limit=2, offset=2)
    assert len(page) == 2
    assert {entry.id for entry in page} == {
        entries[1].id,
        entries[2].id,
    }
