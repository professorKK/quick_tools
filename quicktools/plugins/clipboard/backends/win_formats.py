"""Pure Windows clipboard format helpers (testable on any platform).

Only ``struct`` and Pillow are used here so the encoding logic can be unit
tested on Linux. Actual Win32 API calls live in :mod:`windows`.
"""

from __future__ import annotations

import io
import struct
import sys
from typing import Sequence

from PIL import BmpImagePlugin, Image

DROPFILES_HEADER_SIZE = 20
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040


def encode_hdrop(paths: Sequence[str]) -> bytes:
    """Build a CF_HDROP payload with a Unicode (wide) DROPFILES header."""
    # DROPFILES { DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide; }
    header = struct.pack("<IiiII", DROPFILES_HEADER_SIZE, 0, 0, 0, 1)
    payload = "\0".join(paths) + "\0\0"
    return header + payload.encode("utf-16le")


def decode_hdrop(data: bytes) -> list[str]:
    """Decode a CF_HDROP payload; used by tests and diagnostics."""
    if len(data) < DROPFILES_HEADER_SIZE:
        return []
    offset, _x, _y, _nc, wide = struct.unpack_from("<IiiII", data, 0)
    offset = max(0, min(offset, len(data)))
    raw = data[offset:]
    if wide:
        text = raw.decode("utf-16le", "replace")
    else:
        encoding = "mbcs" if sys.platform == "win32" else "latin-1"
        try:
            text = raw.decode(encoding, "replace")
        except LookupError:
            text = raw.decode("latin-1", "replace")
    return [part for part in text.split("\0") if part]


def png_to_dib(png: bytes) -> bytes:
    """Convert PNG bytes to a CF_DIB payload (BITMAPINFOHEADER + pixels)."""
    with Image.open(io.BytesIO(png)) as source:
        source.load()
        image = source.copy()
    try:
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            rgb = background
            rgba.close()
        else:
            rgb = image.convert("RGB")
        output = io.BytesIO()
        rgb.save(output, "BMP")
        rgb.close()
    finally:
        image.close()
    bmp = output.getvalue()
    if len(bmp) < 14 or bmp[:2] != b"BM":
        raise ValueError("BMP 编码失败")
    # A DIB starts at the BITMAPINFOHEADER immediately after the 14-byte
    # BITMAPFILEHEADER; the pixel array offset is irrelevant here.
    return bmp[14:]


def dib_to_png(dib: bytes) -> bytes:
    """Convert a CF_DIB/CF_DIBV5 payload to PNG bytes via Pillow."""
    image = BmpImagePlugin.DibImageFile(io.BytesIO(dib))
    try:
        image.load()
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()
    finally:
        image.close()
