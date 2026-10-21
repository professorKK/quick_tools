from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path

import pytest

from quicktools.plugins.calculator.scratchpad_store import (
    ScratchEntry,
    ScratchpadState,
    load_scratchpad,
    save_scratchpad,
)
from quicktools.plugins.calculator.settings import (
    load_max_records,
    load_result_group_size,
    load_scientific_mode,
    save_scientific_mode,
)
from quicktools.plugins.calculator.view import CalculatorView

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="Tkinter UI test needs a display"
)


@pytest.fixture()
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


def make_view(root: tk.Tk, data_dir: Path | None) -> tuple[tk.Toplevel, CalculatorView]:
    window = tk.Toplevel(root)
    window.withdraw()
    view = CalculatorView(window, data_dir=data_dir)
    view.pack(fill="both", expand=True)
    return window, view


def add_record(view: CalculatorView, expression: str) -> None:
    view.current_row.entry.insert(0, expression)
    view.evaluate_active()


def test_no_data_dir_starts_with_one_empty_row(root: tk.Tk) -> None:
    window, view = make_view(root, None)
    try:
        assert len(view.rows) == 1
        assert view.rows[0].entry.get() == ""
        assert view.scratchpad_record_count() == 0
        view._request_scratchpad_save(immediate=True)
    finally:
        window.destroy()


def test_restore_rows_results_and_last_base(
    root: tk.Tk, tmp_path: Path
) -> None:
    save_scratchpad(
        tmp_path,
        ScratchpadState(
            (
                ScratchEntry("1+1", 10),
                ScratchEntry("FF+1", 16),
            ),
            last_base=16,
        ),
        max_records=200,
    )
    save_scientific_mode(tmp_path, True)

    window, view = make_view(root, tmp_path)
    try:
        assert view.scientific_mode is True
        assert view.base == 16
        assert len(view.rows) == 3
        assert [row.entry.get() for row in view.rows] == ["1+1", "FF+1", ""]
        assert view.rows[0].result_label.cget("text") == "= 2"
        assert view.rows[0].entry_base == 10
        assert view.rows[1].result_label.cget("text") == "= 0x100"
        assert view.rows[1].entry_base == 16
        assert view.active_row is view.rows[-1]
        assert view.rows[-1].entry.get() == ""
    finally:
        window.destroy()


def test_restore_forces_decimal_when_scientific_mode_is_off(
    root: tk.Tk, tmp_path: Path
) -> None:
    save_scratchpad(
        tmp_path,
        ScratchpadState((ScratchEntry("FF+1", 16),), last_base=16),
        max_records=200,
    )

    window, view = make_view(root, tmp_path)
    try:
        assert view.scientific_mode is False
        assert view.base == 10
        assert len(view.rows) == 2
        assert view.rows[0].entry.get() == "FF+1"
        assert view.rows[0].result_label.cget("text") == "= 0x100"
    finally:
        window.destroy()


def test_unconfirmed_input_is_flushed(root: tk.Tk, tmp_path: Path) -> None:
    window, view = make_view(root, tmp_path)
    try:
        view.current_row.entry.insert(0, "1+2")
        view._flush_scratchpad()
        assert load_scratchpad(tmp_path, max_records=200).entries == (
            ScratchEntry("1+2", 10),
        )
    finally:
        window.destroy()


def test_destroy_flushes_pending_input(root: tk.Tk, tmp_path: Path) -> None:
    window, view = make_view(root, tmp_path)
    view.current_row.entry.insert(0, "3+4")
    window.destroy()
    root.update_idletasks()
    state = load_scratchpad(tmp_path, max_records=200)
    assert state.entries == (ScratchEntry("3+4", 10),)


