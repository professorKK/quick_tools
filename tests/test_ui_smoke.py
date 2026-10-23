from __future__ import annotations

import os
import tkinter as tk

import pytest

from quicktools.plugins.calculator.view import CalculatorView

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="Tkinter UI smoke test needs a display"
)


@pytest.fixture()
def view():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    window = tk.Toplevel(root)
    window.withdraw()
    calculator = CalculatorView(window)
    calculator.pack(fill="both", expand=True)
    root.update_idletasks()
    yield calculator, root
    root.destroy()


@pytest.fixture()
def scientific_view(view):
    calculator, root = view
    calculator.set_scientific_mode(True)
    root.update_idletasks()
    return calculator, root


def test_default_viewport_is_four_rows(view) -> None:
    calculator, root = view
    assert calculator.canvas.cget("height") == str(calculator._row_height * 4)
    assert len(calculator.rows) == 1


def test_calculator_header_has_scratchpad_title_without_pin(view) -> None:
    calculator, root = view
    assert not hasattr(calculator, "pin_button")
    assert not hasattr(calculator, "scratchpad_button")
    assert calculator.scratchpad_title.cget("text") == "草稿纸"
    assert calculator.scratchpad_title.winfo_manager() == "pack"
    assert calculator.scientific_button.winfo_exists()


def test_shrinking_window_compacts_keypad_and_keeps_one_paper_row(view) -> None:
    calculator, root = view
    window = calculator.winfo_toplevel()
    window.deiconify()
    window.geometry("620x650")
    root.update()
    normal_key_height = calculator._digit_buttons["7"].winfo_height()
    assert calculator._keypad_compact is False

    # A plain Toplevel has no plugin frame, so its content minimum is also
    # the window minimum.  The paper shrinks to exactly one layer and the
    # keypad rows shrink instead of the bottom row being clipped.
    window.geometry(f"620x{calculator.minimum_content_height()}")
    root.update()
    calculator._sync_paper_layout()

    assert calculator.canvas.winfo_height() == pytest.approx(
        calculator._row_height, abs=2
    )
    compact_key_height = calculator._digit_buttons["7"].winfo_height()
    assert 0 < compact_key_height < normal_key_height
    keypad_bottom = (
        calculator._keypad.winfo_rooty()
        - calculator.winfo_rooty()
        + calculator._keypad.winfo_height()
    )
    assert keypad_bottom <= calculator.winfo_height() + 1
    assert calculator._keypad_compact is True
    operator = calculator.operator_buttons[0]
    assert operator.cget("image") == ""
    assert operator.cget("text")


def test_scientific_mode_raises_the_minimum_content_height(view) -> None:
    calculator, _root = view
    simple_min = calculator.minimum_content_height()
    calculator.set_scientific_mode(True)
    assert calculator.minimum_content_height() > simple_min


def test_current_row_sits_at_bottom_of_empty_paper(view) -> None:
    calculator, root = view
    window = calculator.winfo_toplevel()
    window.geometry("620x681")
    window.deiconify()
    root.update()
    calculator._sync_paper_layout()
    root.update_idletasks()
    offset = calculator.canvas.coords(calculator._canvas_window)[1]
    row_height = calculator.rows[0].winfo_reqheight()
    assert offset > 0
    assert offset + row_height == pytest.approx(calculator.canvas.winfo_height(), abs=1)


def test_evaluate_and_add_row(scientific_view) -> None:
    calculator, root = scientific_view
    entry = calculator.current_row.entry
    entry.insert(0, "1+1")
    calculator.evaluate_active()
    root.update()
    assert calculator.rows[0].result_label.cget("text") == "= 2"
    assert len(calculator.rows) == 2
    assert calculator.active_row is calculator.rows[1]
    assert calculator._conversion_vars[16].get() == "0x2"


def test_clicking_result_copies_it(view) -> None:
    calculator, root = view
    window = calculator.winfo_toplevel()
    window.deiconify()
    root.update()
    calculator.current_row.entry.insert(0, "1+1")
    calculator.evaluate_active()
    root.update()
    row = calculator.rows[0]
    row.result_label.event_generate("<Button-1>", x=2, y=2, when="now")
    root.update()
    assert root.clipboard_get() == "2"
    assert "已复制结果" in calculator.status_var.get()


