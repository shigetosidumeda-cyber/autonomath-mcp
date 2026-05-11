#!/usr/bin/env python3
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017
"""OG image 生成 (PNG 1200x630)、Pillow only、LLM 呼出ゼロ。

Generates social card images for each site/*.html page based on:
  - <title> tag (first 60 chars)
  - <meta name="description"> (first 120 chars)
  - Page slug for branding line
Output: site/og/{slug}.png
"""

from __future__ import annotations

import pathlib
import re
import sys


def _try_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError:
        return None, None, None


def slug_for(html_path: pathlib.Path, root: pathlib.Path) -> str:
    rel = html_path.relative_to(root / "site")
    return str(rel).removesuffix("/index.html").removesuffix(".html").replace("/", "_") or "index"


def extract_meta(html_path: pathlib.Path) -> tuple[str, str]:
    text = html_path.read_text("utf-8", errors="ignore")
    title_match = re.search(r"<title>([^<]+)</title>", text)
    desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', text)
    title = title_match.group(1).strip() if title_match else "jpcite"
    desc = desc_match.group(1).strip() if desc_match else ""
    return title[:60], desc[:120]


def make_og(
    slug: str, title: str, desc: str, out: pathlib.Path, Image, ImageDraw, ImageFont
) -> None:
    img = Image.new("RGB", (1200, 630), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 48)
        desc_font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 24)
        brand_font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 28)
    except OSError:
        title_font = ImageFont.load_default()
        desc_font = ImageFont.load_default()
        brand_font = ImageFont.load_default()
    # Brand bar (top, blue)
    draw.rectangle((0, 0, 1200, 80), fill=(10, 77, 140))
    draw.text(
        (40, 24), "jpcite — 日本公的制度 Evidence API/MCP", fill=(255, 255, 255), font=brand_font
    )
    # Title (wrap to 2 lines max)
    draw.text((40, 140), title, fill=(15, 23, 42), font=title_font)
    # Description (wrap)
    draw.text((40, 300), desc, fill=(100, 116, 139), font=desc_font)
    # Footer
    draw.text(
        (40, 540),
        "Bookyou株式会社 / T8010001213708 / jpcite.com",
        fill=(100, 116, 139),
        font=desc_font,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)


def main() -> int:
    Image, ImageDraw, ImageFont = _try_pillow()
    if Image is None:
        print("[generate_og_images] Pillow not installed - skipping (pip install Pillow)")
        return 0
    root = pathlib.Path(__file__).resolve().parent.parent
    sample = (root / "site").rglob("*.html")
    count = 0
    for p in sample:
        if "_assets" in str(p) or ".cursor" in str(p):
            continue
        slug = slug_for(p, root)
        title, desc = extract_meta(p)
        out = root / "site" / "og" / f"{slug}.png"
        if out.exists():
            continue  # idempotent: skip existing
        try:
            make_og(slug, title, desc, out, Image, ImageDraw, ImageFont)
            count += 1
            if count >= 10:  # batch limit per run
                break
        except Exception as exc:  # noqa: BLE001
            print(f"[generate_og_images] WARN {slug}: {exc}")
    print(f"[generate_og_images] generated {count} OG images under site/og/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
