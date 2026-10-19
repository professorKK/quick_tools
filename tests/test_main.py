from __future__ import annotations

from typing import ClassVar

import pytest

from quicktools import __main__ as cli


class FakeApp:
    instances: ClassVar[list[FakeApp]] = []

    def __init__(self, start_visible: bool = True) -> None:
        self.start_visible = start_visible
        self.ran = False
        FakeApp.instances.append(self)

    def run(self) -> None:
        self.ran = True


class FakeIpc:
    def __init__(self) -> None:
        self.result = False
        self.commands: list[str] = []

    def __call__(self, command: str) -> bool:
        self.commands.append(command)
        return self.result


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch) -> FakeIpc:
    FakeApp.instances = []
    ipc = FakeIpc()
    monkeypatch.setattr(cli, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(cli, "setup_logging", lambda: None)
    monkeypatch.setattr(cli, "QuickToolsApp", FakeApp)
    monkeypatch.setattr(cli, "send_command", ipc)
    return ipc


def test_background_exits_silently_when_instance_runs(patched: FakeIpc) -> None:
    patched.result = True

    assert cli.main(["--background"]) == 0

    assert patched.commands == ["ping"]
    assert FakeApp.instances == []


def test_background_starts_hidden_without_instance(patched: FakeIpc) -> None:
    patched.result = False

    assert cli.main(["--background"]) == 0

    assert patched.commands == ["ping"]
    assert len(FakeApp.instances) == 1
    assert FakeApp.instances[0].start_visible is False
    assert FakeApp.instances[0].ran


def test_normal_launch_surfaces_existing_instance(patched: FakeIpc) -> None:
    patched.result = True

    assert cli.main([]) == 0

    assert patched.commands == ["show"]
    assert FakeApp.instances == []


def test_normal_launch_starts_visible_without_instance(patched: FakeIpc) -> None:
    patched.result = False

    assert cli.main([]) == 0

    assert patched.commands == ["show"]
    assert FakeApp.instances[0].start_visible is True


def test_quit_without_instance_does_not_start_app(patched: FakeIpc) -> None:
    patched.result = False

    assert cli.main(["--quit"]) == 0

    assert patched.commands == ["quit"]
    assert FakeApp.instances == []


def test_background_is_mutually_exclusive(patched: FakeIpc) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--background", "--show"])
    assert patched.commands == []