def test_mouse_position_edit_recalculates_result(view) -> None:
    calculator, root = view
    entry = calculator.current_row.entry
    entry.insert(0, "12+34")
    calculator.evaluate_active()
    root.update()
    assert calculator.rows[0].result_value == 46
    # A mouse click in a native Entry moves INSERT; emulate that position.
    entry.icursor(2)
    entry.insert(tk.INSERT, "9")
    root.update()
    assert entry.get() == "129+34"
    assert calculator.rows[0].result_value == 163
    assert calculator.rows[0].result_label.cget("text") == "= 163"


def test_fullwidth_parentheses_normalized(view) -> None:
    calculator, root = view
    entry = calculator.current_row.entry
    entry.insert(0, "（1＋2）×3")
    root.update()
    assert entry.get() == "(1+2)*3"
    calculator.evaluate_active()
    root.update()
    assert calculator.rows[0].result_label.cget("text") == "= 9"


def test_hex_mode_and_conversions(scientific_view) -> None:
    calculator, root = scientific_view
    calculator.set_base(16)
    calculator.insert_text("FF")
    calculator.evaluate_active()
    root.update()
    assert calculator.rows[0].result_label.cget("text") == "= 0xFF"
    assert calculator._conversion_vars[10].get() == "255"
    assert calculator._conversion_vars[2].get() == "0b1111 1111"


def test_result_updates_while_typing(scientific_view) -> None:
    calculator, root = scientific_view
    entry = calculator.current_row.entry
    for ch in "1+2*":
        entry.insert(tk.INSERT, ch)
        root.update_idletasks()
    assert calculator.current_row.result_label.cget("text") == "= 3"
    assert calculator._conversion_vars[10].get() == "3"


def test_uncalculable_input_shows_no_result(scientific_view) -> None:
    calculator, root = scientific_view
    entry = calculator.current_row.entry
    entry.insert(0, "1^")
    root.update_idletasks()
    assert calculator.current_row.result_label.cget("text") == ""
    assert calculator._conversion_vars[10].get() == "—"


def test_hex_input_filters_invalid_chars_and_uses_hex(scientific_view) -> None:
    calculator, root = scientific_view
    calculator.set_base(16)
    calculator.current_row.entry.insert(0, "G11+11")
    root.update_idletasks()
    assert calculator.current_row.entry.get() == "11+11"
    assert calculator.current_row.result_label.cget("text") == "= 0x22"
    assert calculator._conversion_vars[10].get() == "34"


def test_binary_input_filters_non_binary_digits(scientific_view) -> None:
    calculator, root = scientific_view
    calculator.set_base(2)
    calculator.current_row.entry.insert(0, "102+1")
    root.update_idletasks()
    assert calculator.current_row.entry.get() == "10+1"
    assert calculator.current_row.result_label.cget("text") == "= 0b11"


def test_operators_form_left_column_in_plus_minus_multiply_divide_order(view) -> None:
    calculator, _root = view
    values = [button.operator_value for button in calculator.operator_buttons]
    assert values == ["+", "-", "*", "/"]
    for button in calculator.operator_buttons:
        assert int(button.grid_info()["column"]) == 0
        assert button.cget("image")
    assert int(calculator._digit_buttons["7"].grid_info()["column"]) == 1
    assert int(calculator._digit_buttons["0"].grid_info()["column"]) == 1


def test_number_keys_stay_white_and_operators_use_light_tints(view) -> None:
    calculator, _root = view
    assert calculator._digit_buttons["7"].cget("bg").lower() == "#ffffff"
    assert calculator._digit_buttons["0"].cget("bg").lower() == "#ffffff"
    assert [button.cget("bg").upper() for button in calculator.operator_buttons] == [
        "#FDECEA",
        "#FFF7E0",
        "#E6F4EA",
        "#E8F0FE",
    ]
    assert calculator.equal_button.cget("bg").upper() == "#D2E3FC"
    assert calculator.equal_button.cget("image")


def test_disabled_digits_follow_base(scientific_view) -> None:
    calculator, root = scientific_view
    calculator.set_base(2)
    assert calculator._digit_buttons["2"]._enabled is False
    assert calculator._digit_buttons["1"]._enabled is True
    assert calculator._digit_buttons["A"]._enabled is False
    calculator.set_base(16)
    assert calculator._digit_buttons["F"]._enabled is True


