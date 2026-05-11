#!/usr/bin/env python3
# ruff: noqa: N803,N806,SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017
"""favicon set + Apple touch icon + maskable PWA icon 生成 (minimal SVG → PNG multi-size)."""

from __future__ import annotations

import pathlib
import sys


def _try_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError:
        return None, None, None


SIZES = [16, 32, 48, 64, 96, 128, 180, 192, 256, 384, 512]


def make_icon(size: int, out: pathlib.Path, Image, ImageDraw, ImageFont) -> None:
    """Simple jpcite mark: blue square with white 'j' character."""
    img = Image.new("RGBA", (size, size), color=(10, 77, 140, 255))
    draw = ImageDraw.Draw(img)
    try:
        font_size = int(size * 0.6)
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except OSError:
        font = ImageFont.load_default()
    # Draw 'j' centered
    text = "j"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def make_favicon_ico(root: pathlib.Path, Image) -> None:
    """16x16 + 32x32 ICO file at site/favicon.ico."""
    out = root / "site" / "favicon.ico"
    if out.exists():
        return
    sizes = [(16, 16), (32, 32)]
    images = []
    for w, _ in sizes:
        img = Image.new("RGBA", (w, w), color=(10, 77, 140, 255))
        images.append(img)
    images[0].save(out, format="ICO", sizes=sizes)


def main() -> int:
    Image, ImageDraw, ImageFont = _try_pillow()
    if Image is None:
        print("[generate_favicon] Pillow not installed - skipping (pip install Pillow)")
        return 0
    root = pathlib.Path(__file__).resolve().parent.parent
    brand_dir = root / "site" / "assets" / "brand"
    count = 0
    for size in SIZES:
        out = brand_dir / f"icon-{size}.png"
        if out.exists():
            continue
        make_icon(size, out, Image, ImageDraw, ImageFont)
        count += 1
    # Apple touch icons (180x180 specifically)
    apple_180 = brand_dir / "apple-touch-icon-180.png"
    if not apple_180.exists():
        make_icon(180, apple_180, Image, ImageDraw, ImageFont)
        count += 1
    # Favicon.ico (at site root)
    make_favicon_ico(root, Image)
    print(f"[generate_favicon] generated {count} icons + favicon.ico at site/assets/brand/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
