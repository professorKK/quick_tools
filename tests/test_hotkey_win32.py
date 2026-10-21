from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from quicktools.config import HotkeySpec

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Win32 virtual-key mapping"
)


def combo(spec: HotkeySpec) -> tuple[int, int]:
    from quicktools.win32_hotkey import to_win32_combo

    return to_win32_combo(spec)


def test_ctrl_space() -> None:
    assert combo(HotkeySpec(("ctrl",), "space")) == (0x0002, 0x20)


def test_ctrl_alt_f12() -> None:
    assert combo(HotkeySpec(("ctrl", "alt"), "f12")) == (0x0003, 0x7B)


def test_super_letter() -> None:
    assert combo(HotkeySpec(("super",), "q")) == (0x0008, ord("Q"))


def test_shift_special_key() -> None:
    assert combo(HotkeySpec(("shift",), "pageup")) == (0x0004, 0x21)


def test_last_function_key() -> None:
    assert combo(HotkeySpec(("ctrl",), "f20")) == (0x0002, 0x83)


def test_out_of_range_function_key_is_rejected() -> None:
    from quicktools.win32_hotkey import to_win32_combo

    with pytest.raises(ValueError):
        to_win32_combo(SimpleNamespace(modifiers=("ctrl",), key="f21"))
