"""Shared helpers for native modal dialogs in frameless windows."""

from __future__ import annotations

import logging
import tkinter as tk

log = logging.getLogger(__name__)


def _is_mapped(window: tk.Misc) -> bool:
    try:
        return bool(window.winfo_ismapped())
    except tk.TclError:
        return False


def _app_toplevels(root: tk.Misc) -> list[tk.Toplevel]:
    found: list[tk.Toplevel] = []

    def walk(widget: tk.Misc) -> None:
        try:
            children = widget.winfo_children()
        except tk.TclError:
            return
        for child in children:
            if isinstance(child, tk.Toplevel):
                found.append(child)
            walk(child)

    walk(root)
    return found


def _application_root(widget: tk.Misc) -> tk.Misc:
    try:
        root = widget._root()  # type: ignore[attr-defined]
        if root is not None:
            return root
    except Exception:
        pass
    top = widget.winfo_toplevel()
    return top.master if top.master is not None else top


def run_modal_dialog(owner: tk.Misc, action, **options):
    """Run a native modal dialog above frameless Tk windows on X11.

    Tk's native file/message dialogs are window-manager-managed windows. On
    X11 QuickTools plugin windows are override-redirect and are composited
    above them, so a dialog parented to one stays hidden while still grabbing
    input. Hide the visible QuickTools toplevels for the duration of the
    dialog and parent it to the hidden Tk root, then restore them and return
    focus to the owner.
    """
    top = owner.winfo_toplevel()
    try:
        windowing = str(top.tk.call("tk", "windowingsystem"))
    except tk.TclError:
        windowing = ""
    if windowing != "x11":
        return action(parent=top, **options)
    root = _application_root(top)
    try:
        had_grab = top.grab_current() is top
    except (tk.TclError, KeyError):
        had_grab = False
    hidden = [
        window for window in _app_toplevels(root) if _is_mapped(window)
    ]
    for window in hidden:
        try:
            window.withdraw()
        except tk.TclError:
            pass
    try:
        try:
            top.update_idletasks()
        except tk.TclError:
            pass
        return action(parent=root, **options)
    finally:
        for window in hidden:
            try:
                window.deiconify()
                window.lift()
            except tk.TclError:
                pass
        try:
            top.update_idletasks()
        except tk.TclError:
            pass
        if had_grab:
            try:
                top.grab_set()
            except tk.TclError:
                pass
        # Match the launcher's order: update Tk's focus model first, then
        # set native X11 input focus. Calling focus_force() after the raw
        # XSetInputFocus path can trip rare Tk/X11 focus races.
        try:
            if top.winfo_exists() and top.winfo_viewable():
                top.focus_force()
        except tk.TclError:
            pass
        try:
            from quicktools import x11_focus

            x11_focus.force_foreground(top)
        except Exception:
            log.debug(
                "原生对话框结束后恢复 X11 焦点失败", exc_info=True
            )


def open_native_file_dialog(owner: tk.Misc, opener, **options):
    """Open a native file dialog that is visible above frameless windows."""
    return run_modal_dialog(owner, opener, **options)
