from __future__ import annotations

import io
import struct

from PIL import Image

from quicktools.plugins.clipboard.backends.win_formats import (
    DROPFILES_HEADER_SIZE,
    decode_hdrop,
    dib_to_png,
    encode_hdrop,
    png_to_dib,
)


def test_hdrop_roundtrip_unicode_and_spaces() -> None:
    paths = [
        r"C:\Users\kk\Documents\example.pdf",
        r"D:\项目\图片 1.png",
        r"\\server\share\file name.txt",
    ]
    payload = encode_hdrop(paths)
    offset, x, y, nc, wide = struct.unpack_from("<IiiII", payload, 0)
    assert offset == DROPFILES_HEADER_SIZE
    assert (x, y, nc, wide) == (0, 0, 0, 1)
    assert decode_hdrop(payload) == paths


def test_hdrop_empty_list() -> None:
    assert decode_hdrop(encode_hdrop([])) == []
    assert decode_hdrop(b"") == []


def test_png_dib_roundtrip() -> None:
    image = Image.new("RGB", (37, 21), (12, 34, 56))
    source = io.BytesIO()
    image.save(source, "PNG")
    dib = png_to_dib(source.getvalue())
    assert dib[:4] == struct.pack("<I", 40)  # BITMAPINFOHEADER
    png = dib_to_png(dib)
    with Image.open(io.BytesIO(png)) as result:
        result.load()
        assert result.size == (37, 21)
        assert result.convert("RGB").getpixel((0, 0)) == (12, 34, 56)
    image.close()


def test_transparent_png_to_dib() -> None:
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 0))
    source = io.BytesIO()
    image.save(source, "PNG")
    image.close()
    dib = png_to_dib(source.getvalue())
    png = dib_to_png(dib)
    with Image.open(io.BytesIO(png)) as result:
        result.load()
        assert result.size == (8, 8)
