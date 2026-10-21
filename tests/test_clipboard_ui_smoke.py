from __future__ import annotations

import io
import os
import sys
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


def test_ui_lists_and_selects_entries(setup) -> None:
    root, _window, view, _service, _backend, text_entry, image_entry, file_entry = setup
    assert view.pin_button.winfo_exists()
    assert view._count_vars["all"].get() == "3"
    assert len(view._card_rows) == 3

    view._select(text_entry.id)
    root.update()
    assert view._detail_title_var.get() == "unique 文本内容"
    assert view._reveal_button._enabled is False

    view._select(image_entry.id)
    root.update()
    assert view._detail_title_var.get().startswith("图片")
    assert view._reveal_button._enabled is True
    assert view._preview_photo is not None

    view._select(file_entry.id)
    root.update()
    assert view._reveal_button._enabled is True
    assert view._detail_title_var.get() == "sample.txt"


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


def test_ui_settings_window_opens_and_closes(setup) -> None:
    root, _window, view, _service, _backend, _text_entry, _image_entry, _file_entry = setup
    view._open_settings()
    root.update()
    assert view._settings_window is not None
    settings_window = view._settings_window
    assert settings_window.winfo_exists()
    view._close_settings(settings_window)
    root.update()
    assert view._settings_window is None
