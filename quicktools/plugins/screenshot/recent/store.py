"""File-backed recent screenshot history.

Screenshots live directly in the configured save directory. Metadata is encoded
in the file name instead of a database:

    screenshot_<YYYYMMDD>_<HHMMSS>_<mmm>_<mode>[_N]_<W>x<H>[_fav].<ext>

The optional ``_N`` disambiguates files captured in the same millisecond, and
``_fav`` marks a favorite. Scanning the directory at read time keeps the list
in sync with the file manager and lets users search favorites by file name.
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

THUMB_MAX_SIDE = 360
MAX_IMAGE_BYTES = 50 * 1024 * 1024
_FAV_SUFFIX = "_fav"
_NAME_RE = re.compile(
    r"^screenshot_(?P<date>\d{8})_(?P<time>\d{6})_(?P<ms>\d{3})_"
    r"(?P<mode>[a-z]+)(?:_(?P<index>\d+))?_"
    r"(?P<width>\d+)x(?P<height>\d+)(?P<fav>_fav)?"
    r"(?P<ext>\.(?:png|jpg|jpeg|webp))$",
    re.IGNORECASE,
)


class RecentStoreError(Exception):
    """Raised when a screenshot cannot be stored or read."""


@dataclass(frozen=True)
class RecentEntry:
    id: str
    path: Path
    created_at: float
    updated_at: float
    mode: str
    width: int
    height: int
    byte_size: int
    favorite: bool = False

    @property
    def name(self) -> str:
        return self.path.name


class RecentStore:
    """Scan the screenshot save directory and manage its image files.

    All methods must be called on the Tk main thread. Thumbnails are cached in
    ``<data_dir>/thumbs``; the cache is not a database and can be deleted at
    any time.
    """

    def __init__(self, data_dir: Path, save_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.thumbs_dir = self.data_dir / "thumbs"
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        self._save_dir = (
            Path(save_dir) if save_dir is not None else self.data_dir
        )
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_db()

    # ------------------------------------------------------------ lifecycle
    @property
    def save_dir(self) -> Path:
        return self._save_dir

    def set_save_dir(self, path: Path | str) -> None:
        self._save_dir = Path(path)
        self._save_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """Kept for API compatibility; the file store has nothing to close."""

    # -------------------------------------------------------------- helpers
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

    @staticmethod
    def _timestamp_parts(stamp: float) -> tuple[str, str, str]:
        moment = datetime.fromtimestamp(float(stamp))
        return (
            moment.strftime("%Y%m%d"),
            moment.strftime("%H%M%S"),
            f"{moment.microsecond // 1000:03d}",
        )

    @staticmethod
    def _make_name(
        date: str,
        clock: str,
        millis: str,
        mode: str,
        width: int,
        height: int,
        *,
        index: int = 0,
        favorite: bool = False,
        extension: str = ".png",
    ) -> str:
        stem = f"screenshot_{date}_{clock}_{millis}_{mode}"
        if index > 0:
            stem += f"_{index}"
        stem += f"_{width}x{height}"
        if favorite:
            stem += _FAV_SUFFIX
        return f"{stem}{extension}"

    @staticmethod
    def _entry_id(
        date: str, clock: str, millis: str, mode: str, index: int = 0
    ) -> str:
        value = f"{date}_{clock}_{millis}_{mode}"
        return f"{value}_{index}" if index > 0 else value

    def _entry_from_path(self, path: Path) -> RecentEntry | None:
        match = _NAME_RE.match(path.name)
        if match is None:
            return None
        try:
            stamp = datetime.strptime(
                f"{match.group('date')}_{match.group('time')}_"
                f"{match.group('ms')}",
                "%Y%m%d_%H%M%S_%f",
            ).timestamp()
            stat = path.stat()
        except (ValueError, OSError):
            return None
        if not path.is_file():
            return None
        index = int(match.group("index") or 0)
        return RecentEntry(
            id=self._entry_id(
                match.group("date"),
                match.group("time"),
                match.group("ms"),
                match.group("mode").lower(),
                index,
            ),
            path=path,
            created_at=stamp,
            updated_at=max(stamp, float(stat.st_mtime)),
            mode=match.group("mode").lower(),
            width=int(match.group("width")),
            height=int(match.group("height")),
            byte_size=int(stat.st_size),
            favorite=bool(match.group("fav")),
        )

    def _scan(self) -> list[RecentEntry]:
        try:
            files = list(self._save_dir.iterdir())
        except OSError:
            log.exception("最近截图：扫描保存目录失败 %s", self._save_dir)
            return []
        by_id: dict[str, RecentEntry] = {}
        for path in files:
            if not path.is_file():
                continue
            entry = self._entry_from_path(path)
            if entry is None:
                continue
            previous = by_id.get(entry.id)
            if previous is None or entry.updated_at > previous.updated_at:
                if previous is not None:
                    log.warning(
                        "最近截图：文件 id=%s 重复，使用较新的 %s（忽略 %s）",
                        entry.id,
                        entry.path.name,
                        previous.path.name,
                    )
                by_id[entry.id] = entry
            else:
                log.warning(
                    "最近截图：文件 id=%s 重复，保留 %s（忽略 %s）",
                    entry.id,
                    previous.path.name,
                    entry.path.name,
                )
        return sorted(
            by_id.values(),
            key=lambda item: (item.updated_at, item.created_at, item.id),
            reverse=True,
        )

    def _unique_target(
        self,
        date: str,
        clock: str,
        millis: str,
        mode: str,
        width: int,
        height: int,
        *,
        favorite: bool = False,
        extension: str = ".png",
    ) -> tuple[str, Path]:
        index = 0
        while True:
            name = self._make_name(
                date,
                clock,
                millis,
                mode,
                width,
                height,
                index=index,
                favorite=favorite,
                extension=extension,
            )
            path = self._save_dir / name
            if not path.exists():
                entry_id = self._entry_id(
                    date, clock, millis, mode, index
                )
                return entry_id, path
            index += 1

    def _thumb_cache_path(self, entry_id: str) -> Path:
        safe = re.sub(r"[^0-9a-zA-Z_.-]", "_", entry_id)
        return self.thumbs_dir / f"{safe}.png"

    # --------------------------------------------------------------- mutate
    def add_png(
        self, png: bytes, *, mode: str, source: str = ""
    ) -> RecentEntry:
        payload, width, height = self._normalize_png(png)
        date, clock, millis = self._timestamp_parts(time.time())
        clean_mode = re.sub(r"[^a-z]", "", (mode or "region").lower())
        if not clean_mode:
            clean_mode = "region"
        _entry_id, target = self._unique_target(
            date, clock, millis, clean_mode, width, height
        )
        self._write_png(target, payload)
        entry = self._entry_from_path(target)
        if entry is None:
            raise RecentStoreError("无法读取新建的截图文件")
        log.debug(
            "最近截图：新增文件 id=%s，模式=%s，尺寸=%d×%d，%d 字节，文件=%s",
            entry.id,
            entry.mode,
            entry.width,
            entry.height,
            entry.byte_size,
            entry.path,
        )
        return entry

    def update_png(
        self, entry_id: str, png: bytes, *, annotation_count: int = 0
    ) -> RecentEntry | None:
        entry = self.get(entry_id)
        if entry is None:
            return None
        payload, width, height = self._normalize_png(png)
        new_name = re.sub(
            r"_\d+x\d+(?=_fav|\.)",
            f"_{width}x{height}",
            entry.name,
            count=1,
        )
        if not new_name.lower().endswith(".png"):
            # Managed screenshots are always rewritten as lossless PNG.
            new_name = Path(new_name).with_suffix(".png").name
        target = entry.path.with_name(new_name)
        old_path = entry.path
        if target != old_path and target.exists():
            log.warning(
                "最近截图：更新时目标文件已存在，保留原文件名 %s", target
            )
            target = old_path
        self._write_png(target, payload)
        if target != old_path:
            try:
                old_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                log.warning(
                    "最近截图：删除旧尺寸文件失败 %s", old_path, exc_info=True
                )
        try:
            self._thumb_cache_path(entry_id).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            log.debug("最近截图：删除缩略图缓存失败", exc_info=True)
        updated = self.get(entry_id)
        log.debug(
            "最近截图：更新文件 id=%s，尺寸=%d×%d，%d 字节",
            entry_id,
            width,
            height,
            len(payload),
        )
        return updated

    def set_favorite(
        self, entry_id: str, favorite: bool
    ) -> RecentEntry | None:
        entry = self.get(entry_id)
        if entry is None:
            return None
        stem = entry.path.stem
        if favorite and not stem.endswith(_FAV_SUFFIX):
            new_stem = stem + _FAV_SUFFIX
        elif not favorite and stem.endswith(_FAV_SUFFIX):
            new_stem = stem[: -len(_FAV_SUFFIX)]
        else:
            return entry
        target = entry.path.with_name(new_stem + entry.path.suffix)
        if target.exists():
            log.warning(
                "最近截图：收藏改名失败，目标已存在 id=%s path=%s",
                entry_id,
                target,
            )
            return None
        try:
            entry.path.rename(target)
        except OSError:
            log.exception("最近截图：收藏改名失败 id=%s", entry_id)
            return None
        log.debug(
            "最近截图：文件 id=%s 收藏状态=%s，文件=%s",
            entry_id,
            favorite,
            target.name,
        )
        return self.get(entry_id)

    def toggle_favorite(self, entry_id: str) -> RecentEntry | None:
        entry = self.get(entry_id)
        if entry is None:
            return None
        return self.set_favorite(entry.id, not entry.favorite)

    def delete(self, entry_id: str) -> bool:
        entry = self.get(entry_id)
        if entry is None:
            return False
        try:
            entry.path.unlink()
        except FileNotFoundError:
            return False
        except OSError:
            log.exception("最近截图：删除文件失败 %s", entry.path)
            return False
        try:
            self._thumb_cache_path(entry_id).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            log.debug("最近截图：删除缩略图缓存失败", exc_info=True)
        log.debug("最近截图：已删除文件 id=%s %s", entry_id, entry.path)
        return True

    def clear(self) -> int:
        entries = self._scan()
        removed = 0
        for entry in entries:
            if self.delete(entry.id):
                removed += 1
        log.debug("最近截图：清空 %d 个文件", removed)
        return removed

    def prune(self, *, max_entries: int, max_bytes: int) -> int:
        """No-op: managed files are the user's data and are never auto-deleted."""
        return 0

    # --------------------------------------------------------------- query
    def list(
        self,
        limit: int | None = 100,
        *,
        favorite: bool | None = None,
        mode: str | None = None,
    ) -> list[RecentEntry]:
        entries = self._scan()
        if favorite is not None:
            entries = [item for item in entries if item.favorite is favorite]
        if mode:
            normalized = mode.strip().lower()
            entries = [item for item in entries if item.mode == normalized]
        if limit is not None:
            entries = entries[: max(1, int(limit))]
        return entries

    def get(self, entry_id: str) -> RecentEntry | None:
        if not entry_id:
            return None
        for entry in self._scan():
            if entry.id == entry_id:
                return entry
        return None

    def image_path(self, entry: RecentEntry) -> Path | None:
        path = entry.path
        return path if path.exists() else None

    def thumb_path(self, entry: RecentEntry) -> Path | None:
        source = self.image_path(entry)
        if source is None:
            return None
        cache = self._thumb_cache_path(entry.id)
        try:
            if cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime:
                return cache
            with Image.open(source) as image:
                thumb = image.copy()
            thumb.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.LANCZOS)
            buffer = io.BytesIO()
            thumb.save(buffer, format="PNG")
            self._write_png(cache, buffer.getvalue())
            return cache
        except Exception:
            log.warning(
                "最近截图：生成缩略图失败 id=%s 文件=%s",
                entry.id,
                source,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------ migration
    def _migrate_legacy_db(self) -> None:
        database = self.data_dir / "recent.db"
        marker = self.data_dir / "recent.db.migrated"
        if not database.exists() or marker.exists():
            return
        import sqlite3

        migrated = 0
        skipped = 0
        log.info("最近截图：开始迁移旧数据库 %s", database)
        try:
            connection = sqlite3.connect(
                f"file:{database}?mode=ro", uri=True
            )
            connection.row_factory = sqlite3.Row
        except Exception:
            log.exception("最近截图：打开旧数据库失败，跳过迁移")
            return
        try:
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(shots)"
                ).fetchall()
            }
            if not columns:
                log.warning("最近截图：旧数据库没有 shots 表，跳过迁移")
                marker.write_text("no-shots-table\n", encoding="utf-8")
                return
            rows = connection.execute(
                "SELECT * FROM shots ORDER BY id"
            ).fetchall()
            for row in rows:
                data = {key: row[key] for key in row.keys()}
                relative = str(data.get("png_path") or "")
                source = self._safe_legacy_path(relative)
                saved_raw = str(data.get("saved_path") or "").strip()
                saved_path = (
                    Path(saved_raw).expanduser() if saved_raw else None
                )
                if source is None or not source.exists():
                    if saved_path is not None and saved_path.is_file():
                        log.info(
                            "最近截图迁移：旧缓存缺失，改用已保存文件 %s",
                            saved_path,
                        )
                        source = saved_path
                    else:
                        skipped += 1
                        log.warning(
                            "最近截图迁移：图片不存在，跳过 id=%s path=%s",
                            data.get("id"),
                            relative,
                        )
                        continue
                try:
                    payload = source.read_bytes()
                    payload, width, height = self._normalize_png(payload)
                except Exception:
                    skipped += 1
                    log.warning(
                        "最近截图迁移：图片无效，跳过 id=%s path=%s",
                        data.get("id"),
                        source,
                        exc_info=True,
                    )
                    continue
                stamp = self._legacy_timestamp(data, source)
                date, clock, millis = self._timestamp_parts(stamp)
                mode = re.sub(
                    r"[^a-z]", "", str(data.get("mode") or "region").lower()
                ) or "region"
                favorite = bool(data.get("favorite") or 0)
                _entry_id, target = self._unique_target(
                    date,
                    clock,
                    millis,
                    mode,
                    width,
                    height,
                    favorite=favorite,
                )
                try:
                    self._write_png(target, payload)
                    updated_stamp = float(
                        data.get("updated_at")
                        or data.get("created_at")
                        or stamp
                    )
                    os.utime(target, (updated_stamp, updated_stamp))
                except Exception:
                    skipped += 1
                    log.warning(
                        "最近截图迁移：写入文件失败 %s", target, exc_info=True
                    )
                    continue
                migrated += 1
                log.info(
                    "最近截图迁移：id=%s -> %s（收藏=%s）",
                    data.get("id"),
                    target.name,
                    favorite,
                )
                if saved_path is not None:
                    self._consume_legacy_export(saved_path, target)
        except Exception:
            log.exception("最近截图：迁移旧数据库失败")
            return
        finally:
            try:
                connection.close()
            except Exception:
                pass
        try:
            marker.write_text(
                f"migrated={migrated} skipped={skipped}\n",
                encoding="utf-8",
            )
        except OSError:
            log.warning("最近截图：写入迁移标记失败 %s", marker, exc_info=True)
        log.info(
            "最近截图：旧数据库迁移完成，导入 %d 条，跳过 %d 条",
            migrated,
            skipped,
        )

    def _consume_legacy_export(
        self, saved_path: Path, managed_target: Path
    ) -> None:
        """Remove the old auto-export file that duplicated a migrated entry.

        Only files inside the current save directory whose names match the old
        automatic ``screenshot_<timestamp>`` pattern are touched. User-renamed
        files and exports from other directories are kept.
        """
        try:
            resolved = saved_path.resolve()
            resolved.relative_to(self._save_dir.resolve())
        except (OSError, ValueError):
            return
        if resolved == managed_target.resolve():
            return
        if not resolved.is_file():
            return
        if not re.match(
            r"^screenshot_\d{8}_\d{6}(?:_\d+)?\.(?:png|jpg|jpeg|webp)$",
            resolved.name,
            re.IGNORECASE,
        ):
            return
        try:
            resolved.unlink()
            log.info("最近截图迁移：已合并旧导出文件 %s", resolved)
        except FileNotFoundError:
            pass
        except OSError:
            log.warning(
                "最近截图迁移：删除旧导出文件失败 %s", resolved, exc_info=True
            )

    def _safe_legacy_path(self, relative: str) -> Path | None:
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
    def _legacy_timestamp(data: dict, source: Path) -> float:
        try:
            return float(data.get("created_at") or source.stat().st_mtime)
        except (TypeError, ValueError, OSError):
            return time.time()
