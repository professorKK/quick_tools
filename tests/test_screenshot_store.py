from __future__ import annotations

import io
import sqlite3
import time
from pathlib import Path

import pytest
from PIL import Image

from quicktools.plugins.screenshot.recent.store import (
    RecentStore,
    RecentStoreError,
)


def png_bytes(width: int = 20, height: int = 10, color=(1, 2, 3)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, "PNG")
    return output.getvalue()


def make_store(tmp_path: Path) -> RecentStore:
    return RecentStore(tmp_path / "data", tmp_path / "shots")


def test_add_list_update_delete(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        entry = store.add_png(png_bytes(), mode="region", source="test")
        assert isinstance(entry.id, str) and entry.id
        assert entry.width == 20
        assert entry.height == 10
        assert entry.path.exists()
        assert entry.path.parent == tmp_path / "shots"
        assert entry.path.name.startswith("screenshot_")
        assert entry.path.name.endswith("_region_20x10.png")
        assert store.list() == [entry]
        assert store.image_path(entry) == entry.path

        updated = store.update_png(entry.id, png_bytes(30, 40))
        assert updated is not None
        assert updated.id == entry.id
        assert (updated.width, updated.height) == (30, 40)
        assert updated.path.name.endswith("_region_30x40.png")
        assert updated.path.exists()
        assert not entry.path.exists()
        assert store.get(entry.id) == updated

        favorite = store.set_favorite(entry.id, True)
        assert favorite is not None
        assert favorite.id == entry.id
        assert favorite.favorite is True
        assert favorite.path.name.endswith("_fav.png")
        assert store.list(favorite=True) == [favorite]

        assert store.delete(entry.id)
        assert not favorite.path.exists()
        assert store.list() == []
        assert store.get(entry.id) is None
    finally:
        store.close()


def test_invalid_png_is_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        with pytest.raises(RecentStoreError):
            store.add_png(b"not png", mode="region")
    finally:
        store.close()


def test_prune_never_deletes_files(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        for _ in range(3):
            store.add_png(png_bytes(), mode="region")
        assert store.prune(max_entries=1, max_bytes=1) == 0
        assert len(store.list()) == 3
    finally:
        store.close()


def test_favorite_filters_and_toggle(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        region_a = store.add_png(png_bytes(), mode="region")
        window = store.add_png(png_bytes(), mode="window")
        region_b = store.add_png(png_bytes(), mode="region")

        starred = store.set_favorite(window.id, True)
        assert starred is not None and starred.favorite is True
        assert [entry.id for entry in store.list(favorite=True)] == [
            window.id
        ]
        assert {entry.id for entry in store.list(mode="region")} == {
            region_a.id,
            region_b.id,
        }
        assert [
            entry.id for entry in store.list(favorite=True, mode="window")
        ] == [window.id]

        toggled = store.toggle_favorite(window.id)
        assert toggled is not None and toggled.favorite is False
        assert store.list(favorite=True) == []
        assert store.toggle_favorite("missing") is None
    finally:
        store.close()


def test_parses_files_and_ignores_exports(tmp_path: Path) -> None:
    save_dir = tmp_path / "shots"
    save_dir.mkdir()
    Image.new("RGB", (20, 10)).save(
        save_dir / "screenshot_20261022_101112_123_region_20x10.png"
    )
    Image.new("RGB", (30, 20)).save(
        save_dir / "screenshot_20261022_101113_456_window_30x20_fav.png"
    )
    # Old exports and unrelated images must not appear in the recent list.
    Image.new("RGB", (10, 10)).save(
        save_dir / "screenshot_20261022_101114.png"
    )
    Image.new("RGB", (10, 10)).save(save_dir / "random.png")

    store = make_store(tmp_path)
    try:
        entries = store.list()
        assert len(entries) == 2
        assert {entry.mode for entry in entries} == {"region", "window"}
        window = next(entry for entry in entries if entry.mode == "window")
        assert window.favorite is True
        assert (window.width, window.height) == (30, 20)
        assert window.id == "20261022_101113_456_window"
        assert store.list(favorite=True) == [window]
        assert store.list(mode="region")[0].width == 20
    finally:
        store.close()


def test_clear_removes_managed_files(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        store.add_png(png_bytes(), mode="region")
        store.add_png(png_bytes(), mode="window")
        assert store.clear() == 2
        assert store.list() == []
        assert list((tmp_path / "shots").glob("screenshot_*")) == []
    finally:
        store.close()


def test_migrates_legacy_database_once(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    images_dir = data_dir / "images"
    images_dir.mkdir(parents=True)
    legacy_image = images_dir / "legacy.png"
    legacy_image.write_bytes(png_bytes(20, 10))
    shots_dir = tmp_path / "shots"
    shots_dir.mkdir()
    legacy_export = shots_dir / "screenshot_20261020_113305.png"
    legacy_export.write_bytes(png_bytes(20, 10))
    database = data_dir / "recent.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE shots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          mode TEXT NOT NULL,
          width INTEGER NOT NULL,
          height INTEGER NOT NULL,
          png_path TEXT NOT NULL,
          thumb_path TEXT NOT NULL,
          byte_size INTEGER NOT NULL,
          saved_path TEXT,
          annotation_count INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL DEFAULT '',
          favorite INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.execute(
        """
        INSERT INTO shots (
          created_at, updated_at, mode, width, height, png_path, thumb_path,
          byte_size, saved_path, annotation_count, source, favorite
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'legacy', 1)
        """,
        (
            1792650000.123,
            1792650000.123,
            "region",
            20,
            10,
            "images/legacy.png",
            "thumbs/legacy.png",
            len(legacy_image.read_bytes()),
            str(legacy_export),
        ),
    )
    connection.commit()
    connection.close()

    first = make_store(tmp_path)
    try:
        entries = first.list()
        assert len(entries) == 1
        migrated = entries[0]
        assert migrated.favorite is True
        assert migrated.mode == "region"
        assert migrated.path.name.endswith("_region_20x10_fav.png")
        assert migrated.path.exists()
        assert not legacy_export.exists()
        assert (data_dir / "recent.db.migrated").exists()
    finally:
        first.close()

    second = make_store(tmp_path)
    try:
        assert len(second.list()) == 1
    finally:
        second.close()


def test_manually_deleted_source_removes_thumbnail_cache(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    try:
        entry = store.add_png(png_bytes(200, 100), mode="region")
        thumb = store.thumb_path(entry)
        assert thumb is not None and thumb.exists()

        entry.path.unlink()
        assert store.list() == []

        assert not thumb.exists()
    finally:
        store.close()


def test_cleanup_removes_orphan_cache_and_temp_files(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    try:
        entry = store.add_png(png_bytes(200, 100), mode="region")
        thumb = store.thumb_path(entry)
        assert thumb is not None and thumb.exists()
        orphan = store.thumbs_dir / "legacy_hash.png"
        orphan.write_bytes(b"stale")
        stale_tmp = store.thumbs_dir / ".thumb.png.interrupted.tmp"
        stale_tmp.write_bytes(b"stale")
        unrelated = store.thumbs_dir / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")

        assert store.list() == [entry]

        assert not orphan.exists()
        assert not stale_tmp.exists()
        assert unrelated.exists()
        assert thumb.exists()
    finally:
        store.close()


def test_cleanup_keeps_thumbs_when_save_dir_unreadable(
    tmp_path: Path, monkeypatch
) -> None:
    store = make_store(tmp_path)
    try:
        entry = store.add_png(png_bytes(200, 100), mode="region")
        thumb = store.thumb_path(entry)
        assert thumb is not None and thumb.exists()
        orphan = store.thumbs_dir / "legacy_hash.png"
        orphan.write_bytes(b"stale")

        monkeypatch.setattr(store, "_scan_entries", lambda: None)
        assert store._cleanup_orphan_thumbs() == 0

        assert thumb.exists()
        assert orphan.exists()
    finally:
        store.close()


def test_thumb_cache_is_generated(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    try:
        entry = store.add_png(png_bytes(200, 100), mode="region")
        thumb = store.thumb_path(entry)
        assert thumb is not None and thumb.exists()
        before = thumb.stat().st_mtime
        time.sleep(0.01)
        updated = store.update_png(entry.id, png_bytes(100, 200))
        assert updated is not None
        thumb_after = store.thumb_path(updated)
        assert thumb_after is not None and thumb_after.exists()
        assert thumb_after.stat().st_mtime >= before
    finally:
        store.close()
