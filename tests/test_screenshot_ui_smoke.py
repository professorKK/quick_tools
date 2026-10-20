from __future__ import annotations

import os
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest
from PIL import Image

from quicktools.plugins.screenshot.editor.annotations import Tool
from quicktools.plugins.screenshot.editor.editor_window import CaptureEditor
from quicktools.plugins.screenshot.models import (
    CapturedImage,
    CaptureMode,
    Point,
    Rect,
    ScreenInfo,
    WindowInfo,
)
from quicktools.plugins.screenshot.selection.overlay import CaptureOverlay
from quicktools.plugins.screenshot.settings import ScreenshotSettings

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("DISPLAY"),
    reason="Tk display required",
)


@pytest.fixture()
def root():
    try:
        instance = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk 不可用：{exc}")
    instance.withdraw()
    try:
        yield instance
    finally:
        try:
            instance.destroy()
        except tk.TclError:
            pass


def test_overlay_selects_rectangle(root: tk.Tk) -> None:
    image = Image.new("RGB", (400, 300), (12, 34, 56))
    captured = CapturedImage(image=image, origin=Point(0, 0))
    screen = ScreenInfo("test", Rect(0, 0, 400, 300), primary=True)
    selected: list[Image.Image] = []
    cancelled: list[bool] = []

    overlay = CaptureOverlay(
        root,
        captured,
        screen,
        CaptureMode.REGION,
        [],
        selected.append,
        lambda: cancelled.append(True),
    )
    overlay._top.withdraw()
    overlay._on_press(SimpleNamespace(x=20, y=30))
    overlay._on_motion(SimpleNamespace(x=220, y=180))
    overlay._on_release(SimpleNamespace(x=220, y=180))
    root.update()

    assert cancelled == []
    assert len(selected) == 1
    assert selected[0].size == (200, 150)
    assert selected[0].getpixel((0, 0)) == (12, 34, 56)


def test_overlay_freeform(root: tk.Tk) -> None:
    image = Image.new("RGB", (200, 150), (30, 40, 50))
    captured = CapturedImage(image=image)
    screen = ScreenInfo("test", Rect(0, 0, 200, 150), primary=True)
    selected: list[Image.Image] = []
    overlay = CaptureOverlay(
        root,
        captured,
        screen,
        CaptureMode.FREEFORM,
        [],
        selected.append,
        lambda: None,
    )
    overlay._top.withdraw()
    overlay._on_press(SimpleNamespace(x=20, y=20))
    overlay._on_motion(SimpleNamespace(x=120, y=20))
    overlay._on_motion(SimpleNamespace(x=60, y=100))
    overlay._on_release(SimpleNamespace(x=20, y=20))
    root.update()

    assert len(selected) == 1
    result = selected[0]
    assert result.mode == "RGBA"
    assert result.size == (100, 80)
    assert result.getpixel((50, 30))[3] == 255
    assert result.getpixel((90, 70))[3] == 0


def test_overlay_window_selection(root: tk.Tk) -> None:
    captured = CapturedImage(image=Image.new("RGB", (400, 300)))
    screen = ScreenInfo("test", Rect(0, 0, 400, 300), primary=True)
    selected: list = []
    windows = [
        WindowInfo(1, "Back", "back", Rect(10, 10, 200, 150), z_order=0),
        WindowInfo(2, "Front", "front", Rect(100, 100, 150, 100), z_order=1),
    ]
    overlay = CaptureOverlay(
        root,
        captured,
        screen,
        CaptureMode.WINDOW,
        windows,
        lambda _image: None,
        lambda: None,
        on_window_selected=selected.append,
    )
    overlay._top.withdraw()
    overlay._on_motion(SimpleNamespace(x=120, y=120))
    overlay._on_press(SimpleNamespace(x=120, y=120))
    root.update()

    assert len(selected) == 1
    assert selected[0].title == "Front"


def test_overlay_cancel(root: tk.Tk) -> None:
    captured = CapturedImage(image=Image.new("RGB", (200, 100)))
    screen = ScreenInfo("test", Rect(0, 0, 200, 100), primary=True)
    cancelled: list[bool] = []
    overlay = CaptureOverlay(
        root,
        captured,
        screen,
        CaptureMode.REGION,
        [],
        lambda _image: None,
        lambda: cancelled.append(True),
    )
    overlay._top.withdraw()
    overlay._cancel()
    root.update()
    assert cancelled == [True]


