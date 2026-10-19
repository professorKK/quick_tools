from __future__ import annotations

import json
from pathlib import Path

import pytest

from quicktools.plugin_api import PluginBase, PluginError
from quicktools.plugin_loader import PluginLoader


def write_plugin(
    root: Path,
    folder: str,
    *,
    plugin_id: str | None = None,
    api_version: int = 1,
    entry: str = "plugin.py",
    class_name: str = "TestPlugin",
    source: str | None = None,
    background: bool = False,
) -> Path:
    plugin_dir = root / folder
    plugin_dir.mkdir(parents=True)
    manifest = {
        "api_version": api_version,
        "id": plugin_id or folder,
        "name": f"Plugin {folder}",
        "description": "test",
        "version": "1.0.0",
        "entry": entry,
        "class": class_name,
        "icon": "T",
        "order": 10,
        "background": background,
    }
    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (plugin_dir / entry).write_text(
        source
        or (
            "from quicktools.plugin_api import PluginBase\n"
            "class TestPlugin(PluginBase):\n"
            "    def create_ui(self, window):\n"
            "        pass\n"
        ),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture()
def loader(tmp_path: Path) -> PluginLoader:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    return PluginLoader(user_plugins=user, builtin_plugins=builtin)


def test_scan_and_load_user_plugin(loader: PluginLoader) -> None:
    write_plugin(loader.user_plugins, "hello")
    metas = loader.scan()
    assert [m.id for m in metas] == ["hello"]
    assert metas[0].builtin is False
    cls = loader.load_class(metas[0])
    assert issubclass(cls, PluginBase)


def test_background_flag_is_parsed(loader: PluginLoader) -> None:
    write_plugin(loader.user_plugins, "service", background=True)
    write_plugin(loader.user_plugins, "normal")
    metas = {meta.id: meta for meta in loader.scan()}
    assert metas["service"].background is True
    assert metas["normal"].background is False


def test_lazy_import_does_not_run_broken_code_until_open(loader: PluginLoader) -> None:
    write_plugin(loader.user_plugins, "broken", source="this is not python !!!\n")
    metas = loader.scan()
    assert len(metas) == 1
    with pytest.raises(PluginError):
        loader.load_class(metas[0])


def test_relative_import_inside_plugin(loader: PluginLoader) -> None:
    plugin_dir = write_plugin(
        loader.user_plugins,
        "relative",
        source=(
            "from quicktools.plugin_api import PluginBase\n"
            "from .helper import VALUE\n"
            "class TestPlugin(PluginBase):\n"
            "    def create_ui(self, window):\n"
            "        self.value = VALUE\n"
        ),
    )
    (plugin_dir / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    metas = loader.scan()
    cls = loader.load_class(metas[0])
    context = type(
        "Context",
        (),
        {
            "root": None,
            "plugin_id": "relative",
            "plugin_dir": plugin_dir,
            "data_dir": plugin_dir,
        },
    )()
    plugin = cls(context)
    plugin.create_ui(None)
    assert plugin.value == 42


def test_path_traversal_is_rejected(loader: PluginLoader) -> None:
    write_plugin(loader.user_plugins, "escape", entry="../outside.py")
    metas = loader.scan()
    assert metas == []
    assert loader.errors


def test_manifest_api_version_and_missing_fields(loader: PluginLoader) -> None:
    write_plugin(loader.user_plugins, "oldapi", api_version=99)
    plugin_dir = loader.user_plugins / "nofield"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "api_version": 1,
                "id": "nofield",
                "name": "No field",
                "version": "1",
                "entry": "plugin.py",
            }
        ),
        encoding="utf-8",
    )
    metas = loader.scan()
    assert metas == []
    assert len(loader.errors) == 2


def test_duplicate_id_builtin_wins(loader: PluginLoader) -> None:
    write_plugin(loader.builtin_plugins, "one", plugin_id="same")
    write_plugin(loader.user_plugins, "two", plugin_id="same")
    metas = loader.scan()
    assert len(metas) == 1
    assert metas[0].builtin is True
    assert loader.errors


def test_wrong_base_class_is_reported(loader: PluginLoader) -> None:
    write_plugin(
        loader.user_plugins,
        "wrongbase",
        source="class TestPlugin:\n    pass\n",
    )
    meta = loader.scan()[0]
    with pytest.raises(PluginError):
        loader.load_class(meta)


def test_scan_without_manifest_skips_folder(loader: PluginLoader) -> None:
    (loader.user_plugins / "notaplugin").mkdir()
    assert loader.scan() == []
