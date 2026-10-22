from __future__ import annotations

from pathlib import Path

from quicktools import paths


def test_plugin_data_dir_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "data")
    assert paths.plugin_data_dir("clipboard") == (
        tmp_path / "data" / "plugin_data" / "clipboard"
    )
    assert paths.default_plugin_data_root() == (
        tmp_path / "data" / "plugin_data"
    )


def test_plugin_data_dir_custom_root(tmp_path: Path) -> None:
    root = tmp_path / "custom"
    assert paths.plugin_data_root(None) == paths.default_plugin_data_root()
    assert paths.plugin_data_root("") == paths.default_plugin_data_root()
    assert paths.plugin_data_root(str(root)) == root
    assert paths.plugin_data_dir("calculator", root) == root / "calculator"


def test_plugin_data_root_expands_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert paths.plugin_data_root("~/plugin-data") == tmp_path / "plugin-data"
