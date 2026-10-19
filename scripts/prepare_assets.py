"""Generate application/tray icon assets from the master logo."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "quicktools" / "assets"
SOURCE = ASSETS / "logo.png"


def centered_icon(source: Image.Image, size: tuple[int, int], box: int) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    fitted = ImageOps.contain(source, (box, box), Image.Resampling.LANCZOS)
    x = (size[0] - fitted.width) // 2
    y = (size[1] - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))
    return canvas


def _rounded_stroke(draw: ImageDraw.ImageDraw, points, fill: str, width: int) -> None:
    draw.line(points, fill=fill, width=width, joint="curve")
    radius = width // 2
    for x, y in (points[0], points[-1]):
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=fill,
        )


def _make_keypad_icons() -> None:
    """Draw crisp Google-colored operator icons at 4x and downsample."""
    folder = ASSETS / "keypad"
    folder.mkdir(exist_ok=True)
    scale = 4
    size = 36
    canvas = size * scale
    colors = {
        "plus": "#EA4335",
        "minus": "#F9AB00",
        "multiply": "#34A853",
        "divide": "#669DF6",
        "equals": "#1A73E8",
    }
    stroke_width = 18
    for name, color in colors.items():
        image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if name == "plus":
            _rounded_stroke(draw, [(34, 72), (110, 72)], color, stroke_width)
            _rounded_stroke(draw, [(72, 34), (72, 110)], color, stroke_width)
        elif name == "minus":
            _rounded_stroke(draw, [(34, 72), (110, 72)], color, stroke_width)
        elif name == "multiply":
            _rounded_stroke(draw, [(40, 40), (104, 104)], color, stroke_width)
            _rounded_stroke(draw, [(104, 40), (40, 104)], color, stroke_width)
        elif name == "divide":
            _rounded_stroke(draw, [(34, 72), (110, 72)], color, stroke_width)
            radius = 10
            for cy in (43, 101):
                draw.ellipse(
                    (72 - radius, cy - radius, 72 + radius, cy + radius),
                    fill=color,
                )
        elif name == "equals":
            _rounded_stroke(draw, [(34, 55), (110, 55)], color, stroke_width)
            _rounded_stroke(draw, [(34, 89), (110, 89)], color, stroke_width)
        image.resize((size, size), Image.Resampling.LANCZOS).save(
            folder / f"{name}.png", optimize=True
        )


def _make_tray_icons(source: Image.Image) -> None:
    """Make borderless, large K icons without artificially thickening it.

    At 16×16 the detailed gradient becomes visual noise, so we keep the K's
    silhouette and fill it with a clean bright blue gradient. The Linux icon
    is additionally stretched horizontally to use the wide tray slot.
    """
    work = ImageOps.contain(source, (512, 512), Image.Resampling.LANCZOS)
    alpha = work.getchannel("A").point(lambda value: 255 if value > 40 else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("logo has no visible pixels")
    alpha = alpha.crop(bbox)
    width, height = alpha.size

    top = (79, 195, 255)
    bottom = (26, 115, 232)
    gradient = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(gradient)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(
            round(top[i] * (1 - ratio) + bottom[i] * ratio)
            for i in range(3)
        ) + (255,)
        draw.line([(0, y), (width, y)], fill=color)

    silhouette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    silhouette.paste(gradient, (0, 0), alpha)

    def place(size: tuple[int, int], content: tuple[int, int]) -> Image.Image:
        # Resize directly (rather than contain) so the Linux icon can be
        # stretched horizontally without changing the stroke weight.
        fitted = silhouette.resize(content, Image.Resampling.LANCZOS)
        out = Image.new("RGBA", size, (0, 0, 0, 0))
        out.alpha_composite(
            fitted,
            ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2),
        )
        return out

    natural_height = 60
    natural_width = max(
        1, round(silhouette.width * natural_height / silhouette.height)
    )
    place((64, 64), (natural_width, natural_height)).save(
        ASSETS / "tray.png", optimize=True
    )
    # GNOME/XEmbed has a 24×16 (3:2) slot. Stretching the K horizontally
    # makes it much easier to recognize without making the strokes bolder.
    place((96, 64), (88, 60)).save(
        ASSETS / "tray-linux.png", optimize=True
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tray-only",
        action="store_true",
        help="only regenerate tray.png and tray-linux.png",
    )
    args = parser.parse_args()

    source = Image.open(SOURCE).convert("RGBA")
    bbox = source.getchannel("A").getbbox()
    if bbox:
        source = source.crop(bbox)

    if args.tray_only:
        _make_tray_icons(source)
        print("tray icons written to", ASSETS)
        return

    icon = centered_icon(source, (256, 256), 232)
    icon.save(ASSETS / "icon.png", optimize=True)

    launcher = centered_icon(source, (48, 48), 44)
    launcher.save(ASSETS / "launcher.png", optimize=True)

    _make_keypad_icons()
    _make_tray_icons(source)

    icon.save(
        ASSETS / "quicktools.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("assets written to", ASSETS)


if __name__ == "__main__":
    main()
