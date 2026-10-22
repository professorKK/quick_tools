"""SQLite history and clipboard image storage."""

from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageOps

from .models import (
    ClipboardContent,
    ClipboardEntry,
    ClipboardError,
    ClipboardKind,
    ClipboardTooLarge,
    content_digest,
    current_platform,
    display_name_for_paths,
    kind_value,
)
from .platform_utils import first_line

log = logging.getLogger(__name__)

MAX_SINGLE_IMAGE_BYTES = 50 * 1024 * 1024
THUMB_MAX_SIDE = 360
ORPHAN_GRACE_SECONDS = 60.0
STALE_TEMP_SECONDS = 60.0


@dataclass(frozen=True)
class MaintenanceStats:
    missing_images: int = 0
    orphan_images: int = 0
    orphan_thumbs: int = 0
    temp_files: int = 0

    @property
    def total(self) -> int:
        return (
            self.missing_images
            + self.orphan_images
            + self.orphan_thumbs
            + self.temp_files
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ClipboardStore:
    """Persist clipboard history below the plugin's private data directory.

    All methods expect to be called from the Tk main thread. The service owns
    one store for the lifetime of the application and closes it on shutdown.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir = self.data_dir / "images"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "history.db"
        self._clock = clock
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        self.maintenance()

    # ------------------------------------------------------------- schema
    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK (kind IN ('text','image','files')),
                    digest TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    text_content TEXT,
                    image_path TEXT,
                    thumb_path TEXT,
                    files_json TEXT,
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    source TEXT,
                    source_platform TEXT NOT NULL,
                    copy_count INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    last_copied_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_last "
                "ON entries(last_copied_at DESC, id DESC)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_kind "
                "ON entries(kind, last_copied_at DESC)"
            )
            self._conn.execute("PRAGMA user_version = 1")

    # --------------------------------------------------------------- add
    def add(
        self,
        content: ClipboardContent,
        *,
        max_image_bytes: int = 200 * 1024 * 1024,
    ) -> ClipboardEntry:
        """Insert a snapshot, or bump an existing identical entry to the top."""
        digest = content_digest(content)
        existing = self._conn.execute(
            "SELECT * FROM entries WHERE digest = ?", (digest,)
        ).fetchone()
        now = self._clock()
        if existing is not None:
            with self._conn:
                self._conn.execute(
                    "UPDATE entries SET last_copied_at = ?, "
                    "copy_count = copy_count + 1, "
                    "source = COALESCE(?, source) WHERE id = ?",
                    (now, content.source, existing["id"]),
                )
            return self._row_to_entry(
                self._conn.execute(
                    "SELECT * FROM entries WHERE id = ?", (existing["id"],)
                ).fetchone()
            )

        image_path: str | None = None
        thumb_path: str | None = None
        files: tuple[str, ...] = ()
        title = ""
        text_content: str | None = None
        byte_size = 0
        char_count = 0
        kind = kind_value(content.kind)

        if kind == "text":
            text = content.text or ""
            text_content = text
            title = first_line(text)
            byte_size = len(text.encode("utf-8"))
            char_count = len(text)
        elif kind == "image":
            limit = min(MAX_SINGLE_IMAGE_BYTES, max(1, int(max_image_bytes)))
            image_path, thumb_path, byte_size, title = self._save_image(
                content.image_png or b"", limit
            )
        else:
            files = tuple(path for path in content.paths if path)
            title = display_name_for_paths(files, content.platform)
            byte_size = self._file_total_size(files, content.platform)
            thumb_path = self._file_thumbnail(files, content.platform)
            if thumb_path is None and files:
                thumb_path = None

        try:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    INSERT INTO entries (
                        kind, digest, title, text_content, image_path, thumb_path,
                        files_json, byte_size, char_count, source, source_platform,
                        copy_count, created_at, last_copied_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        kind,
                        digest,
                        title,
                        text_content,
                        image_path,
                        thumb_path,
                        json.dumps(files, ensure_ascii=False) if files else None,
                        byte_size,
                        char_count,
                        content.source,
                        content.platform,
                        now,
                        now,
                    ),
                )
                entry_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            # A previous panel/process may have inserted the same digest.
            self._delete_owned_paths((image_path, thumb_path))
            row = self._conn.execute(
                "SELECT * FROM entries WHERE digest = ?", (digest,)
            ).fetchone()
            if row is None:
                raise
            return self._row_to_entry(row)
        except Exception:
            self._delete_owned_paths((image_path, thumb_path))
            raise

        row = self._conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return self._row_to_entry(row)

    # ------------------------------------------------------------ images
    def _save_image(
        self, png: bytes, limit: int
    ) -> tuple[str, str, int, str]:
        if not png:
            raise ClipboardError("空图片")
        if len(png) > limit:
            raise ClipboardTooLarge(
                f"图片超过 {limit // (1024 * 1024)} MB，已跳过"
            )
        image = None
        thumb = None
        temp_image: Path | None = None
        temp_thumb: Path | None = None
        image_rel = thumb_rel = ""
        try:
            with Image.open(io.BytesIO(png)) as source:
                source.load()
                image = source.copy()
            original = image
            image = ImageOps.exif_transpose(image)
            if image is not original:
                original.close()
            width, height = image.size
            token = uuid.uuid4().hex
            image_rel = f"images/{token}.png"
            thumb_rel = f"thumbs/{token}.png"
            image_file = self.data_dir / image_rel
            thumb_file = self.data_dir / thumb_rel

            temp_image = image_file.with_name(f".{token}.tmp")
            if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                image = image.convert("RGBA")
            image.save(temp_image, format="PNG")
            os.replace(temp_image, image_file)
            temp_image = None

            thumb = image.copy()
            thumb.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
            if thumb.mode == "P":
                thumb = thumb.convert("RGBA")
            temp_thumb = thumb_file.with_name(f".{token}.tmp")
            thumb.save(temp_thumb, format="PNG")
            os.replace(temp_thumb, thumb_file)
            temp_thumb = None

            size = image_file.stat().st_size
            return image_rel, thumb_rel, size, f"图片 {width}×{height}"
        except Image.UnidentifiedImageError as exc:
            self._delete_owned_paths((image_rel, thumb_rel))
            raise ClipboardError("无法读取剪贴板图片") from exc
        except Exception as exc:
            self._delete_owned_paths((image_rel, thumb_rel))
            raise ClipboardError(f"保存图片失败：{exc}") from exc
        finally:
            for handle in (thumb, image):
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
            for temp in (temp_image, temp_thumb):
                if temp is not None:
                    try:
                        temp.unlink(missing_ok=True)
                    except OSError:
                        pass

    def _file_thumbnail(self, files: tuple[str, ...], platform: str) -> str | None:
        if len(files) != 1 or platform != current_platform():
            return None
        path = Path(files[0])
        try:
            if not path.is_file() or path.stat().st_size > MAX_SINGLE_IMAGE_BYTES:
                return None
            with Image.open(path) as source:
                source.load()
                thumb = source.copy()
        except Exception:
            return None
        token = uuid.uuid4().hex
        rel = f"thumbs/{token}.png"
        target = self.data_dir / rel
        temp = target.with_name(f".{token}.tmp")
        try:
            thumb.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
            if thumb.mode == "P":
                thumb = thumb.convert("RGBA")
            thumb.save(temp, format="PNG")
            os.replace(temp, target)
            temp = None
            return rel
        except Exception:
            return None
        finally:
            thumb.close()
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _file_total_size(files: tuple[str, ...], platform: str) -> int:
        if platform != current_platform():
            return 0
        total = 0
        for path in files:
            try:
                total += os.path.getsize(path)
            except (OSError, ValueError):
                continue
        return total

    # -------------------------------------------------------------- read
    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> ClipboardEntry:
        raw_files = row["files_json"]
        try:
            files = tuple(json.loads(raw_files)) if raw_files else ()
        except (TypeError, ValueError):
            files = ()
        return ClipboardEntry(
            id=int(row["id"]),
            kind=ClipboardKind(row["kind"]),
            digest=row["digest"],
            title=row["title"],
            text_content=row["text_content"],
            image_path=row["image_path"],
            thumb_path=row["thumb_path"],
            paths=files,
            byte_size=int(row["byte_size"] or 0),
            char_count=int(row["char_count"] or 0),
            source=row["source"],
            source_platform=row["source_platform"],
            copy_count=int(row["copy_count"] or 1),
            created_at=float(row["created_at"]),
            last_copied_at=float(row["last_copied_at"]),
        )

    def get(self, entry_id: int) -> ClipboardEntry | None:
        row = self._conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def list_entries(
        self,
        kind: ClipboardKind | None = None,
        query: str = "",
        *,
        newest_first: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ClipboardEntry]:
        clauses: list[str] = []
        params: list[object] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value)
        cleaned = query.strip()
        if cleaned:
            pattern = f"%{_escape_like(cleaned)}%"
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR "
                "COALESCE(text_content, '') LIKE ? ESCAPE '\\' OR "
                "COALESCE(files_json, '') LIKE ? ESCAPE '\\')"
            )
            params.extend((pattern, pattern, pattern))
        sql = "SELECT * FROM entries"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        order = "DESC" if newest_first else "ASC"
        sql += f" ORDER BY last_copied_at {order}, id {order}"
        offset = max(0, int(offset))
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend((max(0, int(limit)), offset))
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(offset)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def counts(self) -> dict[str, int]:
        result = {"all": 0, "text": 0, "image": 0, "files": 0}
        for row in self._conn.execute(
            "SELECT kind, COUNT(*) AS total FROM entries GROUP BY kind"
        ):
            result[str(row["kind"])] = int(row["total"])
            result["all"] += int(row["total"])
        return result

    # ------------------------------------------------------------ mutate
    def mark_copied(self, entry_id: int) -> ClipboardEntry | None:
        """Count a manual re-copy without moving the entry to the top.

        Only fresh ``add()`` calls update ``last_copied_at`` and therefore the
        history order.  Clicking "二次复制" in the history is a paste helper,
        not a new capture, and must leave the list position unchanged.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE entries SET copy_count = copy_count + 1 WHERE id = ?",
                (entry_id,),
            )
        return self.get(entry_id)

    def update_text(self, entry_id: int, text: str) -> ClipboardEntry | None:
        """Save an edited text entry without changing its history position.

        If the new content is identical to another text entry, the edited row
        is merged into that existing row (duplicate digests are not allowed).
        """
        row = self._conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None or row["kind"] != ClipboardKind.TEXT.value:
            return None
        if not text.strip():
            raise ClipboardError("文本内容不能为空")

        digest = content_digest(
            ClipboardContent(kind=ClipboardKind.TEXT, text=text)
        )
        if digest != row["digest"]:
            duplicate = self._conn.execute(
                "SELECT * FROM entries WHERE digest = ? AND id <> ?",
                (digest, entry_id),
            ).fetchone()
            if duplicate is not None:
                with self._conn:
                    self._conn.execute(
                        "DELETE FROM entries WHERE id = ?", (entry_id,)
                    )
                self._delete_owned_paths(
                    (row["image_path"], row["thumb_path"])
                )
                return self._row_to_entry(duplicate)

        with self._conn:
            self._conn.execute(
                "UPDATE entries SET text_content = ?, digest = ?, title = ?, "
                "char_count = ?, byte_size = ? WHERE id = ?",
                (
                    text,
                    digest,
                    first_line(text),
                    len(text),
                    len(text.encode("utf-8")),
                    entry_id,
                ),
            )
        return self.get(entry_id)

    def delete(self, entry_id: int) -> bool:
        row = self._conn.execute(
            "SELECT image_path, thumb_path FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return False
        with self._conn:
            self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self._delete_owned_paths((row["image_path"], row["thumb_path"]))
        return True

    def clear(self) -> int:
        rows = self._conn.execute(
            "SELECT image_path, thumb_path FROM entries"
        ).fetchall()
        with self._conn:
            self._conn.execute("DELETE FROM entries")
        for row in rows:
            self._delete_owned_paths((row["image_path"], row["thumb_path"]))
        return len(rows)

    @staticmethod
    def _owned_name(relative: str | None, subdir: str) -> str | None:
        if not relative:
            return None
        candidate = Path(relative)
        if candidate.is_absolute():
            return None
        try:
            parts = candidate.relative_to(subdir)
        except ValueError:
            return None
        if len(parts.parts) != 1:
            return None
        return parts.name

    @staticmethod
    def _scan_owned(directory: Path):
        files: dict[str, float] = {}
        temps: list[tuple[Path, float]] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    try:
                        if entry.is_symlink() or not entry.is_file(
                            follow_symlinks=False
                        ):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.name.endswith(".tmp"):
                        temps.append((Path(entry.path), stat.st_mtime))
                    else:
                        files[entry.name] = stat.st_mtime
        except OSError:
            log.exception("剪贴板：扫描数据目录失败 %s", directory)
            return None, []
        return files, temps

    def maintenance(
        self,
        *,
        orphan_grace_seconds: float = ORPHAN_GRACE_SECONDS,
        temp_grace_seconds: float = STALE_TEMP_SECONDS,
    ) -> MaintenanceStats:
        """Remove missing image rows and unreferenced/temporary files."""
        try:
            rows = self._conn.execute(
                "SELECT id, kind, image_path, thumb_path FROM entries"
            ).fetchall()
        except Exception:
            log.exception("剪贴板：读取维护数据失败")
            return MaintenanceStats()
        image_refs: set[str] = set()
        thumb_refs: set[str] = set()
        for row in rows:
            name = self._owned_name(row["image_path"], "images")
            if name:
                image_refs.add(name)
            name = self._owned_name(row["thumb_path"], "thumbs")
            if name:
                thumb_refs.add(name)

        images, image_temps = self._scan_owned(self.images_dir)
        thumbs, thumb_temps = self._scan_owned(self.thumbs_dir)

        missing_images = 0
        if images is not None:
            missing = [
                row
                for row in rows
                if row["kind"] == "image"
                and (
                    self._owned_name(row["image_path"], "images")
                    not in images
                )
            ]
            if missing:
                with self._conn:
                    self._conn.executemany(
                        "DELETE FROM entries WHERE id = ?",
                        [(row["id"],) for row in missing],
                    )
                for row in missing:
                    self._delete_owned_paths(
                        (row["image_path"], row["thumb_path"])
                    )
                    name = self._owned_name(row["thumb_path"], "thumbs")
                    if name:
                        thumb_refs.discard(name)
                missing_images = len(missing)
                image_refs = {
                    name for name in image_refs if name in images
                }
                log.warning(
                    "剪贴板：清理 %d 条原图缺失的图片记录",
                    missing_images,
                )

        now = time.time()
        orphan_images = 0
        if images is not None:
            for name, mtime in images.items():
                if name in image_refs:
                    continue
                if now - mtime < orphan_grace_seconds:
                    continue
                try:
                    (self.images_dir / name).unlink()
                    orphan_images += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    log.debug("剪贴板：删除孤儿图片失败 %s", name, exc_info=True)

        orphan_thumbs = 0
        if thumbs is not None:
            for name, mtime in thumbs.items():
                if name in thumb_refs:
                    continue
                if now - mtime < orphan_grace_seconds:
                    continue
                try:
                    (self.thumbs_dir / name).unlink()
                    orphan_thumbs += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    log.debug("剪贴板：删除孤儿缩略图失败 %s", name, exc_info=True)

        temp_files = 0
        for path, mtime in (*image_temps, *thumb_temps):
            if now - mtime < temp_grace_seconds:
                continue
            try:
                path.unlink()
                temp_files += 1
            except FileNotFoundError:
                pass
            except OSError:
                log.debug("剪贴板：删除临时文件失败 %s", path, exc_info=True)

        stats = MaintenanceStats(
            missing_images=missing_images,
            orphan_images=orphan_images,
            orphan_thumbs=orphan_thumbs,
            temp_files=temp_files,
        )
        if stats.total:
            log.warning(
                "剪贴板维护：缺失图片=%d 孤儿图片=%d 孤儿缩略图=%d 临时文件=%d",
                stats.missing_images,
                stats.orphan_images,
                stats.orphan_thumbs,
                stats.temp_files,
            )
        return stats

    def remove_missing_images(self) -> int:
        """Compatibility wrapper: maintenance for missing image rows."""
        return self.maintenance().missing_images

    def prune(self, *, max_entries: int, max_image_bytes: int) -> int:
        """Drop old rows and old images, deleting only plugin-owned files."""
        max_entries = max(1, int(max_entries))
        max_image_bytes = max(0, int(max_image_bytes))
        removed = 0

        overflow = self._conn.execute(
            "SELECT id, image_path, thumb_path FROM entries "
            "ORDER BY last_copied_at DESC, id DESC LIMIT -1 OFFSET ?",
            (max_entries,),
        ).fetchall()
        if overflow:
            with self._conn:
                self._conn.executemany(
                    "DELETE FROM entries WHERE id = ?",
                    [(row["id"],) for row in overflow],
                )
            for row in overflow:
                self._delete_owned_paths((row["image_path"], row["thumb_path"]))
            removed += len(overflow)

        images = self._conn.execute(
            "SELECT id, image_path, thumb_path, byte_size FROM entries "
            "WHERE kind = 'image' ORDER BY last_copied_at DESC, id DESC"
        ).fetchall()
        total = 0
        stale: list[sqlite3.Row] = []
        for row in images:
            total += int(row["byte_size"] or 0)
            if total > max_image_bytes:
                stale.append(row)
        if stale:
            with self._conn:
                self._conn.executemany(
                    "DELETE FROM entries WHERE id = ?",
                    [(row["id"],) for row in stale],
                )
            for row in stale:
                self._delete_owned_paths((row["image_path"], row["thumb_path"]))
            removed += len(stale)
        return removed

    # ------------------------------------------------------------ files
    def image_file(self, entry: ClipboardEntry) -> Path | None:
        return self._absolute(entry.image_path)

    def thumb_file(self, entry: ClipboardEntry) -> Path | None:
        return self._absolute(entry.thumb_path)

    def image_bytes(self, entry: ClipboardEntry) -> bytes | None:
        path = self.image_file(entry)
        if path is None:
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def _absolute(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        target = (self.data_dir / relative).resolve()
        try:
            target.relative_to(self.data_dir.resolve())
        except ValueError:
            return None
        return target if target.is_file() else None

    def _delete_owned_paths(self, paths: Iterable[str | None]) -> None:
        root = self.data_dir.resolve()
        for relative in paths:
            if not relative:
                continue
            target = (self.data_dir / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                continue
            if target.parent not in (self.images_dir.resolve(), self.thumbs_dir.resolve()):
                continue
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
