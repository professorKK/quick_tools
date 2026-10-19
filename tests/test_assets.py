from __future__ import annotations

from PIL import Image

from quicktools import paths


def test_required_assets_exist() -> None:
    assets = paths.assets_dir()
    for name in (
        "logo.png",
        "icon.png",
        "launcher.png",
        "tray.png",
        "tray-linux.png",
        "quicktools.ico",
    ):
        path = assets / name
        assert path.is_file(), f"missing asset: {path}"
        assert path.stat().st_size > 0
    for name in ("plus", "minus", "multiply", "divide", "equals"):
        path = assets / "keypad" / f"{name}.png"
        assert path.is_file(), f"missing keypad icon: {path}"
        assert path.stat().st_size > 0


def test_raster_assets_are_valid_rgba() -> None:
    assets = paths.assets_dir()
    for name, size in {
        "icon.png": (256, 256),
        "launcher.png": (48, 48),
        "tray.png": (64, 64),
        "tray-linux.png": (96, 64),
    }.items():
        with Image.open(assets / name) as image:
            assert image.size == size
            assert "A" in image.getbands()


def test_ico_is_windows_icon() -> None:
    with Image.open(paths.assets_dir() / "quicktools.ico") as image:
        assert image.format == "ICO"


def test_tray_icons_have_no_box_and_fill_the_height() -> None:
    for name in ("tray.png", "tray-linux.png"):
        with Image.open(paths.assets_dir() / name) as image:
            image = image.convert("RGBA")
            alpha = image.getchannel("A")
            # No opaque/bordered rectangular background.
            for point in (
                (0, 0),
                (image.width - 1, 0),
                (0, image.height - 1),
                (image.width - 1, image.height - 1),
            ):
                assert alpha.getpixel(point) == 0
            bbox = alpha.getbbox()
            assert bbox is not None
            assert bbox[3] - bbox[1] >= int(image.height * 0.8)
            if name == "tray-linux.png":
                # The Linux tray K is intentionally stretched to use the
                # wide 24×16 slot.
                assert bbox[2] - bbox[0] >= int(image.width * 0.8)
