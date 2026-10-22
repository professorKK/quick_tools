from __future__ import annotations

import io
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Sequence

import pytest
from PIL import Image

from quicktools.plugins.clipboard.models import (
    BackendStatus,
    ClipboardContent,
    ClipboardKind,
    current_platform,
)
from quicktools.plugins.clipboard.service import ClipboardService
from quicktools.plugins.clipboard.view import ClipboardView

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


class FakeBackend:
    name = "fake"

    def __init__(self) -> None:
        self.status = BackendStatus(True, "Fake（测试）")
        self.callback: Callable[[ClipboardContent], None] | None = None
        self.text_writes: list[str] = []

    def start(self, on_change) -> None:
        self.callback = on_change

    def stop(self) -> None:
        pass

    def read_text(self) -> str | None:
        return None

    def read_image(self) -> bytes | None:
        return None

    def read_files(self) -> list[str] | None:
        return None

    def write_text(self, text: str) -> None:
        self.text_writes.append(text)

    def write_image(self, png: bytes) -> None:
        pass

    def write_files(self, paths: Sequence[str]) -> None:
        pass


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (60, 40), (10, 120, 200)).save(output, "PNG")
    return output.getvalue()


@pytest.fixture()
def setup(tmp_path: Path):
    root = tk.Tk()
    root.withdraw()
    backend = FakeBackend()
    service = ClipboardService(tmp_path, root, backend=backend)
    service.start()

    file_path = tmp_path / "sample.txt"
    file_path.write_text("file body", encoding="utf-8")

    text_entry = service.store.add(
        ClipboardContent(kind=ClipboardKind.TEXT, text="unique 文本内容")
    )
    image_entry = service.store.add(
        ClipboardContent(kind=ClipboardKind.IMAGE, image_png=png_bytes())
    )
    file_entry = service.store.add(
        ClipboardContent(
            kind=ClipboardKind.FILES,
            paths=(str(file_path),),
            platform=current_platform(),
        )
    )

    window = tk.Toplevel(root)
    window.withdraw()
    view = ClipboardView(window, service)
    view.pack(fill="both", expand=True)
    window.deiconify()
    root.update()

    yield root, window, view, service, backend, text_entry, image_entry, file_entry

    try:
        window.destroy()
    except tk.TclError:
        pass
    try:
        service.stop()
    except Exception:
        pass
    try:
        root.update()
    except tk.TclError:
        pass
    try:
        root.destroy()
    except tk.TclError:
        pass


def card_action(view: ClipboardView, entry_id: int, kind: str):
    return view._card_actions[entry_id].actions[kind]


def test_ui_lists_and_selects_entries(setup) -> None:
    root, _window, view, _service, _backend, text_entry, image_entry, file_entry = setup
    assert not hasattr(view, "pin_button")
    assert view._count_vars["all"].get() == "3"
    assert len(view._card_rows) == 3

    view._select(text_entry.id)
    root.update()
    assert view._detail_title_var.get() == "unique 文本内容"
    assert card_action(view, text_entry.id, "reveal")._enabled is False

    view._select(image_entry.id)
    root.update()
    assert view._detail_title_var.get().startswith("图片")
    assert card_action(view, image_entry.id, "reveal")._enabled is True
    assert view._preview_photo is not None

    view._select(file_entry.id)
    root.update()
    assert card_action(view, file_entry.id, "reveal")._enabled is True
    assert view._detail_title_var.get() == "sample.txt"


def test_ui_card_actions_use_icons(setup, monkeypatch) -> None:
    root, _window, view, service, backend, text_entry, image_entry, _file_entry = setup

    for entry_id in (text_entry.id, image_entry.id):
        bar = view._card_actions[entry_id]
        assert isinstance(bar, tk.Canvas)
        assert list(bar.actions) == ["copy", "reveal", "delete"]
        assert bar._kind_at(5) == "copy"
        assert bar._kind_at(30) == "reveal"
        assert bar._kind_at(60) == "delete"
        assert bar._kind_at(26) is None

    calls: list[int] = []
    monkeypatch.setattr(view, "_reveal_entry", lambda entry: calls.append(entry.id))
    card_action(view, image_entry.id, "reveal")._command()
    assert calls == [image_entry.id]

    card_action(view, text_entry.id, "copy")._command()
    root.update()
    assert backend.text_writes == ["unique 文本内容"]

    card_action(view, text_entry.id, "delete")._command()
    root.update()
    assert service.get(text_entry.id) is None


