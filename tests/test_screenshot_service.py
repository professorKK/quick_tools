from __future__ import annotations

import io
from pathlib import Path
from typing import Callable

from PIL import Image

from quicktools.plugin_api import PluginActions
from quicktools.plugins.screenshot import service as service_module
from quicktools.plugins.screenshot.capture.base import (
    CaptureCapabilities,
    CaptureStatus,
)
from quicktools.plugins.screenshot.editor.annotations import Tool
from quicktools.plugins.screenshot.models import (
    CapturedImage,
    Point,
    Rect,
    ScreenInfo,
    WindowInfo,
)
from quicktools.plugins.screenshot.service import ScreenshotService


class FakeRoot:
    def __init__(self) -> None:
        self.jobs: dict[str, Callable[[], None]] = {}
        self._counter = 0

    def after(self, _delay: int, callback: Callable[[], None]) -> str:
        self._counter += 1
        key = f"job-{self._counter}"
        self.jobs[key] = callback
        return key

    def after_cancel(self, key: str) -> None:
        self.jobs.pop(key, None)

    def run_next(self) -> None:
        jobs = list(self.jobs.items())
        self.jobs.clear()
        for _key, callback in jobs:
            callback()

    def winfo_pointerx(self) -> int:
        return 10

    def winfo_pointery(self) -> int:
        return 10


class FakeBackend:
    name = "fake"
    status = CaptureStatus(True, "Fake")

    def __init__(self) -> None:
        self.closed = False

    def capabilities(self):
        return CaptureCapabilities(True, True, True, True, False)

    def screens(self):
        return [ScreenInfo("fake", Rect(0, 0, 800, 600), primary=True)]

    def cursor_position(self):
        return Point(10, 10)

    def grab_screen(self):
        return CapturedImage(Image.new("RGB", (800, 600), (1, 2, 3)))

    def list_windows(self):
        return [
            WindowInfo(
                handle=7,
                title="Demo",
                app_name="Demo",
                rect=Rect(100, 100, 200, 100),
                z_order=0,
            )
        ]

    def raise_window(self, handle: int) -> bool:
        return True

    def close(self):
        self.closed = True


class FakeOverlay:
    instances: list["FakeOverlay"] = []

    def __init__(
        self,
        root,
        captured,
        screen,
        mode,
        windows,
        on_selected,
        on_cancel,
        *,
        on_window_selected=None,
        on_region_selected=None,
    ) -> None:
        self.on_selected = on_selected
        self.on_cancel = on_cancel
        self.on_window_selected = on_window_selected
        self.on_region_selected = on_region_selected
        self.windows = windows
        self.destroyed = False
        FakeOverlay.instances.append(self)

    def destroy(self) -> None:
        self.destroyed = True


class FakeScrollController:
    instances: list["FakeScrollController"] = []

    def __init__(self, root, region, settings, *, on_done, on_cancel) -> None:
        self.root = root
        self.region = region
        self.settings = settings
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.disposed = False
        FakeScrollController.instances.append(self)

    def dispose(self) -> None:
        self.disposed = True


class FakeEditor:
    instances: list["FakeEditor"] = []

    def __init__(
        self,
        root,
        image,
        settings,
        *,
        on_copy,
        on_save,
        on_close,
        on_return=None,
        on_autosave=None,
        initial_tool=None,
        **_kwargs,
    ) -> None:
        self.image = image
        self.on_copy = on_copy
        self.on_save = on_save
        self.on_autosave = on_autosave
        self.on_close = on_close
        self.on_return = on_return
        self.initial_tool = initial_tool
        self.disposed = False
        FakeEditor.instances.append(self)

    def dispose(self) -> None:
        self.disposed = True


class FakeActions:
    def __init__(self) -> None:
        self.hide_calls = 0
        self.restore_calls = 0
        self.open_calls = 0
        self.clips: list[bytes] = []
        self.posted: list[str] = []

    def hide_windows(self):
        self.hide_calls += 1

        def restore() -> None:
            self.restore_calls += 1

        return restore

    def copy_png_to_clipboard(self, png: bytes) -> None:
        self.clips.append(png)

    def post_action(self, action: str) -> None:
        self.posted.append(action)

    def open_window(self) -> None:
        self.open_calls += 1

    def app_hotkey_display(self) -> str:
        return "Ctrl+Alt+Space"


def make_actions() -> tuple[PluginActions, FakeActions]:
    fake = FakeActions()
    return (
        PluginActions(
            post_action=fake.post_action,
            open_window=fake.open_window,
            hide_windows=fake.hide_windows,
            copy_png_to_clipboard=fake.copy_png_to_clipboard,
            app_hotkey_display=fake.app_hotkey_display,
        ),
        fake,
    )


class PortalFakeBackend(FakeBackend):
    def capabilities(self):
        return CaptureCapabilities(False, False, True, False, True)


