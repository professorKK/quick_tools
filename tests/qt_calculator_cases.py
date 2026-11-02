"""Qt calculator scenarios run in an isolated child process.

Creating a QApplication in the pytest process changes fontconfig's current
configuration, which hides the bundled Material Icons font from Tk.  The
production app runs Tk and Qt in separate processes, so the tests do too:
``test_calculator_qt_window.py`` starts this file with a case name.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from quicktools.plugins.calculator.qt_window import CalculatorWindow
from quicktools.plugins.calculator.settings import (
    load_max_records,
    load_result_group_size,
    load_scientific_mode,
)

_app = QApplication([])


def _process() -> None:
    _app.processEvents()


def _new_window() -> tuple[CalculatorWindow, Path]:
    data_dir = Path(tempfile.mkdtemp(prefix="quicktools-qt-calc-"))
    return CalculatorWindow(data_dir), data_dir


def _type(window: CalculatorWindow, expression: str) -> None:
    window.active_row.entry.setText(expression)
    _process()


def case_calculate_and_copy() -> None:
    window, _data_dir = _new_window()
    try:
        _type(window, "10000*1%")
        row = window.active_row
        assert row.result_label.text() == "= 100", row.result_label.text()
        window.evaluate_active()
        _process()
        assert window.rows[0].full_expression_text() == "10000*1%=100"
        QApplication.clipboard().setText("")
        window.rows[0]._copy_full_expression()
        assert QApplication.clipboard().text() == "10000*1%=100"
        assert window.status_label.property("tone") == "success"
    finally:
        window.close()


def case_restore_scratchpad() -> None:
    window, data_dir = _new_window()
    try:
        _type(window, "1+1")
        window.evaluate_active()
        window.set_scientific_mode(True)
        window.set_base(16)
        _type(window, "0xFF+1")
        window.evaluate_active()
        window.flush_scratchpad()
        window.close()

        restored = CalculatorWindow(data_dir)
        try:
            assert load_scientific_mode(data_dir) is True
            assert restored.scientific_mode is True
            assert [row.expression for row in restored.rows] == [
                "1+1",
                "0xFF+1",
                "",
            ]
            assert restored.rows[0].result_label.text() == "= 2"
            assert restored.rows[1].result_label.text() == "= 0x100"
        finally:
            restored.close()
    finally:
        if window.isVisible():
            window.close()


def case_settings_trim_and_clear() -> None:
    window, data_dir = _new_window()
    try:
        _type(window, "1+1")
        window.evaluate_active()
        _type(window, "2+2")
        window.evaluate_active()
        window.flush_scratchpad()

        assert window.apply_max_records(1) == 1
        assert [row.expression for row in window.rows] == ["2+2", ""]
        assert load_max_records(data_dir) == 1

        assert window.apply_result_group_size(3) == 3
        assert load_result_group_size(data_dir) == 3
        assert window.clear_scratchpad() == 1
        assert [row.expression for row in window.rows] == [""]
    finally:
        window.close()


def case_scientific_mode() -> None:
    window, _data_dir = _new_window()
    try:
        assert window.scientific_mode is False
        assert window.conversion_panel.isHidden()
        assert window.base_row.isHidden()
        assert window.hex_row.isHidden()
        window.set_scientific_mode(True)
        assert not window.conversion_panel.isHidden()
        assert not window.base_row.isHidden()
        assert not window.hex_row.isHidden()
        window.set_base(16)
        assert window.base == 16
        assert window.base_buttons[16].isChecked()
        window.set_scientific_mode(False)
        assert window.base == 10
    finally:
        window.close()


def case_settings_dialog() -> None:
    from quicktools.plugins.calculator.qt_window import SettingsDialog

    window, data_dir = _new_window()
    try:
        dialog = SettingsDialog(window)
        dialog.max_records_spin.setValue(3)
        dialog.group_size_spin.setValue(3)
        dialog._save()
        assert load_max_records(data_dir) == 3
        assert load_result_group_size(data_dir) == 3
    finally:
        window.close()


def case_window_lifecycle() -> None:
    from PyQt6.QtTest import QTest

    window, _data_dir = _new_window()
    try:
        window.show_initial()
        QTest.qWait(120)
        assert window.isVisible()
        window.pin_button.setChecked(True)
        window.toggle_pin()
        assert window._pinned is True
        assert "已置顶" in window.status_label.text()
        window.pin_button.setChecked(False)
        window.toggle_pin()
        assert window._pinned is False
        assert "已取消置顶" in window.status_label.text()
        window.hide_window()
        assert not window.isVisible()
        window.request_show()
        QTest.qWait(150)
        assert window.isVisible()
        window.toggle_maximize()
        QTest.qWait(80)
        assert window.isMaximized()
        window.toggle_maximize()
        QTest.qWait(80)
        assert not window.isMaximized()
    finally:
        window.close()


def case_keypad_and_filter() -> None:
    window, _data_dir = _new_window()
    try:
        window.insert_text("1+2")
        assert window.active_row.expression == "1+2"
        window.backspace()
        assert window.active_row.expression == "1+"
        window.clear_active()
        assert window.active_row.expression == ""
        window.set_scientific_mode(True)
        window.set_base(16)
        window.insert_text("1G")
        assert window.active_row.expression == "1"
        window.insert_text("A")
        assert window.active_row.expression == "1A"
        # Editing in BIN drops the previously typed hex digits.
        window.set_base(2)
        window.insert_text("2")
        assert window.active_row.expression == "1"
        window.set_base(10)
        assert window.active_row.expression == "1"
    finally:
        window.close()


def case_scroll_and_selection() -> None:
    from PyQt6.QtTest import QTest

    window, _data_dir = _new_window()
    try:
        window.resize(660, 500)
        window.show_initial()
        QTest.qWait(120)
        # The first-visible current input row is the active/selected row.
        assert window.active_row is window.rows[-1]
        assert window.rows[-1].active
        assert all(not row.active for row in window.rows[:-1])

        for index in range(8):
            window.active_row.entry.setText(f"{index}+1")
            window.evaluate_active()
        QTest.qWait(150)
        window.active_row.entry.setText("1+1")
        window.evaluate_active()
        QTest.qWait(300)
        bar = window.paper_scroll.verticalScrollBar()
        assert bar.value() == bar.maximum()
        assert window.rows[-1].isVisible()
        # Only the new current row is highlighted; history rows are white.
        assert window.rows[-1].active
        assert all(not row.active for row in window.rows[:-1])

        target = window.rows[0]
        target.entry.clicked.emit()
        assert window.active_row is target
        assert [row.active for row in window.rows] == [
            True,
        ] + [False] * (len(window.rows) - 1)

        window.begin_new_entry()
        assert window.active_row is window.rows[-1]
        assert window.rows[-1].active
        assert all(not row.active for row in window.rows[:-1])
    finally:
        window.close()


_CASES = {
    "calculate_and_copy": case_calculate_and_copy,
    "restore_scratchpad": case_restore_scratchpad,
    "settings_trim_and_clear": case_settings_trim_and_clear,
    "scientific_mode": case_scientific_mode,
    "settings_dialog": case_settings_dialog,
    "window_lifecycle": case_window_lifecycle,
    "keypad_and_filter": case_keypad_and_filter,
    "scroll_and_selection": case_scroll_and_selection,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _CASES:
        print(f"unknown case: {argv}", file=sys.stderr)
        return 2
    try:
        _CASES[argv[0]]()
    except Exception:
        traceback.print_exc()
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