def test_error_does_not_add_row(view) -> None:
    calculator, root = view
    entry = calculator.current_row.entry
    entry.insert(0, "1/0")
    calculator.evaluate_active()
    root.update()
    assert len(calculator.rows) == 1
    assert calculator.rows[0].result_label.cget("text") == "错误"
    assert "零" in calculator.status_var.get()


def test_history_scrolls_beyond_four_rows(view) -> None:
    calculator, root = view
    for index in range(6):
        row = calculator.rows[-1]
        row.entry.insert(0, f"{index}+1")
        calculator.evaluate_row(row)
        root.update()
    root.update_idletasks()
    content = calculator.canvas.bbox("all")
    assert content is not None
    assert content[3] - content[1] > calculator._row_height * 4
    calculator.scroll_to_bottom()
    root.update()
    assert calculator.canvas.yview()[1] == pytest.approx(1.0, abs=0.01)


def test_editing_older_row_keeps_row_count(view) -> None:
    calculator, root = view
    first = calculator.current_row
    first.entry.insert(0, "2+2")
    calculator.evaluate_row(first)
    root.update()
    assert len(calculator.rows) == 2
    calculator.activate_row(first)
    first.entry.delete(0, tk.END)
    first.entry.insert(0, "3+3")
    calculator.evaluate_row(first)
    root.update()
    assert len(calculator.rows) == 2
    assert first.result_label.cget("text") == "= 6"


def test_stray_release_does_not_insert_operator(view) -> None:
    calculator, root = view
    # Opening the calculator from a launcher card happens on ButtonPress; the
    # later release must not press a keypad button in the new window.
    calculator._digit_buttons["+"]._on_release()
    root.update_idletasks()
    assert calculator.current_row.entry.get() == ""


def test_scientific_mode_defaults_to_simple(view) -> None:
    calculator, _root = view
    assert calculator.scientific_mode is False
    assert calculator.base == 10
    assert calculator._conversion_outer.winfo_manager() == ""
    assert calculator._base_row.winfo_manager() == ""
    assert calculator._hex_row.winfo_manager() == ""
    assert calculator.scientific_button.cget("text") == "科学模式：关"


def test_toggle_scientific_mode_restores_layout_order(scientific_view) -> None:
    calculator, root = scientific_view
    assert calculator.scientific_mode is True
    assert calculator.scientific_button.cget("text") == "科学模式：开"
    for widget, row in (
        (calculator._conversion_outer, 3),
        (calculator._base_row, 4),
        (calculator._hex_row, 1),
    ):
        assert widget.winfo_manager() == "grid"
        assert int(widget.grid_info()["row"]) == row

    calculator.set_base(16)
    calculator.set_scientific_mode(False)
    root.update_idletasks()
    assert calculator.scientific_mode is False
    assert calculator.base == 10
    assert calculator._digit_buttons["A"]._enabled is False
    for widget in (
        calculator._conversion_outer,
        calculator._base_row,
        calculator._hex_row,
    ):
        assert widget.winfo_manager() == ""

    calculator.set_scientific_mode(True)
    root.update_idletasks()
    assert int(calculator._conversion_outer.grid_info()["row"]) == 3
    assert int(calculator._base_row.grid_info()["row"]) == 4
    assert int(calculator._keypad.grid_info()["row"]) == 5
    assert int(calculator._hex_row.grid_info()["row"]) == 1


def test_scientific_mode_is_persisted(tmp_path) -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        first_window = tk.Toplevel(root)
        first_window.withdraw()
        first = CalculatorView(first_window, data_dir=tmp_path)
        first.pack(fill="both", expand=True)
        assert first.scientific_mode is False
        first.set_scientific_mode(True)
        root.update_idletasks()
        assert (tmp_path / "settings.json").is_file()

        second_window = tk.Toplevel(root)
        second_window.withdraw()
        second = CalculatorView(second_window, data_dir=tmp_path)
        second.pack(fill="both", expand=True)
        assert second.scientific_mode is True
        assert second.scientific_button.cget("text") == "科学模式：开"
    finally:
        root.destroy()
