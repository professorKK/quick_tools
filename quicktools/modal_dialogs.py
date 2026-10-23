"""Shared helpers for modal dialogs in frameless windows.

On X11, window-manager-managed dialogs (including Tk's own ``tk_messageBox``
and ``tk_getOpenFile``) are composited *below* override-redirect QuickTools
windows. Historically we hid every visible window for the duration of the
dialog, which made the background flash away. Instead we now turn Tk's dialogs
into override-redirect windows before they are mapped and give them native X11
input focus; they then stack above the visible app windows without hiding
anything.
"""

from __future__ import annotations

import logging
import tkinter as tk

log = logging.getLogger(__name__)

_DIALOG_NAMES = ("__tk__messagebox", "__tk_filedialog")
_POLL_INTERVAL_MS = 120

_overlay_state: dict = {
    "root": None,
    "job": None,
    "active": set(),
    "seen": set(),
    "focused": set(),
    "saved_focus": None,
}


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


def _windowing_system(widget: tk.Misc) -> str:
    try:
        return str(widget.tk.call("tk", "windowingsystem"))
    except tk.TclError:
        return ""


def _install_overlay_hook(root: tk.Misc) -> None:
    """Make Tk's built-in dialogs override-redirect before they are mapped."""
    root.tk.eval(
        """
if {![info exists ::quicktools_overlay_hook]} {
    set ::quicktools_overlay_hook 1
    rename ::tk::PlaceWindow ::quicktools_place_window_original
    proc ::tk::PlaceWindow {w args} {
        if {[string match "*.__tk__messagebox" $w] ||
                [string match "*.__tk_filedialog" $w]} {
            catch {wm overrideredirect $w 1}
        }
        ::quicktools_place_window_original $w {*}$args
    }
}
"""
    )


def _dialog_paths(root: tk.Misc) -> list[str]:
    """Return Tcl paths of visible Tk message/file dialogs."""
    parents = [str(root)]
    for window in _app_toplevels(root):
        try:
            if window.winfo_exists():
                parents.append(str(window))
        except tk.TclError:
            continue
    paths: list[str] = []
    for parent in parents:
        try:
            children = root.tk.call("winfo", "children", parent)
        except tk.TclError:
            continue
        for child in children:
            path = str(child)
            if path.rsplit(".", 1)[-1] not in _DIALOG_NAMES:
                continue
            paths.append(path)
            # Tk's save-file dialog can open a nested overwrite messagebox
            # whose parent is the dialog itself, not a Python Toplevel.
            try:
                nested = root.tk.call("winfo", "children", path)
            except tk.TclError:
                continue
            for child in nested:
                nested_path = str(child)
                if nested_path.rsplit(".", 1)[-1] in _DIALOG_NAMES:
                    paths.append(nested_path)
    return paths


def _poll_overlay_dialogs() -> None:
    state = _overlay_state
    root = state["root"]
    if root is None:
        return
    try:
        if not root.winfo_exists():
            return
    except tk.TclError:
        return

    active: set[str] = set()
    dialog_ids: dict[str, int] = {}
    try:
        for path in _dialog_paths(root):
            try:
                if not int(root.tk.call("winfo", "ismapped", path)):
                    continue
                dialog_ids[path] = int(
                    root.tk.call("winfo", "id", path), 0
                )
            except (tk.TclError, ValueError):
                continue
            active.add(path)
    except tk.TclError:
        pass

    # The dialog has just appeared and no native focus was forced yet, so the
    # current focus still belongs to the window that should get it back.
    if active and not state["active"] and state["saved_focus"] is None:
        try:
            from quicktools import x11_focus

            state["saved_focus"] = x11_focus.input_focus_id()
        except Exception:
            state["saved_focus"] = None

    for path in active:
        if path in state["seen"] and path in state["focused"]:
            continue
        try:
            if path not in state["seen"]:
                state["seen"].add(path)
                root.tk.call("raise", path)
            if path in state["focused"]:
                continue
            from quicktools import x11_focus

            if x11_focus.force_foreground_id(dialog_ids[path]):
                state["focused"].add(path)
        except Exception:
            log.debug("X11 对话框聚焦失败：%s", path, exc_info=True)

    if not active and state["active"]:
        saved = state["saved_focus"]
        state["saved_focus"] = None
        if saved is not None:
            try:
                from quicktools import x11_focus

                x11_focus.force_foreground_id(saved)
            except Exception:
                log.debug("对话框关闭后恢复 X11 焦点失败", exc_info=True)
    elif active:
        state["focused"].intersection_update(active)
        state["seen"].intersection_update(active)
    else:
        state["focused"].clear()
        state["seen"].clear()

    state["active"] = active
    try:
        state["job"] = root.after(_POLL_INTERVAL_MS, _poll_overlay_dialogs)
    except tk.TclError:
        state["job"] = None


def install_overlay_dialogs(root: tk.Misc) -> bool:
    """Enable stacked Tk dialogs on X11.

    Installs the Tcl ``PlaceWindow`` hook once and keeps a small poller that
    forces native X11 focus onto Tk's message/file dialogs. Returns True when
    the overlay mode is available; callers can then skip hiding windows.
    """
    if _windowing_system(root) != "x11":
        return False
    try:
        from quicktools import x11_focus

        if not x11_focus.supported():
            return False
    except Exception:
        return False
    state = _overlay_state
    if state["root"] is root and state["job"] is not None:
        return True
    if state["root"] is not None and state["job"] is not None:
        try:
            state["root"].after_cancel(state["job"])
        except Exception:
            pass
    _install_overlay_hook(root)
    state["root"] = root
    state["active"] = set()
    state["seen"] = set()
    state["focused"] = set()
    state["saved_focus"] = None
    try:
        state["job"] = root.after(_POLL_INTERVAL_MS, _poll_overlay_dialogs)
    except tk.TclError:
        state["job"] = None
    return state["job"] is not None


def _forget_saved_focus() -> None:
    """Do not let the poller override an explicit owner-focus restore."""
    state = _overlay_state
    state["saved_focus"] = None
    state["active"] = set()
    state["seen"].clear()
    state["focused"].clear()


def _restore_owner_focus(top: tk.Misc) -> None:
    # Match the launcher's order: update Tk's focus model first, then set
    # native X11 input focus.
    try:
        if top.winfo_exists() and top.winfo_viewable():
            top.focus_force()
    except tk.TclError:
        pass
    try:
        from quicktools import x11_focus

        x11_focus.force_foreground(top)
    except Exception:
        log.debug("原生对话框结束后恢复 X11 焦点失败", exc_info=True)


def run_modal_dialog(owner: tk.Misc, action, **options):
    """Run a modal dialog above frameless Tk windows.

    On X11 the dialog is made override-redirect and stacked above the still
    visible app windows. On platforms where that is not available (for example
    Wayland), fall back to hiding visible QuickTools toplevels so the dialog is
    not buried underneath them.
    """
    top = owner.winfo_toplevel()
    windowing = _windowing_system(top)
    if windowing != "x11":
        return action(parent=top, **options)
    root = _application_root(top)
    if install_overlay_dialogs(root):
        try:
            return action(parent=top, **options)
        finally:
            _forget_saved_focus()
            _restore_owner_focus(top)

    # Fallback for XWayland / environments without X11 focus control.
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
        _restore_owner_focus(top)


def open_native_file_dialog(owner: tk.Misc, opener, **options):
    """Open a native file dialog that is visible above frameless windows."""
    return run_modal_dialog(owner, opener, **options)
