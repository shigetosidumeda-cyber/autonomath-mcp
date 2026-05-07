#!/usr/bin/env python3
"""Regenerate site/assets/og*.png from a single source of truth.

Sizes:
  - og.png         1200 x 630  (Open Graph default, Facebook/LinkedIn)
  - og-twitter.png 1200 x 675  (Twitter summary_large_image, 16:9)
  - og-square.png  1200 x 1200 (LINE / square placements)

Pure Pillow, no external image deps. Re-run via:

    .venv/bin/python scripts/generate_og_images.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "site" / "assets"

# Font fallback chain: macOS dev paths first, then Linux/CI standard paths.
# When neither is available, _resolve_font_path() falls back to PIL default
# (still produces a render — albeit with US-ASCII glyphs only — instead of
# crashing the pages-regenerate workflow).
JP_FONT_CANDIDATES: tuple[str, ...] = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
EN_FONT_CANDIDATES: tuple[str, ...] = (
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def _resolve_font_path(candidates: tuple[str, ...]) -> str | None:
    """Return the first existing font path, or None if none match."""
    for cand in candidates:
        if Path(cand).exists():
            return cand
    return None


JP_FONT_PATH = _resolve_font_path(JP_FONT_CANDIDATES)
EN_FONT_PATH = _resolve_font_path(EN_FONT_CANDIDATES) or JP_FONT_PATH

BG = (255, 255, 255)
TEXT = (17, 17, 17)
MUTED = (85, 85, 85)
ACCENT = (30, 58, 138)
BORDER = (229, 229, 229)


def _load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font; fall back to PIL's bundled bitmap font if path is None
    or unreadable. Lets pages-regenerate produce *some* output on minimal CI runners
    that lack any system font installs (rather than hard-failing the entire workflow).
    """
    if path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _draw_brand_mark(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    draw.rectangle((x, y, x + size, y + size), fill=ACCENT, outline=ACCENT)
    fnt = _load_font(EN_FONT_PATH, int(size * 0.55))
    bbox = draw.textbbox((0, 0), "jc", font=fnt)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(
        (x + (size - tw) / 2, y + (size - th) / 2 - bbox[1]),
        "jc",
        font=fnt,
        fill=(255, 255, 255),
    )


def _render(width: int, height: int, headline: str, subline: str, kicker: str) -> Image.Image:
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    pad = int(width * 0.06)
    mark_size = int(width * 0.07)

    _draw_brand_mark(draw, pad, pad, mark_size)
    brand_fnt = _load_font(EN_FONT_PATH, int(mark_size * 0.55))
    draw.text(
        (pad + mark_size + int(pad * 0.3), pad + int(mark_size * 0.22)),
        "jpcite",
        font=brand_fnt,
        fill=TEXT,
    )

    kicker_fnt = _load_font(JP_FONT_PATH, int(width * 0.025))
    draw.text((pad, pad + mark_size + int(pad * 0.7)), kicker, font=kicker_fnt, fill=MUTED)

    head_fnt = _load_font(JP_FONT_PATH, int(width * 0.052))
    head_y = pad + mark_size + int(pad * 1.6)
    draw.multiline_text((pad, head_y), headline, font=head_fnt, fill=TEXT, spacing=10)
    head_bbox = draw.multiline_textbbox((pad, head_y), headline, font=head_fnt, spacing=10)
    head_bottom = head_bbox[3]

    sub_fnt = _load_font(JP_FONT_PATH, int(width * 0.026))
    sub_y = head_bottom + int(pad * 0.6)
    draw.text((pad, sub_y), subline, font=sub_fnt, fill=MUTED)

    bottom_fnt = _load_font(EN_FONT_PATH, int(width * 0.022))
    bottom_y = height - pad - int(width * 0.03)
    draw.text((pad, bottom_y), "jpcite.com · Bookyou Inc.", font=bottom_fnt, fill=MUTED)

    draw.line(
        [(pad, height - pad - int(width * 0.06)), (width - pad, height - pad - int(width * 0.06))],
        fill=BORDER,
        width=2,
    )

    return img


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ASSETS,
        help="Directory to write og*.png into (default: site/assets/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended output paths but do not write any PNG",
    )
    args = parser.parse_args()

    headline = "日本の公的制度を、5 つの\nインターフェースで。"
    subline = "API + MCP + LINE + 法令アラート + 埋込 Widget · ¥3/req metered"
    kicker = "補助金 · 融資 · 税制 · 認定 · 13,578 制度 · 一次資料 100%"

    targets = [
        ("og.png", 1200, 630),
        ("og-twitter.png", 1200, 675),
        ("og-square.png", 1200, 1200),
    ]

    out_dir: Path = args.out_dir
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    for name, w, h in targets:
        out = out_dir / name
        if args.dry_run:
            print(f"[dry-run] would write {out}  ({w}x{h})")
            continue
        img = _render(w, h, headline, subline, kicker)
        img.save(out, "PNG", optimize=True)
        try:
            rel = out.relative_to(REPO)
        except ValueError:
            rel = out
        print(f"wrote {rel}  ({w}x{h})")


if __name__ == "__main__":
    main()