def test_editor_copy_and_close(root: tk.Tk) -> None:
    image = Image.new("RGB", (120, 80), (5, 6, 7))
    copied: list[Image.Image] = []
    closed: list[bool] = []

    editor = CaptureEditor(
        root,
        image,
        ScreenshotSettings(),
        on_copy=copied.append,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
    )
    editor.withdraw()
    root.update()
    editor.copy()
    assert copied and copied[0].size == (120, 80)
    assert editor._copy_button is not None
    assert editor._copy_button.cget("text") == "已复制 ✓"
    assert editor._toast_label is not None
    assert "已复制" in editor._toast_label.cget("text")
    editor.close()
    root.update()
    assert closed == [True]


def test_editor_close_and_return(root: tk.Tk) -> None:
    image = Image.new("RGB", (120, 80), (5, 6, 7))
    closed: list[bool] = []
    returned: list[bool] = []

    editor = CaptureEditor(
        root,
        image,
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
        on_return=returned.append,
    )
    editor.withdraw()
    root.update()
    assert editor._close_return_button is not None
    assert editor._close_return_button.cget("text") == "关闭并返回"

    editor._done = True
    editor.close_and_return()
    root.update()
    assert returned == [True]
    assert closed == []


def _widget_texts(widget) -> list[str]:
    texts: list[str] = []
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except tk.TclError:
            text = ""
        if text:
            texts.append(text)
        texts.extend(_widget_texts(child))
    return texts


