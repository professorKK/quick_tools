from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from quicktools.plugins.gp.host import helper_environment

if importlib.util.find_spec("PyQt6") is None:
    pytest.skip("PyQt6 is not installed", allow_module_level=True)

# 离屏平台不支持窗口透明度，gp 悬浮窗的用例需要真实显示环境。
pytestmark = pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
    reason="需要可用的显示环境（离屏平台不支持窗口透明度）",
)

_CASE_SCRIPT = Path(__file__).with_name("qt_gp_cases.py")
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_DIR = _REPO_ROOT / "quicktools" / "plugins" / "gp"


def _case_env() -> dict[str, str]:
    env = helper_environment()
    env.pop("QT_QPA_PLATFORM", None)
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) + (os.pathsep + pythonpath if pythonpath else "")
    )
    return env


def _run_case(case: str) -> None:
    result = subprocess.run(
        [sys.executable, str(_CASE_SCRIPT), case],
        cwd=_REPO_ROOT,
        env=_case_env(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, (
        f"gp 悬浮窗用例 {case!r} 失败\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_gp_widget_defaults() -> None:
    _run_case("defaults")


def test_gp_widget_transparent_background() -> None:
    _run_case("transparent_background")


def test_gp_widget_hover_opacity() -> None:
    _run_case("hover_opacity")


def test_gp_widget_commands() -> None:
    _run_case("commands")


def test_gp_widget_drag_requires_shift() -> None:
    _run_case("drag_requires_shift")


def test_gp_widget_drag_shift_released_midway() -> None:
    _run_case("drag_shift_released_midway")


def test_gp_widget_drag_clamps_and_saves() -> None:
    _run_case("drag_clamps_and_saves")


def test_gp_widget_position_persists_via_controller() -> None:
    _run_case("position_persists_via_controller")


def test_gp_widget_fallback_does_not_overwrite_saved_position() -> None:
    _run_case("fallback_does_not_overwrite_saved_position")


def test_gp_widget_drag_across_screens() -> None:
    _run_case("drag_across_screens")


def test_gp_widget_context_menu() -> None:
    _run_case("context_menu")


def test_gp_settings_dialog_single_instance_and_placement() -> None:
    _run_case("settings_dialog_single_instance_and_placement")


def test_gp_context_menu_keeps_hover_opacity() -> None:
    _run_case("context_menu_keeps_hover_opacity")


def test_gp_context_menu_exit_quits_helper() -> None:
    _run_case("context_menu_exit_quits_helper")


def test_gp_diameter_slider_sync() -> None:
    _run_case("diameter_slider_sync")


def test_gp_settings_dialog_stays_put_when_changed() -> None:
    _run_case("settings_dialog_stays_put_when_changed")


def test_gp_closing_settings_does_not_quit() -> None:
    _run_case("closing_settings_does_not_quit")


def test_gp_settings_dialog_flips_at_left_edge() -> None:
    _run_case("settings_dialog_flips_at_left_edge")


def test_gp_settings_dialog_auto_saves() -> None:
    _run_case("settings_dialog_auto_saves")


def test_gp_settings_dialog_reset_position() -> None:
    _run_case("settings_dialog_reset_position")


def test_gp_diameter_change_keeps_reachable() -> None:
    _run_case("diameter_change_keeps_reachable")


def test_gp_helper_ready_and_quit(tmp_path: Path) -> None:
    """Helper 必须输出 ready，并在 quit 命令后正常退出。"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "quicktools",
            "--gp-qt-helper",
            "--data-dir",
            str(tmp_path),
            "--plugin-dir",
            str(_PLUGIN_DIR),
        ],
        cwd=_REPO_ROOT,
        env=_case_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        ready = process.stdout.readline().strip()
        assert ready == "ready", (
            f"helper 未输出 ready：{ready!r}\n"
            f"stderr:\n{process.stderr.read() if process.stderr else ''}"
        )
        assert process.stdin is not None
        process.stdin.write("quit\n")
        process.stdin.flush()
        stdout_tail, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, (
            f"helper 退出码 {process.returncode}\n"
            f"stdout:\n{stdout_tail}\nstderr:\n{stderr}"
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
