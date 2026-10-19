from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from quicktools.plugins.clipboard.models import (
    ClipboardContent,
    ClipboardError,
    ClipboardKind,
    ClipboardTooLarge,
)
from quicktools.plugins.clipboard.settings import (
    ClipboardSettings,
    load_settings,
    save_settings,
)
from quicktools.plugins.clipboard.store import ClipboardStore


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def png_bytes(color=(20, 120, 220), size=(40, 30)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


@pytest.fixture()
def store(tmp_path: Path) -> ClipboardStore:
    clock = Clock()
    instance = ClipboardStore(tmp_path, clock=clock)
    yield instance
    instance.close()


def test_add_text_and_duplicate(store: ClipboardStore) -> None:
    content = ClipboardContent(
        kind=ClipboardKind.TEXT, text="第一行\n第二行", source="terminal"
    )
    entry = store.add(content)
    assert entry.kind is ClipboardKind.TEXT
    assert entry.title == "第一行"
    assert entry.char_count == 7
    assert entry.byte_size == len("第一行\n第二行".encode("utf-8"))
    assert entry.copy_count == 1
    first_time = entry.last_copied_at

    duplicate = store.add(content)
    assert duplicate.id == entry.id
    assert duplicate.copy_count == 2
    assert duplicate.last_copied_at > first_time
    assert store.counts()["all"] == 1


def test_order_counts_and_search(store: ClipboardStore) -> None:
    store.add(ClipboardContent(kind=ClipboardKind.TEXT, text="alpha 内容"))
    store.add(ClipboardContent(kind=ClipboardKind.TEXT, text="beta 内容"))
    store.add(ClipboardContent(kind=ClipboardKind.TEXT, text="gamma 内容"))
    titles = [entry.text_content for entry in store.list_entries()]
    assert titles == ["gamma 内容", "beta 内容", "alpha 内容"]
    oldest = store.list_entries(newest_first=False)
    assert oldest[0].text_content == "alpha 内容"
    assert store.counts() == {"all": 3, "text": 3, "image": 0, "files": 0}
    assert [e.text_content for e in store.list_entries(query="beta")] == [
        "beta 内容"
    ]
    assert store.list_entries(query="%") == []
    assert [e.text_content for e in store.list_entries(query="gamma")] == [
        "gamma 内容"
    ]


def test_image_storage_and_dedupe(store: ClipboardStore, tmp_path: Path) -> None:
    content = ClipboardContent(
        kind=ClipboardKind.IMAGE, image_png=png_bytes(), source="screenshot"
    )
    entry = store.add(content)
    assert entry.kind is ClipboardKind.IMAGE
    assert entry.title.startswith("图片 40×30")
    image_file = store.image_file(entry)
    thumb_file = store.thumb_file(entry)
    assert image_file is not None and image_file.is_file()
    assert thumb_file is not None and thumb_file.is_file()
    assert store.image_bytes(entry) == image_file.read_bytes()
    assert entry.byte_size == image_file.stat().st_size

    duplicate = store.add(content)
    assert duplicate.id == entry.id
    assert duplicate.copy_count == 2
    assert len(list((tmp_path / "images").iterdir())) == 1
    assert len(list((tmp_path / "thumbs").iterdir())) == 1


def test_image_too_large(store: ClipboardStore, tmp_path: Path) -> None:
    with pytest.raises(ClipboardTooLarge):
        store.add(
            ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes()),
            max_image_bytes=10,
        )
    assert not list((tmp_path / "images").iterdir())
    assert not list((tmp_path / "thumbs").iterdir())