def test_editor_autosaves_and_has_no_save_button(root: tk.Tk) -> None:
    autosaved: list[Image.Image] = []
    closed: list[bool] = []
    editor = CaptureEditor(
        root,
        Image.new("RGB", (120, 80), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
        on_autosave=autosaved.append,
    )
    editor.withdraw()
    root.update()

    texts = _widget_texts(editor)
    assert "保存" not in texts
    assert "另存为" in texts

    editor.document.add_number(Point(10, 10), editor.edit_style)
    editor._on_document_changed()
    assert editor._autosave_job is not None

    editor.close()
    root.update()
    assert autosaved and autosaved[0].size == (120, 80)
    assert closed == [True]


def test_editor_close_without_edits_skips_confirm(
    root: tk.Tk, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "quicktools.plugins.screenshot.editor.editor_window.messagebox.askyesno",
        lambda title, message, **kwargs: calls.append(message) or False,
    )
    closed: list[bool] = []
    editor = CaptureEditor(
        root,
        Image.new("RGB", (120, 80), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
        require_action_on_close=False,
    )
    editor.withdraw()
    root.update()

    editor.close()
    root.update()
    assert calls == []
    assert closed == [False]


def test_editor_close_with_edits_confirms(root: tk.Tk, monkeypatch) -> None:
    calls: list[str] = []
    answers = [False, True]

    def askyesno(title, message, **kwargs) -> bool:
        calls.append(message)
        return answers.pop(0)

    monkeypatch.setattr(
        "quicktools.plugins.screenshot.editor.editor_window.messagebox.askyesno",
        askyesno,
    )
    closed: list[bool] = []
    editor = CaptureEditor(
        root,
        Image.new("RGB", (120, 80), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
        require_action_on_close=False,
    )
    editor.withdraw()
    root.update()
    editor.document.add_number(Point(10, 10), editor.edit_style)

    editor.close()
    root.update()
    assert closed == []
    assert editor.winfo_exists()
    assert "未保存的修改" in calls[0]

    editor.close()
    root.update()
    assert closed == [False]
    assert len(calls) == 2


def test_editor_fresh_capture_without_export_confirms(
    root: tk.Tk, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "quicktools.plugins.screenshot.editor.editor_window.messagebox.askyesno",
        lambda title, message, **kwargs: calls.append(message) or True,
    )
    closed: list[bool] = []
    editor = CaptureEditor(
        root,
        Image.new("RGB", (120, 80), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
    )
    editor.withdraw()
    root.update()

    editor.close()
    root.update()
    assert closed == [False]
    assert calls and "还没有复制或保存" in calls[0]


def test_editor_draws_hollow_shapes(root: tk.Tk) -> None:
    image = Image.new("RGB", (400, 240), "white")
    copied: list[Image.Image] = []
    closed: list[bool] = []
    editor = CaptureEditor(
        root,
        image,
        ScreenshotSettings(),
        on_copy=copied.append,
        on_save=lambda _image, _path: None,
        on_close=closed.append,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas

    def draw(tool, start: Point, end: Point) -> None:
        canvas.set_tool(tool)
        x1, y1 = canvas._display_point(start)
        x2, y2 = canvas._display_point(end)
        canvas._on_press(SimpleNamespace(x=x1, y=y1))
        canvas._on_motion(SimpleNamespace(x=x2, y=y2))
        canvas._on_release(SimpleNamespace(x=x2, y=y2))

    draw(Tool.RECT, Point(40, 40), Point(180, 140))
    draw(Tool.ELLIPSE, Point(240, 40), Point(360, 150))
    root.update()
    assert len(editor.document.annotations) == 2

    editor.copy()
    rendered = copied[0].convert("RGB")
    assert rendered.getpixel((110, 90))[0] > 200
    assert rendered.getpixel((300, 95))[0] > 200
    assert rendered.getpixel((40, 90))[1] < 200
    editor.close()
    root.update()
    assert closed == [True]


def test_editor_brush_draws_freehand_stroke(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (400, 240), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.set_tool(Tool.BRUSH)
    assert editor.toolbar._tool_buttons[Tool.BRUSH].cget("text") == "画笔"

    points = [Point(40, 40), Point(100, 60), Point(160, 120)]
    display = [canvas._display_point(point) for point in points]
    canvas._on_press(SimpleNamespace(x=display[0][0], y=display[0][1]))
    for x, y in display[1:]:
        canvas._on_motion(SimpleNamespace(x=x, y=y))
    canvas._on_release(
        SimpleNamespace(x=display[-1][0], y=display[-1][1])
    )
    root.update()

    assert len(editor.document.annotations) == 1
    stroke = editor.document.annotations[0]
    assert stroke.tool is Tool.BRUSH
    assert len(stroke.points) >= 3
    assert canvas.tool is Tool.BRUSH
    rendered = editor.document.render().convert("RGB")
    assert rendered.getpixel((100, 60))[0] > 180
    assert rendered.getpixel((100, 60))[1] < 120


def test_editor_pans_with_space_and_empty_select_drag(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (600, 400), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.zoom_to(3.0)
    root.update()
    assert canvas._can_pan()
    center = SimpleNamespace(
        x=canvas.canvas.winfo_width() // 2,
        y=canvas.canvas.winfo_height() // 2,
    )

    before = (canvas._offset_x, canvas._offset_y)
    canvas._on_space_press(center)
    canvas._on_press(center)
    canvas._on_motion(
        SimpleNamespace(x=center.x + 40, y=center.y + 25)
    )
    canvas._on_release(
        SimpleNamespace(x=center.x + 40, y=center.y + 25)
    )
    canvas._on_space_release(center)
    root.update()
    assert (canvas._offset_x, canvas._offset_y) != before
    assert not editor.document.annotations

    canvas.set_tool(Tool.SELECT)
    before = (canvas._offset_x, canvas._offset_y)
    canvas._on_press(center)
    canvas._on_motion(
        SimpleNamespace(x=center.x - 35, y=center.y - 20)
    )
    canvas._on_release(
        SimpleNamespace(x=center.x - 35, y=center.y - 20)
    )
    root.update()
    assert (canvas._offset_x, canvas._offset_y) != before
    assert canvas._pan_start is None


def test_editor_starts_with_lasso_for_wayland_freeform(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (300, 200), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
        initial_tool=Tool.LASSO,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    assert canvas.tool is Tool.LASSO

    def event(point: Point):
        x, y = canvas._display_point(point)
        return SimpleNamespace(x=x, y=y)

    canvas._on_press(event(Point(20, 20)))
    canvas._on_motion(event(Point(220, 20)))
    canvas._on_motion(event(Point(120, 160)))
    canvas._on_release(event(Point(20, 20)))
    root.update()
    assert editor.document.image_size == (200, 140)
    assert editor.document.render().getpixel((10, 130))[3] == 0
    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_redo_falls_back_to_reset(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (300, 200), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.fit_to_window()
    root.update()

    def event(point: Point):
        x, y = canvas._display_point(point)
        return SimpleNamespace(x=x, y=y)

    canvas.set_tool(Tool.RECT)
    canvas._on_press(event(Point(20, 20)))
    canvas._on_motion(event(Point(100, 80)))
    canvas._on_release(event(Point(100, 80)))
    root.update()
    assert len(editor.document.annotations) == 1

    editor.toolbar._redo_or_reset()
    root.update()
    assert editor.document.annotations == []

    canvas.undo()
    root.update()
    assert len(editor.document.annotations) == 1

    canvas.undo()
    root.update()
    assert editor.document.annotations == []
    editor.toolbar._redo_or_reset()
    root.update()
    assert len(editor.document.annotations) == 1

    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_crop_by_dragging_image_edges(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (300, 200), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.fit_to_window()
    root.update()

    def event(point: Point):
        x, y = canvas._display_point(point)
        return SimpleNamespace(x=x, y=y)

    canvas.set_tool(Tool.CROP)
    assert canvas._crop_rect == Rect(0, 0, 300, 200)
    canvas._on_press(event(Point(299, 100)))
    canvas._on_motion(event(Point(200, 100)))
    canvas._on_release(event(Point(200, 100)))
    canvas._on_press(event(Point(100, 199)))
    canvas._on_motion(event(Point(100, 150)))
    canvas._on_release(event(Point(100, 150)))
    root.update()
    assert canvas._crop_rect is not None
    assert canvas._crop_rect.width < 300
    assert canvas._crop_rect.height < 200
    assert canvas.apply_crop()
    root.update()
    assert editor.document.image_size == (200, 150)
    assert canvas.tool is Tool.SELECT

    canvas.reset_to_original()
    root.update()
    assert editor.document.image_size == (300, 200)
    assert editor.document.annotations == []

    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_text_input_is_transparent_and_font_size_live(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (300, 200), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.fit_to_window()
    root.update()
    canvas.set_tool(Tool.TEXT)
    x, y = canvas._display_point(Point(40, 40))
    canvas._on_press(SimpleNamespace(x=x, y=y))
    root.update()

    entry = canvas._entry
    assert entry is not None
    assert entry.cget("bg") == "#ffffff"
    assert int(entry.cget("highlightthickness")) == 0
    assert int(entry.cget("bd")) == 0
    assert entry.cget("fg") == "#e53935"

    before_font = entry.cget("font")
    assert "-" in str(before_font)
    editor.toolbar.font_size_var.set("40")
    root.update()
    assert canvas._entry is entry
    assert entry.cget("font") != before_font
    assert "-" in str(entry.cget("font"))

    entry.insert(0, "透明输入")
    canvas._commit_entry()
    root.update()
    text = next(
        item for item in editor.document.annotations if item.tool is Tool.TEXT
    )
    assert text.text == "透明输入"
    assert text.style.font_size == 40

    editor.document.select(text.id)
    editor.toolbar.font_size_var.set("60")
    root.update()
    assert text.style.font_size == 60

    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_watermark_prompt(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (300, 200), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.set_tool(Tool.WATERMARK)

    def fill_dialog() -> None:
        for child in editor.winfo_children():
            if isinstance(child, tk.Toplevel) and hasattr(child, "_value"):
                child._value.set("测试水印")
                child.ok()

    root.after(200, fill_dialog)
    canvas._add_watermark()
    root.update()
    watermarks = [
        item
        for item in editor.document.annotations
        if item.tool is Tool.WATERMARK and item.text == "测试水印"
    ]
    assert len(watermarks) == 1
    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_watermark_prompt_survives_grab_failure(
    root: tk.Tk, monkeypatch
) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (300, 200), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    canvas.set_tool(Tool.WATERMARK)

    def fail_grab(_self) -> None:
        raise tk.TclError("grab failed: keyboard or pointer frozen")

    monkeypatch.setattr(tk.Toplevel, "grab_set", fail_grab)

    def fill_dialog() -> None:
        for child in editor.winfo_children():
            if isinstance(child, tk.Toplevel) and hasattr(child, "_value"):
                child._value.set("无 grab 水印")
                child.ok()

    root.after(200, fill_dialog)
    canvas._add_watermark()
    root.update()
    assert any(
        item.tool is Tool.WATERMARK and item.text == "无 grab 水印"
        for item in editor.document.annotations
    )
    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_wheel_zoom_and_pan(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (400, 240), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas
    root.update()
    canvas.fit_to_window()
    root.update()
    fit_scale = canvas._view_scale
    assert fit_scale > 1.0
    assert editor._zoom_var.get() != "缩放 100%"

    canvas.zoom_to(1.0)
    root.update()
    assert abs(canvas._view_scale - 1.0) < 1e-6
    assert editor._zoom_var.get() == "缩放 100%"

    canvas.fit_to_window()
    root.update()
    assert abs(canvas._view_scale - fit_scale) < 1e-6

    center_x = canvas.canvas.winfo_width() // 2
    center_y = canvas.canvas.winfo_height() // 2
    before = canvas._image_point(SimpleNamespace(x=center_x, y=center_y))
    canvas._on_wheel_linux(SimpleNamespace(num=4, x=center_x, y=center_y))
    root.update()
    after = canvas._image_point(SimpleNamespace(x=center_x, y=center_y))
    assert canvas._view_scale > fit_scale
    assert not canvas._fit_mode
    assert abs(after.x - before.x) < 1.5
    assert abs(after.y - before.y) < 1.5

    canvas.zoom_to(0.5)
    root.update()
    assert abs(canvas._view_scale - 0.5) < 1e-6

    canvas.fit_to_window()
    root.update()
    assert canvas._fit_mode
    assert abs(canvas._view_scale - fit_scale) < 1e-6

    canvas.zoom_to(4.0)
    root.update()
    assert abs(canvas._view_scale - 4.0) < 1e-6
    offset_x = canvas._offset_x
    canvas._on_pan_press(SimpleNamespace(x=center_x, y=center_y))
    canvas._on_pan_motion(
        SimpleNamespace(x=center_x + 40, y=center_y + 20)
    )
    canvas._on_pan_release(SimpleNamespace(x=center_x + 40, y=center_y + 20))
    root.update()
    assert canvas._offset_x != offset_x
    assert canvas.render().size == (400, 240)

    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()


def test_editor_move_resize_and_text(root: tk.Tk) -> None:
    editor = CaptureEditor(
        root,
        Image.new("RGB", (500, 300), "white"),
        ScreenshotSettings(),
        on_copy=lambda _image: None,
        on_save=lambda _image, _path: None,
        on_close=lambda _done: None,
    )
    editor.withdraw()
    root.update()
    canvas = editor._canvas

    def event(point: Point):
        x, y = canvas._display_point(point)
        return SimpleNamespace(x=x, y=y)

    canvas.set_tool(Tool.RECT)
    canvas._on_press(event(Point(50, 50)))
    canvas._on_motion(event(Point(200, 150)))
    canvas._on_release(event(Point(200, 150)))
    annotation = editor.document.annotations[0]
    assert annotation.bounds == Rect(50, 50, 150, 100)

    canvas.set_tool(Tool.SELECT)
    canvas._on_press(event(Point(100, 100)))
    canvas._on_motion(event(Point(130, 120)))
    canvas._on_release(event(Point(130, 120)))
    assert annotation.bounds == Rect(80, 70, 150, 100)

    handle = Point(annotation.bounds.right, annotation.bounds.bottom)
    canvas._on_press(event(handle))
    canvas._on_motion(event(Point(290, 250)))
    canvas._on_release(event(Point(290, 250)))
    assert annotation.bounds.width > 150

    canvas.set_tool(Tool.TEXT)
    canvas._on_press(event(Point(60, 200)))
    root.update()
    assert canvas._entry is not None
    canvas._entry.insert(0, "测试 Text")
    canvas._commit_entry()
    root.update()
    texts = [
        item for item in editor.document.annotations if item.tool is Tool.TEXT
    ]
    assert len(texts) == 1
    assert texts[0].text == "测试 Text"

    canvas.undo()
    assert not [
        item for item in editor.document.annotations if item.tool is Tool.TEXT
    ]
    canvas.redo()
    assert [
        item for item in editor.document.annotations if item.tool is Tool.TEXT
    ]
    editor._done = True
    editor.mark_exported()
    editor.close()
    root.update()
