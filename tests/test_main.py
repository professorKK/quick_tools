from __future__ import annotations

import argparse
import os
import queue
from typing import ClassVar

import pytest

from quicktools import __main__ as cli


class FakeApp:
    instances: ClassVar[list[FakeApp]] = []

    def __init__(
        self,
        start_visible: bool = True,
        *,
        start_auto_hide: bool = False,
    ) -> None:
        self.start_visible = start_visible
        self.start_auto_hide = start_auto_hide
        self.ran = False
        self.commands: queue.Queue[str] = queue.Queue()
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
    # Keep detach detection deterministic: source build without a TTY.
    monkeypatch.setattr(cli, "_is_linux", lambda: True)
    monkeypatch.setattr(cli, "_is_frozen", lambda: False)
    monkeypatch.setattr(cli, "_has_terminal", lambda: False)
    monkeypatch.delenv(cli._DETACH_ENV, raising=False)
    return ipc


@pytest.fixture()
def detached(
    monkeypatch: pytest.MonkeyPatch, patched: FakeIpc
) -> list[list[str]]:
    spawned: list[list[str]] = []
    monkeypatch.setattr(cli, "_is_frozen", lambda: True)
    monkeypatch.setattr(cli, "_has_terminal", lambda: True)

    def fake_spawn(argv: list[str]) -> bool:
        spawned.append(list(argv))
        return True

    monkeypatch.setattr(cli, "_spawn_detached", fake_spawn)
    return spawned


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
    assert FakeApp.instances[0].start_auto_hide is False
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
    assert FakeApp.instances[0].start_auto_hide is True


def test_show_starts_visible_without_auto_hide(patched: FakeIpc) -> None:
    patched.result = False

    assert cli.main(["--show"]) == 0

    assert patched.commands == ["show"]
    assert FakeApp.instances[0].start_visible is True
    assert FakeApp.instances[0].start_auto_hide is False


def test_quit_without_instance_does_not_start_app(patched: FakeIpc) -> None:
    patched.result = False

    assert cli.main(["--quit"]) == 0

    assert patched.commands == ["quit"]
    assert FakeApp.instances == []


def test_background_is_mutually_exclusive(patched: FakeIpc) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--background", "--show"])
    assert patched.commands == []


@pytest.mark.parametrize(
    ("mode", "action"),
    [
        ("region", "capture_region"),
        ("window", "capture_window"),
        ("freeform", "capture_freeform"),
        ("scroll", "capture_scroll"),
        ("open", "open"),
    ],
)
def test_screenshot_maps_mode_to_plugin_action(
    patched: FakeIpc, mode: str, action: str
) -> None:
    patched.result = True

    argv = ["--screenshot", mode]
    assert cli.main(argv) == 0

    assert patched.commands == [f"plugin screenshot {action}"]
    assert FakeApp.instances == []


def test_screenshot_defaults_to_region(patched: FakeIpc) -> None:
    patched.result = True

    assert cli.main(["--screenshot"]) == 0

    assert patched.commands == ["plugin screenshot capture_region"]


def test_screenshot_starts_hidden_and_enqueues_without_instance(
    patched: FakeIpc,
) -> None:
    patched.result = False

    assert cli.main(["--screenshot", "region"]) == 0

    assert patched.commands == ["plugin screenshot capture_region"]
    assert len(FakeApp.instances) == 1
    app = FakeApp.instances[0]
    assert app.start_visible is False
    assert app.start_auto_hide is False
    assert app.ran
    assert app.commands.get_nowait() == "plugin screenshot capture_region"


def test_screenshot_is_mutually_exclusive(patched: FakeIpc) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--screenshot", "--show"])
    assert patched.commands == []


# ------------------------------------------------------- terminal detachment
def test_packaged_terminal_launch_detaches(
    patched: FakeIpc, detached: list[list[str]]
) -> None:
    patched.result = False

    assert cli.main([]) == 0

    assert patched.commands == ["show"]
    assert detached == [[]]
    assert FakeApp.instances == []


def test_background_detaches(
    patched: FakeIpc, detached: list[list[str]]
) -> None:
    patched.result = False

    assert cli.main(["--background"]) == 0

    assert patched.commands == ["ping"]
    assert detached == [["--background"]]
    assert FakeApp.instances == []


def test_toggle_detaches_and_forwards_args(
    patched: FakeIpc, detached: list[list[str]]
) -> None:
    patched.result = False

    assert cli.main(["--toggle"]) == 0

    assert patched.commands == ["toggle"]
    assert detached == [["--toggle"]]
    assert FakeApp.instances == []


def test_toggle_starts_hidden_and_enqueues_without_instance(
    patched: FakeIpc,
) -> None:
    patched.result = False

    assert cli.main(["--toggle"]) == 0

    assert patched.commands == ["toggle"]
    assert len(FakeApp.instances) == 1
    app = FakeApp.instances[0]
    assert app.start_visible is False
    assert app.start_auto_hide is False
    assert app.ran
    assert app.commands.get_nowait() == "toggle"


def test_quit_never_detaches(
    patched: FakeIpc, detached: list[list[str]]
) -> None:
    patched.result = False

    assert cli.main(["--quit"]) == 0

    assert patched.commands == ["quit"]
    assert detached == []
    assert FakeApp.instances == []


