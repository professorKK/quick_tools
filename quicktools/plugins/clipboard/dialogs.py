"""Clipboard modal dialog wrappers built on the shared X11 helper."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from quicktools.modal_dialogs import run_modal_dialog


def show_error(owner: tk.Misc, title: str, message: str) -> None:
    run_modal_dialog(
        owner,
        lambda **kwargs: messagebox.showerror(title, message, **kwargs),
    )


def ask_yes_no(owner: tk.Misc, title: str, message: str) -> bool:
    return bool(
        run_modal_dialog(
            owner,
            lambda **kwargs: messagebox.askyesno(title, message, **kwargs),
        )
    )
