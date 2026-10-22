"""Platform-specific application paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "QuickTools"
APP_ID = "quicktools"


def _env_path(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else fallback


def config_dir() -> Path:
    if sys.platform == "win32":
        base = _env_path("APPDATA", Path.home() / "AppData" / "Roaming")
        return base / APP_DIR_NAME
    return _env_path("XDG_CONFIG_HOME", Path.home() / ".config") / APP_ID


def data_dir() -> Path:
    if sys.platform == "win32":
        base = _env_path("APPDATA", Path.home() / "AppData" / "Roaming")
        return base / APP_DIR_NAME
    return _env_path("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_ID


def settings_file() -> Path:
    return config_dir() / "settings.json"


def window_state_file() -> Path:
    """Per-plugin window sizes, kept out of settings.json."""
    return config_dir() / "window_state.json"


def user_plugins_dir() -> Path:
    return data_dir() / "plugins"


def default_plugin_data_root() -> Path:
    return data_dir() / "plugin_data"


def plugin_data_root(root: str | Path | None = None) -> Path:
    """Resolve the plugin data root; blank means the default location."""
    raw = str(root).strip() if root is not None else ""
    if not raw:
        return default_plugin_data_root()
    return Path(raw).expanduser()


def plugin_data_dir(
    plugin_id: str, root: str | Path | None = None
) -> Path:
    return plugin_data_root(root) / plugin_id


def log_file() -> Path:
    return data_dir() / "logs" / "quicktools.log"


def package_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "quicktools"
    return Path(__file__).resolve().parent


def builtin_plugins_dir() -> Path:
    return package_dir() / "plugins"


def assets_dir() -> Path:
    return package_dir() / "assets"


def ensure_app_dirs() -> None:
    for path in (config_dir(), data_dir(), user_plugins_dir(), log_file().parent):
        path.mkdir(parents=True, exist_ok=True)


def ipc_runtime_file() -> Path:
    """Where the Windows IPC port is advertised.

    On Linux the Unix socket path is returned directly by ``ipc.py``.
    """
    if sys.platform == "win32":
        return data_dir() / "ipc-port"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path("/tmp")
    return base / f"quicktools-{os.getuid()}.sock"