def test_foreground_never_detaches(
    patched: FakeIpc, detached: list[list[str]]
) -> None:
    patched.result = False

    assert cli.main(["--foreground"]) == 0

    assert detached == []
    assert FakeApp.instances[0].start_visible is True
    assert FakeApp.instances[0].start_auto_hide is True
    assert FakeApp.instances[0].ran


def test_source_mode_never_detaches(
    monkeypatch: pytest.MonkeyPatch, patched: FakeIpc
) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(cli, "_is_frozen", lambda: False)
    monkeypatch.setattr(cli, "_has_terminal", lambda: True)
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv: spawned.append(argv) or True
    )
    patched.result = False

    assert cli.main([]) == 0

    assert spawned == []
    assert FakeApp.instances[0].start_visible is True
    assert FakeApp.instances[0].start_auto_hide is True


def test_no_terminal_never_detaches(
    monkeypatch: pytest.MonkeyPatch, patched: FakeIpc
) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(cli, "_is_frozen", lambda: True)
    monkeypatch.setattr(cli, "_has_terminal", lambda: False)
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv: spawned.append(argv) or True
    )
    patched.result = False

    assert cli.main([]) == 0

    assert spawned == []
    assert FakeApp.instances[0].start_visible is True
    assert FakeApp.instances[0].start_auto_hide is True


def test_env_guard_prevents_recursion(
    monkeypatch: pytest.MonkeyPatch, patched: FakeIpc
) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(cli, "_is_frozen", lambda: True)
    monkeypatch.setattr(cli, "_has_terminal", lambda: True)
    monkeypatch.setenv(cli._DETACH_ENV, cli._DETACH_VALUE)
    monkeypatch.setattr(
        cli, "_spawn_detached", lambda argv: spawned.append(argv) or True
    )
    patched.result = False

    assert cli.main([]) == 0

    assert spawned == []
    assert FakeApp.instances[0].start_visible is True
    assert FakeApp.instances[0].start_auto_hide is True


def test_detach_spawn_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    patched: FakeIpc,
    detached: list[list[str]],
) -> None:
    monkeypatch.setattr(cli, "_spawn_detached", lambda argv: False)
    patched.result = False

    assert cli.main([]) == 1

    assert FakeApp.instances == []


def test_argv_none_forwards_sys_argv(
    monkeypatch: pytest.MonkeyPatch,
    patched: FakeIpc,
    detached: list[list[str]],
) -> None:
    monkeypatch.setattr(cli.sys, "argv", ["/opt/QuickTools/QuickTools", "--show"])
    patched.result = False

    assert cli.main() == 0

    assert detached == [["--show"]]


def test_should_detach_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_is_linux", lambda: True)
    monkeypatch.setattr(cli, "_is_frozen", lambda: True)
    monkeypatch.setattr(cli, "_has_terminal", lambda: True)
    monkeypatch.delenv(cli._DETACH_ENV, raising=False)

    def args(**overrides: bool) -> argparse.Namespace:
        values = {"foreground": False, "tray_helper": False, "quit": False}
        values.update(overrides)
        return argparse.Namespace(**values)

    assert cli._should_detach(args()) is True
    assert cli._should_detach(args(foreground=True)) is False
    assert cli._should_detach(args(tray_helper=True)) is False
    assert cli._should_detach(args(quit=True)) is False

    monkeypatch.setenv(cli._DETACH_ENV, cli._DETACH_VALUE)
    assert cli._should_detach(args()) is False


def test_detach_command_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_is_frozen", lambda: True)
    monkeypatch.setattr(cli.sys, "executable", "/opt/QuickTools/QuickTools")

    assert cli._detach_command(["--show"]) == [
        "/opt/QuickTools/QuickTools",
        "--show",
    ]


def test_detach_command_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_is_frozen", lambda: False)
    monkeypatch.setattr(cli.sys, "executable", "/usr/bin/python3")

    assert cli._detach_command([]) == [
        "/usr/bin/python3",
        "-m",
        "quicktools",
    ]


def test_spawn_detached_popen_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeProcess:
        pid = 4321

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        calls["command"] = command
        calls["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(cli, "_is_frozen", lambda: True)
    monkeypatch.setattr(cli.sys, "executable", "/opt/QuickTools/QuickTools")
    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.delenv(cli._DETACH_ENV, raising=False)

    assert cli._spawn_detached(["--background"]) is True

    assert calls["command"] == [
        "/opt/QuickTools/QuickTools",
        "--background",
    ]
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["stdin"] is cli.subprocess.DEVNULL
    assert kwargs["stdout"] is cli.subprocess.DEVNULL
    assert kwargs["stderr"] is cli.subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    assert kwargs["start_new_session"] is True
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env[cli._DETACH_ENV] == cli._DETACH_VALUE
    assert os.environ.get(cli._DETACH_ENV) is None


def test_spawn_detached_handles_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_popen(*args: object, **kwargs: object) -> None:
        raise OSError("boom")

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    assert cli._spawn_detached([]) is False


class _FakeStream:
    def __init__(self, result: object) -> None:
        self._result = result

    def isatty(self) -> bool:
        if isinstance(self._result, BaseException):
            raise self._result
        return bool(self._result)


def test_stream_is_tty_edge_cases() -> None:
    assert cli._stream_is_tty(_FakeStream(True)) is True
    assert cli._stream_is_tty(_FakeStream(False)) is False
    assert cli._stream_is_tty(None) is False
    assert cli._stream_is_tty(object()) is False
    assert cli._stream_is_tty(_FakeStream(ValueError("closed"))) is False
