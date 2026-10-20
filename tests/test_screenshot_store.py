from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from quicktools.plugins.screenshot.recent.store import RecentStore, RecentStoreError


def png_bytes(width: int = 20, height: int = 10, color=(1, 2, 3)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, "PNG")
    return output.getvalue()


def test_add_list_update_delete(tmp_path: Path) -> None:
    store = RecentStore(tmp_path)
    try:
        entry = store.add_png(png_bytes(), mode="region", source="test")
        assert entry.width == 20
        assert entry.height == 10
        assert store.list() == [entry]
        assert store.image_path(entry) is not None
        assert store.thumb_path(entry) is not None

        updated = store.update_png(entry.id, png_bytes(30, 40), annotation_count=2)
        assert updated is not None
        assert updated.width == 30
        assert updated.height == 40
        assert updated.annotation_count == 2

        saved = tmp_path / "saved.png"
        store.mark_saved(entry.id, saved)
        assert store.get(entry.id).saved_path == str(saved)

        image_path = store.image_path(entry)
        assert image_path is not None
        assert store.delete(entry.id)
        assert not image_path.exists()
        assert store.list() == []
    finally:
        store.close()


def test_invalid_png_is_rejected(tmp_path: Path) -> None:
    store = RecentStore(tmp_path)
    try:
        with pytest.raises(RecentStoreError):
            store.add_png(b"not png", mode="region")
    finally:
        store.close()


def test_prune_by_entries_and_bytes(tmp_path: Path) -> None:
    store = RecentStore(tmp_path)
    try:
        entries = [
            store.add_png(png_bytes(20, 20), mode="region") for _ in range(5)
        ]
        removed = store.prune(max_entries=2, max_bytes=10 * 1024 * 1024)
        assert removed == 3
        remaining = store.list()
        assert len(remaining) == 2
        assert {entry.id for entry in remaining} == {entries[-1].id, entries[-2].id}

        removed = store.prune(max_entries=10, max_bytes=1)
        assert removed == 2
        assert store.list() == []
    finally:
        store.close()


def test_favorite_filters_and_toggle(tmp_path: Path) -> None:
    store = RecentStore(tmp_path)
    try:
        region_a = store.add_png(png_bytes(), mode="region")
        window = store.add_png(png_bytes(), mode="window")
        region_b = store.add_png(png_bytes(), mode="region")
        assert region_a.favorite is False

        starred = store.set_favorite(window.id, True)
        assert starred is not None and starred.favorite is True
        assert store.get(window.id).favorite is True
        assert [entry.id for entry in store.list(favorite=True)] == [window.id]
        assert {entry.id for entry in store.list(mode="region")} == {
            region_a.id,
            region_b.id,
        }
        assert [entry.id for entry in store.list(favorite=True, mode="window")] == [
            window.id
        ]

        toggled = store.toggle_favorite(window.id)
        assert toggled is not None and toggled.favorite is False
        assert store.list(favorite=True) == []
        assert store.toggle_favorite(999999) is None
    finally:
        store.close()


def test_favorite_column_migrates_old_database(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "recent.db"
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
          source TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO shots (
          created_at, updated_at, mode, width, height, png_path, thumb_path,
          byte_size, saved_path, annotation_count, source
        ) VALUES (1, 1, 'region', 10, 10, 'images/a.png', 'thumbs/a.png', 10,
                  NULL, 0, '');
        PRAGMA user_version=1;
        """
    )
    connection.commit()
    connection.close()

    store = RecentStore(tmp_path)
    try:
        entries = store.list()
        assert len(entries) == 1
        assert entries[0].favorite is False
        updated = store.set_favorite(entries[0].id, True)
        assert updated is not None and updated.favorite is True
    finally:
        store.close()

    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(shots)").fetchall()
        }
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    assert "favorite" in columns
    assert version == 2
