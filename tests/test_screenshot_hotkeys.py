from __future__ import annotations

from types import SimpleNamespace

import pytest

from quicktools.plugins.screenshot import plugin as plugin_module
from quicktools.plugins.screenshot.plugin import ScreenshotPlugin
from quicktools.plugins.screenshot.settings import ScreenshotSettings
from quicktools.plugins.screenshot.shortcuts import (
    MODE_HOTKEYS,
    shortcut_label,
    shortcut_labels,
)


class FakeActions:
    def __init__(self) -> None:
        self.posted: list[str] = []

    def post_action(self, action: str) -> None:
        self.posted.append(action)

    def app_hotkey_display(self) -> str:
        return ""


class FakeService:
    def __init__(self) -> None:
        self.settings = ScreenshotSettings()
        self.statuses: list[str] = []

    def report_status(self, message: str) -> None:
        self.statuses.append(message)


class FakeHotkeyManager:
    instances: list["FakeHotkeyManager"] = []
    fail_displays: set[str] = set()

    def __init__(self, spec, callback) -> None:
        self.spec = spec
        self.callback = callback
        self.error = ""
        self.running = False

    def start(self, spec=None) -> bool:
        if self.spec.display() in self.fail_displays:
            self.error = "快捷键被占用"
            return False
        self.running = True
        FakeHotkeyManager.instances.append(self)
        return True

    def stop(self) -> None:
        self.running = False


def make_plugin() -> tuple[ScreenshotPlugin, FakeService, FakeActions]:
    actions = FakeActions()
    context = SimpleNamespace(actions=actions)
    plugin = ScreenshotPlugin(context)
    return plugin, FakeService(), actions


@pytest.fixture(autouse=True)
def reset_fake_managers(monkeypatch):
    FakeHotkeyManager.instances = []
    FakeHotkeyManager.fail_displays = set()
    monkeypatch.setattr(plugin_module, "HotkeyManager", FakeHotkeyManager)
    monkeypatch.setattr(plugin_module, "is_wayland_session", lambda: False)
    yield


def test_registers_primary_and_mode_hotkeys() -> None:
    plugin, service, actions = make_plugin()
    plugin._start_hotkey(service)

    assert len(plugin._hotkey_managers) == 5
    assert plugin._hotkey is not None
    assert plugin._hotkey.spec.display() == "Ctrl+Alt+X"
    displays = {
        manager.spec.display() for manager in plugin._hotkey_managers
    }
    assert displays == {
        "Ctrl+Alt+X",
        "Ctrl+Alt+1",
        "Ctrl+Alt+2",
        "Ctrl+Alt+3",
        "Ctrl+Alt+4",
    }

    for manager in plugin._hotkey_managers:
        manager.callback()
    assert actions.posted == [
        "capture_region",
        "capture_region",
        "capture_window",
        "capture_freeform",
        "capture_scroll",
    ]

    plugin._stop_hotkey()
    assert plugin._hotkey_managers == []
    assert plugin._hotkey is None
    assert all(not manager.running for manager in FakeHotkeyManager.instances)


def test_wayland_registers_no_hotkeys(monkeypatch) -> None:
    monkeypatch.setattr(plugin_module, "is_wayland_session", lambda: True)
    plugin, service, _actions = make_plugin()
    plugin._start_hotkey(service)
    assert plugin._hotkey_managers == []
    assert service.statuses
    assert "Wayland" in service.statuses[-1]


def test_one_mode_failure_keeps_other_hotkeys() -> None:
    FakeHotkeyManager.fail_displays = {"Ctrl+Alt+2"}
    plugin, service, _actions = make_plugin()
    plugin._start_hotkey(service)

    assert plugin._hotkey is not None
    assert plugin._hotkey.spec.display() == "Ctrl+Alt+X"
    displays = {
        manager.spec.display() for manager in plugin._hotkey_managers
    }
    assert "Ctrl+Alt+1" in displays
    assert "Ctrl+Alt+3" in displays
    assert "Ctrl+Alt+4" in displays
    assert "Ctrl+Alt+2" not in displays
    assert "失败" not in service.statuses[-1]
    assert "冲突" not in service.statuses[-1]
    assert "部分模式快捷键未注册" in service.statuses[-1]


def test_suspend_and_resume_all_hotkeys() -> None:
    plugin, service, _actions = make_plugin()
    plugin.service = service
    plugin._start_hotkey(service)
    assert len(plugin._hotkey_managers) == 5

    plugin.suspend_hotkey()
    assert plugin._hotkey_managers == []
    assert all(not manager.running for manager in FakeHotkeyManager.instances)

    plugin.resume_hotkey()
    assert len(plugin._hotkey_managers) == 5


def test_mode_shortcut_labels_are_stable() -> None:
    assert set(MODE_HOTKEYS) == {
        "capture_region",
        "capture_window",
        "capture_freeform",
        "capture_scroll",
    }
    assert shortcut_label("capture_region") == "Ctrl+Alt+1"
    assert shortcut_labels()["capture_scroll"] == "Ctrl+Alt+4"
    with pytest.raises(KeyError):
        shortcut_label("capture_unknown")