class FakePortalClient:
    instances: list["FakePortalClient"] = []

    def __init__(self) -> None:
        self.calls: list[bool] = []
        output = io.BytesIO()
        Image.new("RGB", (120, 80), (7, 8, 9)).save(output, "PNG")
        self.png = output.getvalue()
        FakePortalClient.instances.append(self)

    def capture(self, *, interactive: bool, modal: bool = True) -> bytes:
        self.calls.append(interactive)
        return self.png


def setup_service(
    monkeypatch,
    tmp_path: Path,
    *,
    backend=None,
    portal_client=None,
):
    FakeOverlay.instances = []
    FakeEditor.instances = []
    FakeScrollController.instances = []
    FakePortalClient.instances = []
    backend = backend or FakeBackend()
    monkeypatch.setattr(service_module, "create_backend", lambda: backend)
    monkeypatch.setattr(service_module, "CaptureOverlay", FakeOverlay)
    monkeypatch.setattr(service_module, "CaptureEditor", FakeEditor)
    monkeypatch.setattr(
        service_module, "ScrollController", FakeScrollController
    )
    if portal_client is not None:
        monkeypatch.setattr(
            service_module, "_create_portal_client", lambda: portal_client
        )
    root = FakeRoot()
    actions, fake_actions = make_actions()
    service = ScreenshotService(tmp_path, root, actions)
    service.start()
    return service, root, backend, fake_actions


def test_region_capture_copy_and_close(monkeypatch, tmp_path: Path) -> None:
    service, root, backend, actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        assert actions.hide_calls == 1
        assert service._busy
        root.run_next()
        assert FakeOverlay.instances
        overlay = FakeOverlay.instances[-1]

        image = Image.new("RGB", (100, 50), (10, 20, 30))
        overlay.on_selected(image)
        assert service._busy
        assert len(service.recent_entries()) == 1
        assert FakeEditor.instances
        editor = FakeEditor.instances[-1]
        assert editor.on_autosave is not None

        editor.on_copy(image)
        assert actions.clips
        editor.on_close(True)
        assert not service._busy
        assert len(service.recent_entries()) == 1
        assert actions.restore_calls == 0
        assert actions.open_calls == 0
        assert actions.hide_calls == 2
    finally:
        service.stop()
    assert backend.closed


def test_editor_close_and_return_restores_and_opens_assistant(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, actions = setup_service(monkeypatch, tmp_path)
    try:
        refreshes: list[bool] = []
        service.set_recent_changed_listener(
            lambda: refreshes.append(True)
        )
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        image = Image.new("RGB", (100, 50), (10, 20, 30))
        overlay.on_selected(image)
        editor = FakeEditor.instances[-1]
        assert editor.on_return is not None

        editor.on_copy(image)
        editor.on_return(True)
        assert not service._busy
        assert actions.restore_calls == 1
        assert actions.open_calls == 1
        assert actions.hide_calls == 1
        assert len(service.recent_entries()) == 1
        assert service.last_status == "截图已完成，已返回截图助手"
        assert refreshes
    finally:
        service.stop()


def test_editor_autosave_updates_recent_entry(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (100, 50), (10, 20, 30)))
        editor = FakeEditor.instances[-1]
        assert editor.on_autosave is not None
        before = service.recent_entries()[0]

        editor.on_autosave(Image.new("RGB", (60, 40), (200, 10, 10)))
        after = service.recent_entries()[0]
        assert (after.width, after.height) == (60, 40)
        assert after.byte_size != before.byte_size
        assert service.recent is not None
        thumb_path = service.recent.thumb_path(after)
        assert thumb_path is not None and thumb_path.exists()
        with Image.open(thumb_path) as thumb:
            assert thumb.width <= 360 and thumb.height <= 360
    finally:
        service.stop()


def test_editor_autosave_overwrites_saved_file(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (100, 50), (10, 20, 30)))
        editor = FakeEditor.instances[-1]
        target = tmp_path / "saved.png"

        editor.on_save(Image.new("RGB", (100, 50), (10, 20, 30)), target)
        assert target.exists()
        editor.on_autosave(Image.new("RGB", (70, 30), (0, 200, 0)))
        with Image.open(target) as saved:
            assert saved.size == (70, 30)
            assert saved.convert("RGB").getpixel((10, 10))[1] > 150
    finally:
        service.stop()


def test_editor_close_and_return_without_action_keeps_new_recent(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (30, 20), (5, 5, 5)))
        assert len(service.recent_entries()) == 1

        FakeEditor.instances[-1].on_return(False)
        assert len(service.recent_entries()) == 1
        assert not service._busy
        assert actions.restore_calls == 1
        assert actions.open_calls == 1
        assert service.last_status == "已关闭截图，已返回截图助手"
    finally:
        service.stop()


def test_open_recent_close_and_return_focuses_assistant(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (40, 30), (9, 9, 9)))
        FakeEditor.instances[-1].on_close(True)
        entry = service.recent_entries()[0]

        service.open_recent(entry)
        assert service._busy
        editor = FakeEditor.instances[-1]
        assert editor.on_autosave is not None
        editor.on_return(True)
        assert not service._busy
        assert actions.restore_calls == 0
        assert actions.open_calls == 1
        assert len(service.recent_entries()) == 1
    finally:
        service.stop()


