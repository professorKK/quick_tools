"""SQLite-backed recent screenshot history with cached thumbnails."""

from __future__ import annotations

import io
import logging
import os
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

THUMB_MAX_SIDE = 360
MAX_IMAGE_BYTES = 50 * 1024 * 1024


class RecentStoreError(Exception):
    """Raised when a screenshot cannot be stored or read."""


@dataclass(frozen=True)
class RecentEntry:
    id: int
    created_at: float
    updated_at: float
    mode: str
    width: int
    height: int
    png_path: str
    thumb_path: str
    byte_size: int
    saved_path: str | None
    annotation_count: int
    source: str
    favorite: bool = False


class RecentStore:
    """Store screenshot originals and thumbnails under the plugin data dir.

    All methods must be called on the Tk main thread.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.data_dir / "recent.db")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS shots (
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
            CREATE INDEX IF NOT EXISTS idx_shots_updated
              ON shots(updated_at DESC, id DESC);
            """
        )
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(shots)").fetchall()
        }
        if "favorite" not in columns:
            self._conn.execute(
                "ALTER TABLE shots ADD COLUMN "
                "favorite INTEGER NOT NULL DEFAULT 0"
            )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shots_favorite "
            "ON shots(favorite, updated_at DESC, id DESC)"
        )
        self._conn.execute("PRAGMA user_version=2")
        self._conn.commit()

    # ------------------------------------------------------------ lifecycle
    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # -------------------------------------------------------------- helpers
    def _safe_path(self, relative: str) -> Path | None:
        if not relative:
            return None
        candidate = Path(relative)
        if candidate.is_absolute():
            return None
        resolved = (self.data_dir / candidate).resolve()
        try:
            resolved.relative_to(self.data_dir.resolve())
        except ValueError:
            return None
        return resolved

    @staticmethod
    def _normalize_png(png: bytes) -> tuple[bytes, int, int]:
        if not isinstance(png, (bytes, bytearray)) or not png:
            raise RecentStoreError("截图图片数据为空")
        payload = bytes(png)
        if len(payload) > MAX_IMAGE_BYTES:
            raise RecentStoreError("截图图片过大")
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                width, height = image.size
                if image.format != "PNG":
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    payload = buffer.getvalue()
        except RecentStoreError:
            raise
        except Exception as exc:
            raise RecentStoreError("截图图片数据无效") from exc
        if width <= 0 or height <= 0:
            raise RecentStoreError("截图图片尺寸无效")
        return payload, width, height

    def _write_png(self, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(handle.name)
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _write_thumbnail(self, payload: bytes, path: Path) -> None:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                thumb = image.copy()
            thumb.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
            buffer = io.BytesIO()
            thumb.save(buffer, format="PNG")
            self._write_png(path, buffer.getvalue())
        except Exception:
            log.exception("生成截图缩略图失败")
            self._write_png(path, payload)

    def _remove_files(self, entry: RecentEntry) -> None:
        for relative in (entry.png_path, entry.thumb_path):
            path = self._safe_path(relative)
            if path is not None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    log.debug("删除截图文件失败：%s", path, exc_info=True)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> RecentEntry:
        return RecentEntry(
            id=int(row["id"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            mode=str(row["mode"]),
            width=int(row["width"]),
            height=int(row["height"]),
            png_path=str(row["png_path"]),
            thumb_path=str(row["thumb_path"]),
            byte_size=int(row["byte_size"]),
            saved_path=row["saved_path"],
            annotation_count=int(row["annotation_count"]),
            source=str(row["source"] or ""),
            favorite=bool(row["favorite"]),
        )

    # --------------------------------------------------------------- mutate
    def add_png(self, png: bytes, *, mode: str, source: str = "") -> RecentEntry:
        payload, width, height = self._normalize_png(png)
        name = uuid.uuid4().hex
        png_relative = f"images/{name}.png"
        thumb_relative = f"thumbs/{name}.png"
        png_path = self._safe_path(png_relative)
        thumb_path = self._safe_path(thumb_relative)
        if png_path is None or thumb_path is None:
            raise RecentStoreError("截图存储路径无效")
        self._write_png(png_path, payload)
        self._write_thumbnail(payload, thumb_path)
        now = time.time()
        try:
            cursor = self._conn.execute(
                """
                INSERT INTO shots (
                  created_at, updated_at, mode, width, height,
                  png_path, thumb_path, byte_size, saved_path,
                  annotation_count, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?)
                """,
                (
                    now,
                    now,
                    mode,
                    width,
                    height,
                    png_relative,
                    thumb_relative,
                    len(payload),
                    source,
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            for path in (png_path, thumb_path):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        entry = self.get(int(cursor.lastrowid))
        if entry is None:
            raise RecentStoreError("无法读取新建的截图记录")
        return entry

    def update_png(
        self, entry_id: int, png: bytes, *, annotation_count: int = 0
    ) -> RecentEntry | None:
        entry = self.get(entry_id)
        if entry is None:
            return None
        payload, width, height = self._normalize_png(png)
        png_path = self._safe_path(entry.png_path)
        thumb_path = self._safe_path(entry.thumb_path)
        if png_path is None or thumb_path is None:
            raise RecentStoreError("截图存储路径无效")
        self._write_png(png_path, payload)
        self._write_thumbnail(payload, thumb_path)
        self._conn.execute(
            """
            UPDATE shots SET updated_at = ?, width = ?, height = ?,
              byte_size = ?, annotation_count = ?
            WHERE id = ?
            """,
            (
                time.time(),
                width,
                height,
                len(payload),
                max(0, int(annotation_count)),
                entry_id,
            ),
        )
        self._conn.commit()
        return self.get(entry_id)

    def mark_saved(self, entry_id: int, path: Path) -> None:
        self._conn.execute(
            "UPDATE shots SET saved_path = ?, updated_at = ? WHERE id = ?",
            (str(path), time.time(), entry_id),
        )
        self._conn.commit()

    def set_favorite(
        self, entry_id: int, favorite: bool
    ) -> RecentEntry | None:
        """Set the favorite flag without changing the sort timestamp."""

        self._conn.execute(
            "UPDATE shots SET favorite = ? WHERE id = ?",
            (1 if favorite else 0, int(entry_id)),
        )
        self._conn.commit()
        return self.get(entry_id)

    def toggle_favorite(self, entry_id: int) -> RecentEntry | None:
        entry = self.get(entry_id)
        if entry is None:
            return None
        return self.set_favorite(entry.id, not entry.favorite)

    def delete(self, entry_id: int) -> bool:
        entry = self.get(entry_id)
        if entry is None:
            return False
        self._conn.execute("DELETE FROM shots WHERE id = ?", (entry_id,))
        self._conn.commit()
        self._remove_files(entry)
        return True

    def clear(self) -> int:
        rows = self.list(limit=100000)
        self._conn.execute("DELETE FROM shots")
        self._conn.commit()
        for entry in rows:
            self._remove_files(entry)
        return len(rows)

    def prune(self, *, max_entries: int, max_bytes: int) -> int:
        removed = 0
        rows = self.list(limit=100000)
        keep_count = max(1, int(max_entries))
        for entry in rows[keep_count:]:
            if self.delete(entry.id):
                removed += 1
        rows = self.list(limit=100000)
        total = sum(entry.byte_size for entry in rows)
        for entry in reversed(rows):
            if total <= max_bytes:
                break
            if self.delete(entry.id):
                removed += 1
                total -= entry.byte_size
        return removed

    # --------------------------------------------------------------- query
    def list(
        self,
        limit: int = 100,
        *,
        favorite: bool | None = None,
        mode: str | None = None,
    ) -> list[RecentEntry]:
        clauses: list[str] = []
        params: list[object] = []
        if favorite is not None:
            clauses.append("favorite = ?")
            params.append(1 if favorite else 0)
        if mode:
            clauses.append("mode = ?")
            params.append(mode.strip().lower())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        rows = self._conn.execute(
            f"""
            SELECT * FROM shots
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get(self, entry_id: int) -> RecentEntry | None:
        row = self._conn.execute(
            "SELECT * FROM shots WHERE id = ?", (int(entry_id),)
        ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def image_path(self, entry: RecentEntry) -> Path | None:
        path = self._safe_path(entry.png_path)
        return path if path is not None and path.exists() else None

    def thumb_path(self, entry: RecentEntry) -> Path | None:
        path = self._safe_path(entry.thumb_path)
        return path if path is not None and path.exists() else None
