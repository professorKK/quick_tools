#!/usr/bin/env python3
"""Native Linux StatusNotifierItem / Ayatana AppIndicator helper.

This script is intentionally standalone and is launched with the system
Python (``/usr/bin/python3``), because PyGObject and AyatanaAppIndicator are
distribution packages. It talks to the QuickTools primary instance over the
local Unix socket. Menus are drawn by the desktop shell, so their style matches
other applications on the system.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3, GLib, Gtk  # noqa: E402


def send_command(endpoint: str, command: str) -> bool:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(0.6)
    try:
        sock.connect(endpoint)
        sock.sendall((command + "\n").encode("ascii"))
        try:
            sock.recv(16)
        except OSError:
            pass
        return True
    except OSError:
        return False
    finally:
        sock.close()


class NativeTray:
    def __init__(self, endpoint: str, icon_path: str) -> None:
        self.endpoint = endpoint
        self.misses = 0

        self.indicator = AyatanaAppIndicator3.Indicator.new(
            f"quicktools_{os.getpid()}",
            icon_path,
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("QuickTools")
        self.indicator.set_icon_full(icon_path, "QuickTools")

        menu = Gtk.Menu()
        show_item = Gtk.MenuItem(label="显示")
        quit_item = Gtk.MenuItem(label="退出")
        show_item.connect("activate", self._show)
        quit_item.connect("activate", self._quit)
        menu.append(show_item)
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)

        GLib.timeout_add_seconds(3, self._watchdog)

    def _show(self, _item=None) -> None:
        send_command(self.endpoint, "show")

    def _quit(self, _item=None) -> None:
        send_command(self.endpoint, "quit")
        Gtk.main_quit()

    def _watchdog(self) -> bool:
        if send_command(self.endpoint, "ping"):
            self.misses = 0
        else:
            self.misses += 1
            if self.misses >= 2:
                Gtk.main_quit()
                return False
        return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--icon", required=True)
    args = parser.parse_args()

    tray = NativeTray(args.endpoint, args.icon)

    def stop(*_args) -> None:
        GLib.idle_add(Gtk.main_quit)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    Gtk.main()
    # Keep the reference alive for the whole GTK loop.
    del tray
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