def test_files_entry_and_accessibility(store: ClipboardStore, tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "两个.txt"
    first.write_text("12345", encoding="utf-8")
    second.write_text("67890", encoding="utf-8")
    content = ClipboardContent(
        kind=ClipboardKind.FILES,
        paths=(str(first), str(second)),
        source="文件管理器",
    )
    entry = store.add(content)
    assert entry.title == "2 个文件"
    assert entry.paths == (str(first), str(second))
    assert entry.byte_size == 10
    assert entry.source == "文件管理器"

    single = store.add(
        ClipboardContent(kind=ClipboardKind.FILES, paths=(str(first),))
    )
    assert single.title == "one.txt"

    missing = store.add(
        ClipboardContent(
            kind=ClipboardKind.FILES, paths=(str(tmp_path / "gone.bin"),)
        )
    )
    assert missing.byte_size == 0


def test_foreign_files_are_preserved_but_not_statted(store: ClipboardStore) -> None:
    paths = (
        r"C:\Users\kk\Documents\example.pdf",
        r"D:\项目\文件 2.txt",
    )
    entry = store.add(
        ClipboardContent(
            kind=ClipboardKind.FILES, paths=paths, platform="win32"
        )
    )
    assert entry.paths == paths
    assert entry.source_platform == "win32"
    assert entry.byte_size == 0


def test_delete_and_clear_remove_owned_files(
    store: ClipboardStore, tmp_path: Path
) -> None:
    text = store.add(ClipboardContent(kind=ClipboardKind.TEXT, text="x"))
    image = store.add(
        ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes())
    )
    image_file = store.image_file(image)
    thumb_file = store.thumb_file(image)
    assert image_file is not None and thumb_file is not None

    assert store.delete(text.id) is True
    assert store.get(text.id) is None
    assert store.delete(9999) is False

    assert store.delete(image.id) is True
    assert not image_file.exists()
    assert not thumb_file.exists()

    store.add(ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes((1, 2, 3))))
    removed = store.clear()
    assert removed == 1
    assert store.counts()["all"] == 0
    assert not list((tmp_path / "images").iterdir())
    assert not list((tmp_path / "thumbs").iterdir())


def test_prune_entries_and_image_budget(
    store: ClipboardStore, tmp_path: Path
) -> None:
    for index in range(60):
        store.add(
            ClipboardContent(kind=ClipboardKind.TEXT, text=f"record-{index}")
        )
    store.prune(max_entries=50, max_image_bytes=200 * 1024 * 1024)
    entries = store.list_entries()
    assert len(entries) == 50
    assert entries[0].text_content == "record-59"
    assert entries[-1].text_content == "record-10"

    for index in range(3):
        store.add(
            ClipboardContent(
                kind=ClipboardKind.IMAGE,
                image_png=png_bytes((index * 10, 0, 0)),
            )
        )
    assert store.counts()["image"] == 3
    store.prune(max_entries=500, max_image_bytes=1)
    assert store.counts()["image"] == 0
    assert not list((tmp_path / "images").iterdir())


def test_settings_roundtrip_and_clamping(tmp_path: Path) -> None:
    defaults = load_settings(tmp_path)
    assert defaults.recording is True
    assert defaults.max_entries == 500
    assert defaults.max_image_mb == 200

    save_settings(
        tmp_path,
        ClipboardSettings(
            recording=False,
            max_entries=1,
            max_image_mb=999999,
            capture_images=False,
            capture_files=True,
        ),
    )
    loaded = load_settings(tmp_path)
    assert loaded.recording is False
    assert loaded.max_entries == 50
    assert loaded.max_image_mb == 2000
    assert loaded.capture_images is False
    assert loaded.capture_files is True

    (tmp_path / "settings.json").write_text("{broken", encoding="utf-8")
    assert load_settings(tmp_path).max_entries == 500


def test_update_text_preserves_history_position(store: ClipboardStore) -> None:
    entry = store.add(
        ClipboardContent(kind=ClipboardKind.TEXT, text="original")
    )
    before = store.get(entry.id)
    assert before is not None
    updated = store.update_text(entry.id, "edited 内容\n第二行")
    assert updated is not None
    assert updated.id == entry.id
    assert updated.text_content == "edited 内容\n第二行"
    assert updated.title == "edited 内容"
    assert updated.char_count == len("edited 内容\n第二行")
    assert updated.byte_size == len("edited 内容\n第二行".encode("utf-8"))
    assert updated.digest != before.digest
    assert updated.copy_count == before.copy_count
    assert updated.last_copied_at == before.last_copied_at
    assert updated.created_at == before.created_at

    with pytest.raises(ClipboardError):
        store.update_text(entry.id, "   ")

    image = store.add(
        ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes())
    )
    assert store.update_text(image.id, "not editable") is None


def test_update_text_merges_into_duplicate(store: ClipboardStore) -> None:
    first = store.add(
        ClipboardContent(kind=ClipboardKind.TEXT, text="alpha")
    )
    second = store.add(
        ClipboardContent(kind=ClipboardKind.TEXT, text="beta")
    )
    merged = store.update_text(second.id, "alpha")
    assert merged is not None
    assert merged.id == first.id
    assert merged.text_content == "alpha"
    assert store.get(second.id) is None
    assert store.counts()["text"] == 1


def test_store_rejects_empty_text(store: ClipboardStore) -> None:
    with pytest.raises(ClipboardError):
        store.add(ClipboardContent(kind=ClipboardKind.TEXT, text="   "))
