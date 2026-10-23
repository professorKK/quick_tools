from __future__ import annotations

from pathlib import Path

import pytest

from quicktools import data_migration
from quicktools.data_migration import (
    PluginDataCancelled,
    PluginDataConflictError,
    PluginDataError,
    find_plugin_data_conflicts,
    migrate_plugin_data,
    normalize_plugin_data_root,
)


def seed(root: Path) -> None:
    (root / "clipboard" / "images").mkdir(parents=True)
    (root / "clipboard" / "images" / "a.png").write_bytes(b"a")
    (root / "clipboard" / "history.db").write_bytes(b"db")
    (root / "calculator").mkdir()
    (root / "calculator" / "settings.json").write_text("{}", encoding="utf-8")


def test_same_filesystem_rename(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)

    result = migrate_plugin_data(source, dest)

    assert result.methods == {"clipboard": "rename", "calculator": "rename"}
    assert not (source / "clipboard").exists()
    assert (dest / "clipboard" / "history.db").read_bytes() == b"db"
    assert (dest / "calculator" / "settings.json").exists()
    assert result.migrated == ["calculator", "clipboard"]


def test_missing_source_is_noop(tmp_path: Path) -> None:
    result = migrate_plugin_data(tmp_path / "missing", tmp_path / "new")

    assert result.migrated == []
    assert (tmp_path / "new").is_dir()