def test_ui_search_filter_and_delete(setup) -> None:
    root, _window, view, service, _backend, text_entry, _image_entry, _file_entry = setup

    view.search.set("unique")
    view.refresh(reset_scroll=True)
    root.update()
    assert len(view._card_rows) == 1
    assert text_entry.id in view._card_rows

    view.search.set("")
    view._set_filter(ClipboardKind.IMAGE)
    root.update()
    assert len(view._card_rows) == 1
    assert service.counts()["image"] == 1

    view._set_filter(None)
    root.update()
    view._delete_entry(text_entry.id)
    root.update()
    assert service.counts()["text"] == 0
    assert text_entry.id not in view._card_rows

    view._toggle_sort()
    root.update()
    assert view._sort_button.cget("text") == "↑ 最早"


def test_ui_image_preview_falls_back_to_thumbnail(setup) -> None:
    root, _window, view, service, _backend, _text_entry, image_entry, _file_entry = setup
    full = service.image_file(image_entry)
    assert full is not None
    full.unlink()
    view._select(image_entry.id)
    root.update()
    assert view._preview_photo is not None
    assert view._preview_photo.width() <= max(
        1, view.detail_scroll.canvas.winfo_width()
    )

    def labels(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                yield child.cget("text")
            yield from labels(child)

    texts = "\n".join(labels(view.detail_scroll.inner))
    assert "缩略图" in texts


def test_ui_card_has_no_ellipsis_menu(setup) -> None:
    _root, _window, view, _service, _backend, text_entry, _image_entry, _file_entry = setup
    labels = [
        widget
        for widget in view._card_rows[text_entry.id]
        if isinstance(widget, tk.Label)
    ]
    assert all(label.cget("text") != "…" for label in labels)


def test_ui_text_can_be_edited_and_autosaved(setup) -> None:
    root, _window, view, service, backend, text_entry, _image_entry, _file_entry = setup
    view._select(text_entry.id)
    root.update()
    editor = view._text_editor
    assert editor is not None
    assert editor.cget("state") == "normal"

    editor.delete("1.0", "end")
    editor.insert("1.0", "修改后的文本内容")
    editor.edit_modified(True)
    view._on_text_modified()
    view._flush_text_edit()
    root.update()

    updated = service.get(text_entry.id)
    assert updated is not None
    assert updated.text_content == "修改后的文本内容"
    assert updated.title == "修改后的文本内容"
    assert updated.copy_count == 1
    assert view._detail_title_var.get() == "修改后的文本内容"
    assert view._card_labels[text_entry.id]["title"].cget("text") == "修改后的文本内容"

    # Re-copying uses the edited text, not the original clipboard snapshot.
    view._copy_current()
    assert backend.text_writes == ["修改后的文本内容"]
    editor = view._text_editor
    assert editor is not None

    # Empty edits are rejected and the editor is restored.
    editor.delete("1.0", "end")
    editor.edit_modified(True)
    view._on_text_modified()
    view._flush_text_edit()
    root.update()
    assert service.get(text_entry.id).text_content == "修改后的文本内容"
    assert editor.get("1.0", "end-1c") == "修改后的文本内容"


def test_ui_edit_merges_duplicate_content(setup) -> None:
    root, _window, view, service, _backend, text_entry, _image_entry, _file_entry = setup
    other = service.store.add(
        ClipboardContent(
            kind=ClipboardKind.TEXT,
            text="another text",
        )
    )
    view.refresh()
    root.update()
    view._select(other.id)
    root.update()
    editor = view._text_editor
    assert editor is not None
    editor.delete("1.0", "end")
    editor.insert("1.0", "unique 文本内容")
    editor.edit_modified(True)
    view._on_text_modified()
    view._flush_text_edit()
    root.update()

    assert service.get(other.id) is None
    assert service.get(text_entry.id) is not None
    assert view._selected_id == text_entry.id
    assert service.counts()["text"] == 1


def test_ui_missing_file_warning(setup) -> None:
    root, _window, view, _service, _backend, _text_entry, _image_entry, file_entry = setup
    Path(file_entry.paths[0]).unlink()
    view.refresh()
    root.update()
    secondary, color = view._card_secondary(file_entry)
    assert "失效" in secondary or "移动或删除" in secondary
    view._select(file_entry.id)
    root.update()

    def labels(widget):
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                yield child.cget("text")
            yield from labels(child)

    texts = "\n".join(labels(view.detail_scroll.inner))
    assert "移动或删除" in texts


def test_ui_copy_and_detach(setup) -> None:
    root, window, view, service, backend, text_entry, _image_entry, _file_entry = setup
    view._select(text_entry.id)
    root.update()
    view._copy_current()
    root.update()
    assert backend.text_writes == ["unique 文本内容"]
    assert service.entries(kind=ClipboardKind.TEXT)[0].copy_count == 2

    assert service._listeners
    window.destroy()
    root.update()
    assert service._listeners == []


def test_ui_first_open_fits_card_actions(tmp_path: Path) -> None:
    """The list must apply its final width on first map, not only on resize.

    The plugin window is created while withdrawn. Tk can deliver the final
    <Configure> before mapping, and no later <Configure> arrives, so the
    scrollable inner frame would keep its requested width and clip the
    right-aligned time label and action icons.
    """
    root = tk.Tk()
    root.geometry("1000x640+60+60")
    root.update()
    backend = FakeBackend()
    service = ClipboardService(tmp_path, root, backend=backend)
    service.start()
    for index in range(20):
        service.store.add(
            ClipboardContent(
                kind=ClipboardKind.TEXT,
                text=(
                    f"{index} 这是一条很长的剪贴板文本内容，用来复现首次打开时"
                    "右侧操作图标被裁切的问题。"
                ),
            )
        )

    window = tk.Toplevel(root)
    window.withdraw()
    view = ClipboardView(window, service)
    view.pack(fill="both", expand=True)
    try:
        window.geometry("1000x640+80+80")
        # Lay the withdrawn window out at its final size; this sends the
        # canvas its last <Configure> before it is mapped.
        window.update_idletasks()
        window.deiconify()
        deadline = time.monotonic() + 2.0
        while (
            not view.list_scroll.canvas.winfo_ismapped()
            and time.monotonic() < deadline
        ):
            root.update()
            time.sleep(0.01)
        root.update()

        canvas = view.list_scroll.canvas
        canvas_width = canvas.winfo_width()
        assert canvas_width > 1
        assert abs(view.list_scroll.inner.winfo_width() - canvas_width) <= 1
        viewport_right = canvas.winfo_rootx() + canvas_width
        entry_id = next(iter(view._card_actions))
        bar = view._card_actions[entry_id]
        assert bar.winfo_rootx() + bar.winfo_width() <= viewport_right
    finally:
        window.destroy()
        service.stop()
        try:
            root.update()
        except tk.TclError:
            pass
        root.destroy()


def test_ui_settings_entry_uses_shared_dialog(setup) -> None:
    _root, _window, view, _service, _backend, _text_entry, _image_entry, _file_entry = setup
    calls: list[bool] = []
    view._on_open_settings = lambda: calls.append(True)
    view._open_settings()
    assert calls == [True]


def test_clipboard_settings_panel_saves(setup, monkeypatch) -> None:
    root, window, view, service, _backend, _text_entry, _image_entry, _file_entry = setup
    from quicktools.plugins.clipboard.settings_view import ClipboardSettingsPanel

    host = tk.Toplevel(root)
    host.withdraw()
    try:
        panel = ClipboardSettingsPanel(host, view)
        panel.pack(fill="both", expand=True)
        root.update_idletasks()
        panel.entries_var.set("100")
        panel._save()
        root.update_idletasks()
        assert service.settings.max_entries == 100

        monkeypatch.setattr(
            "quicktools.plugins.clipboard.settings_view.messagebox.askyesno",
            lambda *args, **kwargs: True,
        )
        panel._clear_history()
        assert service.counts()["all"] == 0
    finally:
        host.destroy()
