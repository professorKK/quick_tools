from __future__ import annotations

import io
import os
import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from quicktools.plugins.screenshot.recent.store import RecentStore
from quicktools.plugins.screenshot.settings import ScreenshotSettings
from quicktools.plugins.screenshot.ui.control_window import ControlWindow

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


class FakeService:
    def __init__(self, store: RecentStore) -> None:
        self.recent = store
        self.entries = store.list(500)
        self.last_status = ""

    def recent_entries(
        self,
        limit: int = 8,
        *,
        favorite: bool | None = None,
        mode: str | None = None,
    ):
        entries = self.entries
        if favorite is not None:
            entries = [item for item in entries if item.favorite is favorite]
        if mode:
            entries = [item for item in entries if item.mode == mode]
        return entries[:limit]

    def open_recent(self, _entry) -> None:
        pass

    def copy_recent(self, _entry) -> None:
        self.last_status = "截图已复制到剪贴板"

    def delete_recent(self, entry) -> None:
        self.entries = [item for item in self.entries if item.id != entry.id]

    def clear_recent(self) -> None:
        self.entries = []

    def set_recent_favorite(self, entry, favorite: bool):
        updated = replace(entry, favorite=favorite)
        self.entries = [
            updated if item.id == entry.id else item for item in self.entries
        ]
        self.last_status = "已收藏截图" if favorite else "已取消收藏"
        return updated

    def toggle_recent_favorite(self, entry):
        current = next(
            (item for item in self.entries if item.id == entry.id), entry
        )
        return self.set_recent_favorite(current, not current.favorite)


class FakePlugin:
    def __init__(self, service: FakeService) -> None:
        self.service = service
        self.settings = ScreenshotSettings()
        self.actions: list[str] = []

    def status_text(self) -> str:
        return "截图快捷键：Ctrl+Alt+X"

    def platform_hint(self) -> str:
        return ""

    def handle_action(self, action: str) -> None:
        self.actions.append(action)

    def open_save_folder(self) -> None:
        pass


def _find_label(widget: tk.Misc, text: str) -> tk.Misc | None:
    for child in widget.winfo_children():
        if isinstance(child, tk.Label) and child.cget("text") == text:
            return child
        found = _find_label(child, text)
        if found is not None:
            return found
    return None


def _rows(control: ControlWindow):
    return control.recent_view._scroll.inner.winfo_children()


def test_home_page_mode_cards_are_compact_with_hover_text(
    tmp_path: Path,
) -> None:
    store = RecentStore(tmp_path)
    try:
        service = FakeService(store)
        plugin = FakePlugin(service)
        root = tk.Tk()
        root.withdraw()
        window = tk.Toplevel(root)
        try:
            control = ControlWindow(window, plugin)
            control.pack(fill="both", expand=True)
            root.update()

            cards = control.home_page._mode_cards
            assert [action for action, _card in cards] == [
                "capture_region",
                "capture_window",
                "capture_freeform",
                "capture_scroll",
            ]
            # One compact row, four equal columns.
            assert [int(card.grid_info()["row"]) for _, card in cards] == [
                0, 0, 0, 0
            ]
            assert [int(card.grid_info()["column"]) for _, card in cards] == [
                0, 1, 2, 3
            ]
            for _action, card in cards:
                assert card.description
                assert card._tooltip.text == card.description
                # The explanation only lives in the hover tooltip.
                assert _find_label(card, card.description) is None
                assert card._title.cget("text")
                # The hover tip covers every child of the card.
                assert card._title.bind("<Enter>")
                assert card._title.bind("<Leave>")

            # Header and mode bar stay a thin band; the recent list gets the
            # remaining height.
            assert control.home_page.fixed_height() < 240
            recent = control.recent_view.master
            recent_row = int(recent.grid_info()["row"])
            assert recent.master.grid_rowconfigure(recent_row)["weight"] == 1

            control.home_page._mode_cards[0][1].set_shortcut("Ctrl+Alt+1")
            root.update()
            assert (
                control.home_page._mode_cards[0][1]._shortcut.cget("text")
                == "Ctrl+Alt+1"
            )
        finally:
            window.destroy()
            root.destroy()
    finally:
        store.close()


def test_control_window_scroll_search_footer_and_toast(
    tmp_path: Path,
) -> None:
    store = RecentStore(tmp_path)
    try:
        for index in range(4):
            image = Image.new("RGB", (120, 80), (index * 40, 80, 180))
            output = io.BytesIO()
            image.save(output, "PNG")
            store.add_png(
                output.getvalue(),
                mode="window" if index % 2 else "region",
                source="test",
            )
        service = FakeService(store)
        plugin = FakePlugin(service)
        root = tk.Tk()
        root.withdraw()
        window = tk.Toplevel(root)
        try:
            control = ControlWindow(window, plugin)
            control.pack(fill="both", expand=True)
            root.update()

            recent = control.recent_view.master
            recent_row = int(recent.grid_info()["row"])
            assert recent.master.grid_rowconfigure(recent_row)["weight"] == 1
            assert control.content.grid_rowconfigure(0)["weight"] == 1
            assert int(control.footer.grid_info()["row"]) == 1
            assert control.content.grid_rowconfigure(1)["weight"] == 0
            assert _find_label(control, "设置") is not None
            assert _find_label(control.footer, "设置") is None
            assert not hasattr(control.home_page, "pin_button")
            assert not hasattr(control.about_page, "pin_button")

            control.recent_view._search_var.set("窗口")
            control.recent_view._refresh_from_search()
            root.update()
            assert len(_rows(control)) == 2

            control.recent_view._search_var.set("")
            control.recent_view._refresh_from_search()
            root.update()
            assert len(_rows(control)) == 4

            entry = service.entries[0]
            control.recent_view._copy(entry)
            root.update()
            assert control._toast_label is not None
            assert "已复制" in control._toast_label.cget("text")
            control._hide_toast()
            assert control._toast_label is None

            control.recent_view._toggle_favorite(entry)
            root.update()
            assert any(item.favorite for item in service.entries)
            assert "已收藏" in control._toast_label.cget("text")

            control.recent_view._set_filter("favorite")
            root.update()
            assert len(_rows(control)) == 1
            control.recent_view._set_filter("window")
            root.update()
            assert len(_rows(control)) == 2
            control.recent_view._set_filter("all")
            root.update()
            assert len(_rows(control)) == 4

            control.show_page("about")
            assert control.current_page == "about"
            assert (
                _find_label(control.pages["about"], "关于截图助手") is not None
            )
            control.show_page("home")
            assert control.current_page == "home"
        finally:
            window.destroy()
            root.destroy()
    finally:
        store.close()