def test_open_recent_plain_close_hides_visible_windows(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (40, 30), (9, 9, 9)))
        FakeEditor.instances[-1].on_close(True)
        entry = service.recent_entries()[0]
        hide_calls_before = actions.hide_calls

        service.open_recent(entry)
        FakeEditor.instances[-1].on_close(True)
        assert not service._busy
        assert actions.hide_calls == hide_calls_before + 1
        assert actions.restore_calls == 0
        assert actions.open_calls == 0
        assert len(service.recent_entries()) == 1
    finally:
        service.stop()


def test_region_capture_cancel_restores_windows(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_cancel()
        assert not service._busy
        assert actions.restore_calls == 1
        assert service.recent_entries() == []
    finally:
        service.stop()


def test_editor_close_without_action_keeps_new_recent(
    monkeypatch, tmp_path: Path
) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (30, 20), (5, 5, 5)))
        assert len(service.recent_entries()) == 1
        editor = FakeEditor.instances[-1]
        editor.on_close(False)
        assert len(service.recent_entries()) == 1
        assert not service._busy
    finally:
        service.stop()


def test_window_capture_flow(monkeypatch, tmp_path: Path) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("window")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        assert overlay.windows
        window = overlay.windows[0]

        overlay.on_window_selected(window)
        assert service._busy
        root.run_next()
        assert FakeEditor.instances
        assert len(service.recent_entries()) == 1
        FakeEditor.instances[-1].on_close(False)
        assert not service._busy
    finally:
        service.stop()


def test_freeform_capture_flow(monkeypatch, tmp_path: Path) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("freeform")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        image = Image.new("RGBA", (80, 50), (10, 20, 30, 255))
        overlay.on_selected(image)
        assert service._busy
        assert FakeEditor.instances
        FakeEditor.instances[-1].on_close(False)
        assert not service._busy
    finally:
        service.stop()


def test_scroll_capture_flow(monkeypatch, tmp_path: Path) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("scroll")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        assert overlay.on_region_selected is not None
        image = Image.new("RGB", (200, 100))
        overlay.on_region_selected(image, Rect(0, 0, 200, 100), None)
        assert FakeScrollController.instances
        controller = FakeScrollController.instances[-1]

        stitched = Image.new("RGB", (200, 400))
        controller.on_done(stitched, 4, "已到达底部")
        assert FakeEditor.instances
        assert service._busy
        FakeEditor.instances[-1].on_close(False)
        assert not service._busy
    finally:
        service.stop()


def test_portal_region_capture_flow(monkeypatch, tmp_path: Path) -> None:
    portal = FakePortalClient()
    service, root, _backend, _actions = setup_service(
        monkeypatch,
        tmp_path,
        backend=PortalFakeBackend(),
        portal_client=portal,
    )
    try:
        service.capture("region")
        assert service._portal_thread is not None
        service._portal_thread.join(2)
        root.run_next()
        assert portal.calls == [True]
        assert FakeEditor.instances
        assert FakeEditor.instances[-1].initial_tool is None
        FakeEditor.instances[-1].on_close(False)
        assert not service._busy
    finally:
        service.stop()


def test_portal_freeform_uses_lasso_tool(monkeypatch, tmp_path: Path) -> None:
    portal = FakePortalClient()
    service, root, _backend, _actions = setup_service(
        monkeypatch,
        tmp_path,
        backend=PortalFakeBackend(),
        portal_client=portal,
    )
    try:
        service.capture("freeform")
        assert service._portal_thread is not None
        service._portal_thread.join(2)
        root.run_next()
        assert portal.calls == [False]
        assert FakeEditor.instances
        assert FakeEditor.instances[-1].initial_tool is Tool.LASSO
        FakeEditor.instances[-1].on_close(False)
    finally:
        service.stop()


def test_scroll_cancel_flow(monkeypatch, tmp_path: Path) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("scroll")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_region_selected(
            Image.new("RGB", (200, 100)), Rect(0, 0, 200, 100), None
        )
        controller = FakeScrollController.instances[-1]
        controller.on_cancel("已取消滚动截图")
        assert not service._busy
        assert service._scroll_controller is None
    finally:
        service.stop()


def test_recent_favorite_toggle_and_filter(monkeypatch, tmp_path: Path) -> None:
    service, root, _backend, _actions = setup_service(monkeypatch, tmp_path)
    try:
        service.capture("region")
        root.run_next()
        overlay = FakeOverlay.instances[-1]
        overlay.on_selected(Image.new("RGB", (100, 50), (10, 20, 30)))
        entry = service.recent_entries()[0]

        starred = service.set_recent_favorite(entry, True)
        assert starred is not None and starred.favorite is True
        assert service.last_status == "已收藏截图"
        assert [item.id for item in service.recent_entries(favorite=True)] == [entry.id]

        toggled = service.toggle_recent_favorite(starred)
        assert toggled is not None and toggled.favorite is False
        assert service.last_status == "已取消收藏"
        assert service.recent_entries(favorite=True) == []
        assert service.recent_entries(mode="region")
    finally:
        service.stop()
