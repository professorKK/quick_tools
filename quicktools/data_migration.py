"""Move plugin data between configurable roots.

This module never imports Tk. It is safe to call from a worker thread after
the launcher has stopped every plugin service and window.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Copying thousands of clipboard images can produce a progress event per file.
# Ten updates per second keeps the UI responsive without flooding the queue.
PROGRESS_INTERVAL_SECONDS = 0.1


class PluginDataError(Exception):
    """Base error for plugin data migration."""


class PluginDataConflictError(PluginDataError):
    def __init__(self, dest_root: Path, conflicts: list[str]) -> None:
        self.dest_root = dest_root
        self.conflicts = tuple(conflicts)
        names = "、".join(conflicts)
        super().__init__(
            f"目标目录中已存在以下插件数据：{names}。请选择其他目录，"
            "或确认合并后重试。"
        )


class PluginDataCancelled(PluginDataError):
    """Raised when the user cancels a running migration.

    ``migrate_plugin_data()`` rolls back before raising this, so callers can
    simply restart the plugins with the old root.
    """


@dataclass(frozen=True)
class MigrationProgress:
    plugin_id: str
    files_done: int
    files_total: int
    bytes_done: int
    bytes_total: int


ProgressCallback = Callable[[MigrationProgress], None]
CancelCallback = Callable[[], bool]


@dataclass
class MigrationResult:
    source_root: Path
    dest_root: Path
    methods: dict[str, str] = field(default_factory=dict)
    migrated: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    _renamed: list[tuple[str, Path, Path]] = field(default_factory=list)
    _copied: list[tuple[str, Path]] = field(default_factory=list)
    _created_files: list[Path] = field(default_factory=list)
    _temp_dirs: list[Path] = field(default_factory=list)
    _finalized: bool = False

    def rollback(self) -> None:
        """Undo a failed migration. Idempotent."""
        for _name, source, target in reversed(self._renamed):
            try:
                if not source.exists() and target.exists():
                    os.replace(target, source)
            except OSError:
                log.exception("回滚插件数据目录失败：%s -> %s", target, source)
        for _name, target in reversed(self._copied):
            shutil.rmtree(target, ignore_errors=True)
        for path in reversed(self._created_files):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                log.warning("回滚合并文件失败：%s", path, exc_info=True)
        for temp in self._temp_dirs:
            shutil.rmtree(temp, ignore_errors=True)
        self._renamed.clear()
        self._copied.clear()
        self._created_files.clear()
        self._temp_dirs.clear()
        self.methods.clear()
        self.migrated.clear()
        self.merged.clear()

    def finalize(self) -> None:
        """Remove deferred source copies after the new setting is saved."""
        if self._finalized:
            return
        self._finalized = True
        for name in [*self.migrated, *self.merged]:
            source = self.source_root / name
            if not source.exists():
                continue
            try:
                shutil.rmtree(source)
            except OSError:
                log.warning(
                    "删除迁移后的旧插件数据失败（保留副本）：%s",
                    source,
                    exc_info=True,
                )
        # Clean up the now-empty old root, but never touch a directory that
        # still holds files we did not migrate.
        try:
            if self.source_root.exists() and not any(
                self.source_root.iterdir()
            ):
                self.source_root.rmdir()
        except OSError:
            log.debug(
                "删除空的旧插件数据根目录失败：%s",
                self.source_root,
                exc_info=True,
            )


def normalize_plugin_data_root(
    raw: str | Path | None, *, default_root: Path
) -> tuple[str, Path]:
    """Return (stored value, resolved path). Blank means the default root."""
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return "", default_root.resolve()
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError("插件数据目录必须是绝对路径")
    resolved = path.resolve()
    if resolved == default_root.resolve():
        return "", resolved
    return str(resolved), resolved


def find_plugin_data_conflicts(
    source_root: Path, dest_root: Path
) -> list[str]:
    source_root = Path(source_root)
    dest_root = Path(dest_root)
    if not source_root.exists() or not dest_root.exists():
        return []
    conflicts: list[str] = []
    for entry in os.scandir(source_root):
        if not entry.is_dir(follow_symlinks=False):
            continue
        target = dest_root / entry.name
        if not target.exists():
            continue
        try:
            if not target.is_dir() or any(target.iterdir()):
                conflicts.append(entry.name)
        except OSError:
            conflicts.append(entry.name)
    return sorted(conflicts)


def _tree_size(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                stat = os.stat(os.path.join(root, name), follow_symlinks=False)
            except OSError:
                continue
            files += 1
            size += stat.st_size
    return files, size


def _same_device(source: Path, dest: Path) -> bool:
    try:
        source_dev = source.stat().st_dev
    except OSError:
        return True
    current = dest
    while not current.exists() and current.parent != current:
        current = current.parent
    try:
        return current.stat().st_dev == source_dev
    except OSError:
        return True


def _copy_tree(
    source: Path,
    target: Path,
    *,
    merge: bool,
    plugin_id: str,
    counts: list[int],
    progress: ProgressCallback | None,
    created_files: list[Path],
    should_cancel: CancelCallback | None = None,
) -> None:
    files_done, bytes_done, files_total, bytes_total = counts
    last_emit = 0.0

    def check_cancel() -> None:
        if should_cancel is not None and should_cancel():
            raise PluginDataCancelled("已取消插件数据迁移")

    def emit(force: bool = False) -> None:
        nonlocal last_emit
        if progress is None:
            return
        now = time.monotonic()
        if not force and now - last_emit < PROGRESS_INTERVAL_SECONDS:
            return
        last_emit = now
        progress(
            MigrationProgress(
                plugin_id,
                files_done,
                files_total,
                bytes_done,
                bytes_total,
            )
        )

    def advance(size: int) -> None:
        nonlocal files_done, bytes_done
        files_done += 1
        bytes_done += max(0, size)
        counts[0] = files_done
        counts[1] = bytes_done
        emit()

    emit(force=True)
    for root, dirs, names in os.walk(source):
        relative = Path(root).relative_to(source)
        target_dir = target / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        # Keep deterministic traversal; symlinked dirs are not followed.
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in names:
            check_cancel()
            src = Path(root) / name
            dst = target_dir / name
            try:
                file_size = src.stat(follow_symlinks=False).st_size
            except OSError:
                file_size = 0
            if src.is_symlink():
                if not dst.exists():
                    try:
                        os.symlink(os.readlink(src), dst)
                        created_files.append(dst)
                    except OSError:
                        log.warning("复制符号链接失败：%s", src, exc_info=True)
                advance(file_size)
                continue
            if merge and dst.exists():
                # The target copy wins; still count it so progress reaches 100%.
                advance(file_size)
                continue
            try:
                shutil.copy2(src, dst)
            except OSError as exc:
                raise PluginDataError(
                    f"复制插件数据失败：{src} -> {dst}：{exc}"
                ) from exc
            created_files.append(dst)
            advance(file_size)
    emit(force=True)


def migrate_plugin_data(
    source_root: Path,
    dest_root: Path,
    *,
    merge: bool = False,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> MigrationResult:
    source_root = Path(source_root).resolve()
    dest_root = Path(dest_root).resolve()
    result = MigrationResult(source_root=source_root, dest_root=dest_root)
    if source_root == dest_root:
        return result
    try:
        source_root.relative_to(dest_root)
        raise PluginDataError("插件数据目录不能迁移到自身子目录")
    except ValueError:
        pass
    try:
        dest_root.relative_to(source_root)
        raise PluginDataError("目标目录不能位于旧插件数据目录内部")
    except ValueError:
        pass
    dest_root.mkdir(parents=True, exist_ok=True)
    if not source_root.exists():
        return result

    plugin_dirs = [
        entry
        for entry in os.scandir(source_root)
        if entry.is_dir(follow_symlinks=False)
    ]
    conflicts = find_plugin_data_conflicts(source_root, dest_root)
    if conflicts and not merge:
        raise PluginDataConflictError(dest_root, conflicts)
    # A same-named regular file can never be merged into a directory. Reject
    # it before renaming any plugin so a failed run cannot strand data.
    for entry in plugin_dirs:
        target = dest_root / entry.name
        if target.exists() and not target.is_dir():
            raise PluginDataError(
                f"目标路径已存在同名文件，无法合并：{target}"
            )
    same_device = _same_device(source_root, dest_root)
    for entry in sorted(plugin_dirs, key=lambda item: item.name):
        if should_cancel is not None and should_cancel():
            raise PluginDataCancelled("已取消插件数据迁移")
        source = Path(entry.path)
        target = dest_root / entry.name
        if target.exists() and any(target.iterdir()):
            if not merge:
                raise PluginDataConflictError(dest_root, [entry.name])
            mode = "merge"
        elif target.exists():
            try:
                target.rmdir()
            except OSError:
                pass
            mode = "rename" if same_device else "copy"
        else:
            mode = "rename" if same_device else "copy"

        files_total, bytes_total = (
            (0, 0) if mode == "rename" else _tree_size(source)
        )
        counts = [0, 0, files_total, bytes_total]
        if progress is not None:
            progress(MigrationProgress(entry.name, 0, files_total, 0, bytes_total))
        try:
            if mode == "rename":
                os.replace(source, target)
                result._renamed.append((entry.name, source, target))
                result.migrated.append(entry.name)
                if progress is not None:
                    progress(
                        MigrationProgress(
                            entry.name, files_total, files_total,
                            bytes_total, bytes_total,
                        )
                    )
            elif mode == "copy":
                temp = dest_root / f".{entry.name}.qt-migrate.tmp"
                shutil.rmtree(temp, ignore_errors=True)
                temp.mkdir(parents=True)
                result._temp_dirs.append(temp)
                _copy_tree(
                    source,
                    temp,
                    merge=False,
                    plugin_id=entry.name,
                    counts=counts,
                    progress=progress,
                    created_files=result._created_files,
                    should_cancel=should_cancel,
                )
                if target.exists():
                    target.rmdir()
                os.replace(temp, target)
                result._temp_dirs.remove(temp)
                result._copied.append((entry.name, target))
                result.migrated.append(entry.name)
            else:
                _copy_tree(
                    source,
                    target,
                    merge=True,
                    plugin_id=entry.name,
                    counts=counts,
                    progress=progress,
                    created_files=result._created_files,
                    should_cancel=should_cancel,
                )
                result.merged.append(entry.name)
            result.methods[entry.name] = mode
        except Exception as exc:
            log.exception("迁移插件数据失败：%s", entry.name)
            try:
                result.rollback()
            except Exception:
                log.exception("回滚插件数据迁移失败")
            if isinstance(exc, PluginDataError):
                raise
            raise PluginDataError(
                f"迁移插件数据失败（{entry.name}）：{exc}"
            ) from exc
    return result