def test_delete_row_reflows_focus_and_persists(
    root: tk.Tk, tmp_path: Path
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        add_record(view, "1+1")
        add_record(view, "2+2")
        assert view.scratchpad_record_count() == 2
        assert view.rows[0].delete_button.cget("text") == "×"

        view.rows[0].delete_button._on_click()
        view.rows[0].delete_button._on_release()
        root.update_idletasks()

        assert [row.entry.get() for row in view.rows] == ["2+2", ""]
        # Deleting a non-active row must not steal the caret from the active row.
        assert view.active_row is view.rows[-1]
        assert load_scratchpad(tmp_path, max_records=200).entries == (
            ScratchEntry("2+2", 10),
        )

        view.delete_row(view.rows[0])
        root.update_idletasks()
        assert len(view.rows) == 1
        assert view.rows[0].entry.get() == ""
        assert load_scratchpad(tmp_path, max_records=200).entries == ()
    finally:
        window.destroy()


def test_delete_active_row_activates_neighbor(
    root: tk.Tk, tmp_path: Path
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        add_record(view, "1+1")
        add_record(view, "2+2")
        view.activate_row(view.rows[0])
        view.delete_row(view.rows[0])
        root.update_idletasks()
        assert [row.entry.get() for row in view.rows] == ["2+2", ""]
        assert view.active_row is view.rows[0]
        assert load_scratchpad(tmp_path, max_records=200).entries == (
            ScratchEntry("2+2", 10),
        )
    finally:
        window.destroy()


def test_apply_max_records_trims_oldest(root: tk.Tk, tmp_path: Path) -> None:
    window, view = make_view(root, tmp_path)
    try:
        for expression in ("1+1", "2+2", "3+3", "4+4"):
            add_record(view, expression)
        assert view.scratchpad_record_count() == 4

        removed = view.apply_max_records(2)
        root.update_idletasks()

        assert removed == 2
        assert load_max_records(tmp_path) == 2
        assert [row.entry.get() for row in view.rows] == ["3+3", "4+4", ""]
        assert load_scratchpad(tmp_path, max_records=2).entries == (
            ScratchEntry("3+3", 10),
            ScratchEntry("4+4", 10),
        )
        assert view.active_row is view.rows[-1]
    finally:
        window.destroy()


def test_clear_scratchpad_leaves_one_empty_row(
    root: tk.Tk, tmp_path: Path
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        add_record(view, "1+1")
        add_record(view, "2+2")
        assert view.clear_scratchpad() == 2
        root.update_idletasks()
        assert len(view.rows) == 1
        assert view.rows[0].entry.get() == ""
        assert view.scratchpad_record_count() == 0
        assert load_scratchpad(tmp_path, max_records=200).entries == ()
    finally:
        window.destroy()


def test_header_button_opens_and_reuses_settings_dialog(
    root: tk.Tk, tmp_path: Path
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        assert view.scratchpad_button.cget("text") == "计算器 · 设置"
        view.open_settings()
        dialog = view._settings_window
        assert dialog is not None
        view.open_settings()
        assert view._settings_window is dialog
        dialog.close()
        root.update_idletasks()
        assert view._settings_window is None
    finally:
        window.destroy()


def test_result_grouping_updates_labels_and_persists(
    root: tk.Tk, tmp_path: Path
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        assert view.result_group_size == 0
        add_record(view, "1000")
        row = view.rows[0]
        assert row.result_label.cget("text") == "= 1000"

        assert view.apply_result_group_size(3) == 3
        assert row.result_label.cget("text") == "= 1,000"
        assert load_result_group_size(tmp_path) == 3

        add_record(view, "1234.5")
        second = view.rows[1]
        assert second.result_label.cget("text") == "= 1,234.5"

        view.apply_result_group_size(0)
        assert row.result_label.cget("text") == "= 1000"
        assert second.result_label.cget("text") == "= 1234.5"
    finally:
        window.destroy()


def test_settings_dialog_saves_result_group_size(
    root: tk.Tk, tmp_path: Path
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        view.open_settings()
        dialog = view._settings_window
        assert dialog is not None

        dialog.group_var.set("3")
        dialog._save()
        root.update_idletasks()

        assert view.result_group_size == 3
        assert load_result_group_size(tmp_path) == 3
        assert view._settings_window is None
    finally:
        window.destroy()


def test_settings_dialog_rejects_invalid_group_size(
    root: tk.Tk, tmp_path: Path, monkeypatch
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        view.open_settings()
        dialog = view._settings_window
        assert dialog is not None
        errors: list[str] = []
        monkeypatch.setattr(
            "quicktools.plugins.calculator.settings_view.messagebox.showerror",
            lambda title, message, **kwargs: errors.append(message),
        )
        dialog.group_var.set("11")
        dialog._save()
        assert errors
        assert view._settings_window is dialog
        assert view.result_group_size == 0
        dialog.close()
    finally:
        window.destroy()


def test_settings_dialog_saves_max_and_clears(
    root: tk.Tk, tmp_path: Path, monkeypatch
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        add_record(view, "1+1")
        add_record(view, "2+2")
        view.open_settings()
        dialog = view._settings_window
        assert dialog is not None

        dialog.max_var.set("1")
        dialog._save()
        root.update_idletasks()
        assert view.max_records == 1
        assert load_max_records(tmp_path) == 1

        view.open_settings()
        dialog = view._settings_window
        assert dialog is not None
        monkeypatch.setattr(
            "quicktools.plugins.calculator.settings_view.messagebox.askyesno",
            lambda *args, **kwargs: True,
        )
        dialog._clear_all()
        assert view.scratchpad_record_count() == 0
        dialog.close()
    finally:
        window.destroy()


def test_settings_dialog_rejects_invalid_max(
    root: tk.Tk, tmp_path: Path, monkeypatch
) -> None:
    window, view = make_view(root, tmp_path)
    try:
        view.open_settings()
        dialog = view._settings_window
        assert dialog is not None
        errors: list[str] = []
        monkeypatch.setattr(
            "quicktools.plugins.calculator.settings_view.messagebox.showerror",
            lambda title, message, **kwargs: errors.append(message),
        )
        dialog.max_var.set("0")
        dialog._save()
        assert errors
        assert view._settings_window is dialog
        dialog.close()
    finally:
        window.destroy()