def test_conflict_aborts_before_moving(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    (dest / "clipboard").mkdir(parents=True)
    (dest / "clipboard" / "keep.txt").write_text("keep", encoding="utf-8")

    assert find_plugin_data_conflicts(source, dest) == ["clipboard"]
    with pytest.raises(PluginDataConflictError):
        migrate_plugin_data(source, dest)
    assert (source / "calculator" / "settings.json").exists()
    assert (source / "clipboard" / "history.db").exists()


def test_merge_keeps_target_and_copies_missing(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    (dest / "clipboard").mkdir(parents=True)
    (dest / "clipboard" / "history.db").write_bytes(b"target")

    result = migrate_plugin_data(source, dest, merge=True)

    assert result.methods["clipboard"] == "merge"
    assert (dest / "clipboard" / "history.db").read_bytes() == b"target"
    assert (dest / "clipboard" / "images" / "a.png").read_bytes() == b"a"
    assert (source / "clipboard" / "history.db").exists()
    result.finalize()
    assert not (source / "clipboard").exists()
    assert not (source / "calculator").exists()
    assert not source.exists()


def test_merge_rollback_removes_created_files(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    (dest / "clipboard").mkdir(parents=True)
    (dest / "clipboard" / "history.db").write_bytes(b"target")

    result = migrate_plugin_data(source, dest, merge=True)
    copied = dest / "clipboard" / "images" / "a.png"
    assert copied.exists()

    result.rollback()

    assert not copied.exists()
    assert (dest / "clipboard" / "history.db").read_bytes() == b"target"
    assert (source / "clipboard" / "images" / "a.png").exists()


def test_cross_device_copy_and_finalize(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    monkeypatch.setattr(
        data_migration, "_same_device", lambda _a, _b: False
    )
    progress = []

    result = migrate_plugin_data(source, dest, progress=progress.append)

    assert result.methods["clipboard"] == "copy"
    assert (dest / "clipboard" / "history.db").read_bytes() == b"db"
    assert (source / "clipboard" / "history.db").exists()
    assert progress and progress[-1].files_done == progress[-1].files_total
    assert not list(dest.glob("*.qt-migrate.tmp"))
    result.finalize()
    assert not (source / "clipboard").exists()


def test_cancelled_copy_rolls_back_before_raising(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    monkeypatch.setattr(
        data_migration, "_same_device", lambda _a, _b: False
    )
    calls = 0

    def should_cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(PluginDataCancelled):
        migrate_plugin_data(source, dest, should_cancel=should_cancel)

    assert (source / "calculator" / "settings.json").exists()
    assert (source / "clipboard" / "history.db").exists()
    assert not (dest / "calculator").exists()
    assert not (dest / "clipboard").exists()


def test_rename_rollback_restores_source(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)

    result = migrate_plugin_data(source, dest)
    result.rollback()

    assert (source / "clipboard" / "history.db").exists()
    assert not (dest / "clipboard").exists()


def test_merge_progress_counts_skipped_files(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    (dest / "clipboard").mkdir(parents=True)
    (dest / "clipboard" / "history.db").write_bytes(b"target")
    progress = []

    migrate_plugin_data(source, dest, merge=True, progress=progress.append)

    last = progress[-1]
    assert last.files_done == last.files_total
    assert last.bytes_done == last.bytes_total


def test_merge_rejects_same_named_file_before_moving(tmp_path: Path) -> None:
    source = tmp_path / "old"
    dest = tmp_path / "new"
    seed(source)
    dest.mkdir()
    (dest / "clipboard").write_text("not a directory", encoding="utf-8")

    with pytest.raises(PluginDataError):
        migrate_plugin_data(source, dest, merge=True)

    # Preflight runs before any rename, so both plugins stay intact.
    assert (source / "calculator" / "settings.json").exists()
    assert (source / "clipboard" / "history.db").exists()
    assert not (dest / "calculator").exists()


def _app_with_settings(monkeypatch, tmp_path: Path):
    import quicktools.app as app_module
    from quicktools.app import QuickToolsApp
    from quicktools.config import AppSettings, HotkeySpec

    default_root = tmp_path / "default-root"
    monkeypatch.setattr(
        app_module.paths,
        "default_plugin_data_root",
        lambda: default_root,
    )
    app = object.__new__(QuickToolsApp)
    app.settings = AppSettings(HotkeySpec.default(), "")
    return app_module, app


def test_app_migration_saves_settings_after_moving_data(
    tmp_path: Path, monkeypatch
) -> None:
    app_module, app = _app_with_settings(monkeypatch, tmp_path)
    old_root = tmp_path / "default-root"
    new_root = tmp_path / "new-root"
    seed(old_root)
    saved = []
    monkeypatch.setattr(app_module, "save_settings", saved.append)

    result, settings = app.migrate_plugin_data_root(
        app.settings, str(new_root)
    )

    assert (new_root / "clipboard" / "history.db").exists()
    assert not old_root.exists()
    assert result.migrated == ["calculator", "clipboard"]
    assert settings.plugin_data_root == str(new_root.resolve())
    assert saved[-1].plugin_data_root == str(new_root.resolve())


def test_app_migration_rolls_back_when_settings_save_fails(
    tmp_path: Path, monkeypatch
) -> None:
    app_module, app = _app_with_settings(monkeypatch, tmp_path)
    old_root = tmp_path / "default-root"
    new_root = tmp_path / "new-root"
    seed(old_root)

    def fail_save(_settings) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(app_module, "save_settings", fail_save)

    with pytest.raises(PluginDataError):
        app.migrate_plugin_data_root(app.settings, str(new_root))

    assert (old_root / "clipboard" / "history.db").exists()
    assert (old_root / "calculator" / "settings.json").exists()
    assert not (new_root / "clipboard").exists()


def test_nested_roots_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "old"
    source.mkdir()
    with pytest.raises(PluginDataError):
        migrate_plugin_data(source, source / "inner")
    with pytest.raises(PluginDataError):
        migrate_plugin_data(source, tmp_path)


def test_normalize_root(tmp_path: Path) -> None:
    default = tmp_path / "default"
    assert normalize_plugin_data_root("", default_root=default) == (
        "",
        default.resolve(),
    )
    stored, resolved = normalize_plugin_data_root(
        str(tmp_path / "custom"), default_root=default
    )
    assert stored == str((tmp_path / "custom").resolve())
    assert resolved == (tmp_path / "custom").resolve()
    with pytest.raises(ValueError):
        normalize_plugin_data_root("relative/path", default_root=default)
