from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path

import pytest

from quicktools.plugin_api import PluginBase, PluginContext, PluginMeta
from quicktools.plugin_loader import PluginLoader
from quicktools.plugin_settings import open_plugin_settings
from quicktools.plugins.clipboard.models import BackendStatus
from quicktools.plugins.clipboard.settings import ClipboardSettings
from quicktools.settings_widgets import Card
from quicktools.ui_theme import pick_fonts

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


@pytest.fixture()
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


class DemoPlugin(PluginBase):
    def __init__(self, context: PluginContext) -> None:
        super().__init__(context)
        self.window: tk.Toplevel | None = None

    def create_ui(self, window: tk.Toplevel) -> None:
        self.window = window

    def create_settings_ui(self, parent: tk.Misc) -> None:
        tk.Label(
            parent, text="演示设置项", bg="#ffffff", font=("TkDefaultFont", 10)
        ).pack(anchor="w")


class PlainPlugin(PluginBase):
    def create_ui(self, window: tk.Toplevel) -> None:
        pass


class CardsPlugin(PluginBase):
    settings_cards = True

    def create_ui(self, window: tk.Toplevel) -> None:
        pass

    def create_settings_ui(self, parent: tk.Misc) -> None:
        card = Card(parent)
        card.pack(fill="x")
        tk.Label(card.body, text="卡片设置项", bg="#ffffff").pack(anchor="w")


def _descendants(widget: tk.Misc, cls: type):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_descendants(child, cls))
    return found


def make_plugin(
    root: tk.Tk, tmp_path: Path, plugin_class=DemoPlugin
) -> tuple[PluginBase, tk.Toplevel]:
    folder = tmp_path / "demo"
    folder.mkdir()
    meta = PluginMeta(
        id="demo",
        name="演示插件",
        description="这是演示插件的详细说明。",
        version="1.2.3",
        entry="plugin.py",
        class_name="DemoPlugin",
        folder=folder,
        icon="D",
        summary="一句简短的演示概述",
        author="测试作者",
    )
    context = PluginContext(
        root=root,
        plugin_id="demo",
        plugin_dir=folder,
        data_dir=tmp_path / "data",
        meta=meta,
    )
    plugin = plugin_class(context)
    window = tk.Toplevel(root)
    window.withdraw()
    plugin.create_ui(window)
    return plugin, window


def test_open_plugin_settings_shows_settings_and_about(
    root: tk.Tk, tmp_path: Path
) -> None:
    plugin, window = make_plugin(root, tmp_path)
    try:
        assert open_plugin_settings(plugin, window) is True
        dialog = plugin._settings_dialog
        assert dialog is not None
        assert dialog.winfo_exists()
        assert dialog.current_page == "settings"
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    texts.append(child.cget("text"))
                walk(child)

        walk(dialog)
        assert "演示设置项" in texts

        dialog.show_page("about")
        texts.clear()
        walk(dialog)
        assert "演示插件" in texts
        assert "一句简短的演示概述" in texts
        assert "这是演示插件的详细说明。" in texts
        assert "测试作者" in texts

        dialog.close()
        root.update()
        assert plugin._settings_dialog is None
    finally:
        window.destroy()


def test_open_plugin_settings_reuses_existing_dialog(
    root: tk.Tk, tmp_path: Path
) -> None:
    plugin, window = make_plugin(root, tmp_path)
    try:
        open_plugin_settings(plugin, window)
        dialog = plugin._settings_dialog
        open_plugin_settings(plugin, window, page="about")
        assert plugin._settings_dialog is dialog
        assert dialog.current_page == "about"
        dialog.close()
    finally:
        window.destroy()


class _ClipboardService:
    def __init__(self, data_dir: Path) -> None:
        self.settings = ClipboardSettings()
        self.backend_status = BackendStatus(True, "测试剪贴板")
        self.data_dir = data_dir

    def update_settings(self, **_kwargs) -> None:
        pass

    def clear_history(self) -> int:
        return 0


class _ClipboardView:
    def __init__(self, service: _ClipboardService, fonts) -> None:
        self.service = service
        self.fonts = fonts
        self._startup_error = ""
        self._selected_id = None

    def _flash(self, _message: str) -> None:
        pass

    def refresh(self) -> None:
        pass


def test_clipboard_settings_still_import_after_rescan(
    root: tk.Tk, tmp_path: Path
) -> None:
    """Reproduce the clipboard settings failure seen in the packaged app.

    The launcher rescans while the background clipboard instance stays alive;
    the settings page imports ``.settings_view`` lazily at that point.
    """
    user = tmp_path / "user"
    user.mkdir()
    builtin = Path(__file__).resolve().parents[1] / "quicktools" / "plugins"
    loader = PluginLoader(user_plugins=user, builtin_plugins=builtin)
    metas = loader.scan()
    meta = next(item for item in metas if item.id == "clipboard")
    plugin_class = loader.load_class(meta)
    context = PluginContext(
        root=root,
        plugin_id=meta.id,
        plugin_dir=meta.folder,
        data_dir=tmp_path / "data",
        meta=meta,
    )
    plugin = plugin_class(context)
    plugin._view = _ClipboardView(
        _ClipboardService(tmp_path / "data"), pick_fonts(root)
    )

    loader.scan()
    host = tk.Frame(root, bg="#ffffff")
    host.pack(fill="both", expand=True)
    try:
        plugin.create_settings_ui(host)
        root.update_idletasks()
        labels = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    labels.append(child.cget("text"))
                walk(child)

        walk(host)
        assert "记录与容量" in labels
        assert "启用自动记录" in labels
    finally:
        host.destroy()


def test_plain_builder_is_wrapped_in_one_card(
    root: tk.Tk, tmp_path: Path
) -> None:
    plugin, window = make_plugin(root, tmp_path)
    try:
        open_plugin_settings(plugin, window)
        dialog = plugin._settings_dialog
        cards = _descendants(dialog.settings_body, Card)
        assert len(cards) == 1
        assert dialog.current_page == "settings"
        assert dialog._page_title.get() == "设置"
        dialog.show_page("about")
        assert dialog._page_title.get() == "关于"
        assert dialog._nav["about"]._active is True
        assert dialog._nav["settings"]._active is False
        dialog.close()
    finally:
        window.destroy()


def test_plugin_that_builds_cards_is_not_wrapped_again(
    root: tk.Tk, tmp_path: Path
) -> None:
    plugin, window = make_plugin(root, tmp_path, CardsPlugin)
    try:
        open_plugin_settings(plugin, window)
        dialog = plugin._settings_dialog
        cards = _descendants(dialog.settings_body, Card)
        assert len(cards) == 1
        texts = []
        walk_open = [dialog.settings_body]
        while walk_open:
            widget = walk_open.pop()
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    texts.append(child.cget("text"))
                walk_open.append(child)
        assert "卡片设置项" in texts
        dialog.close()
    finally:
        window.destroy()


def test_plugin_without_settings_gets_empty_state_and_about(
    root: tk.Tk, tmp_path: Path
) -> None:
    plugin, window = make_plugin(root, tmp_path, PlainPlugin)
    try:
        open_plugin_settings(plugin, window)
        dialog = plugin._settings_dialog
        assert dialog is not None
        texts = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    texts.append(child.cget("text"))
                walk(child)

        walk(dialog)
        assert "这个插件没有可配置的选项" in texts
        dialog.show_page("about")
        texts.clear()
        walk(dialog)
        assert "演示插件" in texts
        dialog.close()
    finally:
        window.destroy()
