"""Fixed per-mode screenshot shortcuts shared by the UI and the plugin."""

from __future__ import annotations

from quicktools.config import HotkeySpec

MODE_HOTKEYS: dict[str, HotkeySpec] = {
    "capture_region": HotkeySpec(("ctrl", "alt"), "1"),
    "capture_window": HotkeySpec(("ctrl", "alt"), "2"),
    "capture_freeform": HotkeySpec(("ctrl", "alt"), "3"),
    "capture_scroll": HotkeySpec(("ctrl", "alt"), "4"),
}


def mode_shortcut_items() -> tuple[tuple[str, HotkeySpec], ...]:
    """Return ``(action, spec)`` pairs in display order."""

    return tuple(MODE_HOTKEYS.items())


def shortcut_label(action: str) -> str:
    """Return the display label for a capture action."""

    try:
        return MODE_HOTKEYS[action].display()
    except KeyError:
        raise KeyError(f"未知截图动作：{action}") from None


def shortcut_labels() -> dict[str, str]:
    """Return a copy of all action-to-label mappings."""

    return {
        action: spec.display() for action, spec in MODE_HOTKEYS.items()
    }
