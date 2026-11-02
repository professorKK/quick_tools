from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

if importlib.util.find_spec("PyQt6") is None:
    pytest.skip("PyQt6 is not installed", allow_module_level=True)

_CASE_SCRIPT = Path(__file__).with_name("qt_calculator_cases.py")
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_case(case: str) -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) + (os.pathsep + pythonpath if pythonpath else "")
    )
    result = subprocess.run(
        [sys.executable, str(_CASE_SCRIPT), case],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Qt calculator case {case!r} failed\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_qt_window_calculates_and_copies_full_expression() -> None:
    _run_case("calculate_and_copy")


def test_qt_window_restores_scratchpad_and_settings() -> None:
    _run_case("restore_scratchpad")


def test_qt_window_settings_trim_and_clear() -> None:
    _run_case("settings_trim_and_clear")


def test_qt_window_scientific_mode() -> None:
    _run_case("scientific_mode")


def test_qt_window_settings_dialog() -> None:
    _run_case("settings_dialog")


def test_qt_window_lifecycle() -> None:
    _run_case("window_lifecycle")


def test_qt_window_keypad_and_input_filter() -> None:
    _run_case("keypad_and_filter")


def test_qt_window_scrolls_to_new_row_and_selects_on_click() -> None:
    _run_case("scroll_and_selection")


def test_qt_helper_starts_and_reports_ready(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) + (os.pathsep + pythonpath if pythonpath else "")
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quicktools",
            "--calculator-qt-helper",
            "--data-dir",
            str(tmp_path),
        ],
        cwd=_REPO_ROOT,
        env=env,
        input="quit\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Qt helper failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ready" in result.stdout
