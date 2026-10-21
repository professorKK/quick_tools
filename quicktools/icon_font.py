"""随包加载 Material Icons 图标字体。

Windows 不再依赖系统自带的 Segoe Fluent/MDL2，Linux 也不再只能用 Canvas
线稿：两个平台都从 ``assets/fonts/MaterialIcons-Regular.ttf`` 加载同一套
字形，标题栏的设置/置顶和关于页的信息图标因此保持一致。

字体只注册到当前进程：
* Windows 使用 ``AddFontResourceExW(FR_PRIVATE)``；
* Linux 使用 fontconfig 的 ``FcConfigAppFontAddFile``，Tk 通过 Xft 即可看到；
* 其他平台返回空字符串，调用方继续使用 Canvas 回退图标。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

from . import paths
from .logging_setup import get_logger

log = get_logger(__name__)

FAMILY = "Material Icons"
FILENAME = "MaterialIcons-Regular.ttf"

_loaded_family: str | None = None
_attempted = False
_fontconfig = None  # 保持 fontconfig 库常驻，避免注册后卸载


def font_path():
    """Path to the bundled Material Icons font."""
    return paths.assets_dir() / "fonts" / FILENAME


def _load_windows(path) -> bool:
    gdi32 = ctypes.windll.gdi32
    gdi32.AddFontResourceExW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    gdi32.AddFontResourceExW.restype = ctypes.c_int
    # FR_PRIVATE: make the font visible only to this process.
    added = gdi32.AddFontResourceExW(
        ctypes.c_wchar_p(str(path)), 0x10, None
    )
    return bool(added)


def _load_linux(path) -> bool:
    global _fontconfig
    library = ctypes.util.find_library("fontconfig") or "libfontconfig.so.1"
    _fontconfig = ctypes.CDLL(library)
    _fontconfig.FcInit.restype = ctypes.c_bool
    _fontconfig.FcConfigAppFontAddFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
    ]
    _fontconfig.FcConfigAppFontAddFile.restype = ctypes.c_bool
    _fontconfig.FcInit()
    return bool(
        _fontconfig.FcConfigAppFontAddFile(None, str(path).encode("utf-8"))
    )


def ensure_loaded() -> str:
    """Register the bundled icon font once and return its family name.

    Returns an empty string when the file is missing or the platform cannot
    load it; callers then fall back to the Canvas icons.
    """
    global _loaded_family, _attempted
    if _attempted:
        return _loaded_family or ""
    _attempted = True

    path = font_path()
    if not path.is_file():
        log.warning("内置图标字体缺失：%s", path)
        return ""

    try:
        if sys.platform == "win32":
            loaded = _load_windows(path)
        elif sys.platform.startswith("linux"):
            loaded = _load_linux(path)
        else:  # pragma: no cover - 目前只面向 Windows/Linux
            loaded = False
    except Exception:
        log.debug("加载内置图标字体失败", exc_info=True)
        loaded = False

    if not loaded:
        log.warning("无法加载内置图标字体，回退到 Canvas 图标")
        return ""

    _loaded_family = FAMILY
    log.info("已加载内置图标字体：%s", FAMILY)
    return FAMILY
