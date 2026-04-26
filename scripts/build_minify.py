#!/usr/bin/env python3
"""Static-asset optimizer for AutonoMath / autonomath.ai (Cloudflare Pages).

Performs three things, all idempotent:

1. Minifies hand-written CSS/JS in `site/` and `site/widget/` and the mkdocs
   source `docs/stylesheets/extra.css`. Originals are preserved as `*.src.css` /
   `*.src.js` so re-runs always read fresh source. The minified bytes are
   written back to the original filename so existing references in the
   10,953 generated program pages keep working without a re-render.

2. Generates WebP companion images for non-OG / non-favicon PNGs in
   `site/assets/`. OG cards (`og.png`, `og-twitter.png`, `og-square.png`),
   favicons, and apple-touch-icons are intentionally left untouched —
   downstream SNS scrapers and iOS still want PNG.

3. Self-hosts Noto Sans JP for the mkdocs-generated docs. The marketing
   pages (hand-written HTML in `site/`) already use system fonts and do
   not need self-hosting. We strip the Google Fonts <link> from
   site/docs/**/index.html and inject a small `@font-face` block into
   docs/stylesheets/extra.css that points at fonts subset placed at
   site/static/fonts/. Re-running mkdocs build will re-emit the Google
   Fonts <link>; this script is the post-build step.

Run after `mkdocs build` and after `scripts/generate_program_pages.py`:

    python scripts/build_minify.py

The script logs sizes before/after for each file and a summary at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import shutil
import ssl
import sys
import urllib.request
from pathlib import Path

# macOS Python 3.13 ships without a built-in CA bundle, so urllib fails
# with CERTIFICATE_VERIFY_FAILED on every HTTPS request. Use certifi if
# available; otherwise fall back to the platform default (which works
# inside CI containers but not on raw macOS).
try:
    import certifi

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = None

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
DOCS_SRC = REPO / "docs"
LOG = logging.getLogger("build_minify")

# CSS files: hand-written marketing CSS plus mkdocs extra.css source.
CSS_FILES = [
    SITE / "styles.css",
    SITE / "widget" / "autonomath.css",
    DOCS_SRC / "stylesheets" / "extra.css",
]

# JS files. Top-level marketing JS + widget JS + assets JS. We keep
# `dashboard_init.js` and `analytics.js` in the list — both are loaded
# above the fold on dashboard.html / index.html.
JS_FILES = [
    SITE / "analytics.js",
    SITE / "dashboard.js",
    SITE / "dashboard_v2.js",
    SITE / "dashboard_init.js",
    SITE / "assets" / "feedback-widget.js",
    SITE / "assets" / "prescreen-demo.js",
    SITE / "widget" / "autonomath.js",
]

# PNGs that should NOT be converted to WebP — SNS scrapers (Twitter,
# LinkedIn, Slack) and iOS demand PNG for these use cases.
WEBP_SKIP = {
    "og.png",
    "og-square.png",
    "og-twitter.png",
    "favicon-16.png",
    "favicon-32.png",
    "apple-touch-icon.png",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def _src_path(p: Path) -> Path:
    """Returns the .src.<ext> sibling — preserves original prior to minify."""
    return p.with_suffix(f".src{p.suffix}")


def minify_css() -> tuple[int, int]:
    try:
        import csscompressor
    except ImportError:
        sys.exit("ERROR: pip install csscompressor")

    before_total = 0
    after_total = 0
    for path in CSS_FILES:
        if not path.exists():
            LOG.info("skip (missing) %s", path)
            continue
        src = _src_path(path)
        # First run: snapshot original to .src so subsequent runs read fresh.
        if not src.exists():
            shutil.copy2(path, src)
        original = _read(src)
        minified = csscompressor.compress(original)
        # Idempotent write: only touch mtime if content actually changes.
        current = _read(path) if path.exists() else ""
        if current != minified:
            _write(path, minified)
        before = len(original.encode("utf-8"))
        after = len(minified.encode("utf-8"))
        before_total += before
        after_total += after
        LOG.info(
            "css  %-50s  %7d -> %7d  (%+d, %.0f%%)",
            path.relative_to(REPO),
            before,
            after,
            after - before,
            100 * after / before if before else 0,
        )
    return before_total, after_total


def minify_js() -> tuple[int, int]:
    try:
        import rjsmin
    except ImportError:
        sys.exit("ERROR: pip install rjsmin")

    before_total = 0
    after_total = 0
    for path in JS_FILES:
        if not path.exists():
            LOG.info("skip (missing) %s", path)
            continue
        src = _src_path(path)
        if not src.exists():
            shutil.copy2(path, src)
        original = _read(src)
        minified = rjsmin.jsmin(original)
        current = _read(path) if path.exists() else ""
        if current != minified:
            _write(path, minified)
        before = len(original.encode("utf-8"))
        after = len(minified.encode("utf-8"))
        before_total += before
        after_total += after
        LOG.info(
            "js   %-50s  %7d -> %7d  (%+d, %.0f%%)",
            path.relative_to(REPO),
            before,
            after,
            after - before,
            100 * after / before if before else 0,
        )
    return before_total, after_total


def generate_webp() -> tuple[int, int]:
    """Generates *.webp alongside large PNGs. Returns (png_total, webp_total).

    Skips OG cards and icons (see WEBP_SKIP). The marketing HTML does not
    embed <img> tags today, so the WebP companions are pre-positioned for
    future <picture> tags or for direct OG override (some scrapers do
    accept WebP — but Twitter still does not, hence the skip-list).
    """
    try:
        from PIL import Image
    except ImportError:
        sys.exit("ERROR: pip install Pillow")

    png_total = 0
    webp_total = 0
    assets = SITE / "assets"
    for png in sorted(list(assets.glob("*.png")) + list(assets.glob("*.jpg")) + list(assets.glob("*.jpeg"))):
        if png.name in WEBP_SKIP:
            LOG.info("webp skip (sns/icon)  %s", png.relative_to(REPO))
            continue
        webp = png.with_suffix(".webp")
        # Idempotent: skip if webp newer than source.
        if webp.exists() and webp.stat().st_mtime >= png.stat().st_mtime:
            LOG.info("webp fresh           %s", webp.relative_to(REPO))
        else:
            with Image.open(png) as im:
                # Pillow's WebP encoder: method=6 is slowest+smallest,
                # quality=82 gives near-lossless for screenshots.
                im.save(webp, "WEBP", quality=82, method=6)
        before = png.stat().st_size
        after = webp.stat().st_size
        png_total += before
        webp_total += after
        LOG.info(
            "webp %-50s  %7d -> %7d  (%+d, %.0f%%)",
            webp.relative_to(REPO),
            before,
            after,
            after - before,
            100 * after / before if before else 0,
        )
    return png_total, webp_total


# Self-hosted Noto Sans JP — we use the Google Fonts CSS API v2 to fetch the
# JP+latin subset .woff2 files once and stash them under site/static/fonts/.
# At runtime the docs theme then references them via @font-face below.
FONT_DIR = SITE / "static" / "fonts"
FONT_WEIGHTS = ["400", "700"]  # regular + bold; mkdocs-material does not need 300/i variants for body copy
GOOGLE_FONTS_CSS_URL = (
    "https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@{weights}&display=swap"
)


def fetch_noto_sans_jp() -> list[Path]:
    """Downloads Noto Sans JP woff2 subsets to site/static/fonts/ once.

    Returns the list of stored woff2 paths. If they all already exist we
    skip the network entirely (idempotent for offline reruns).

    Implementation note: Google Fonts CSS2 API serves a CSS document with
    @font-face entries pointing at fonts.gstatic.com. We extract the
    woff2 URLs and download each. UA spoofing is required: the API
    returns different formats based on browser support.
    """
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    weights_param = ";".join(FONT_WEIGHTS)
    css_url = GOOGLE_FONTS_CSS_URL.format(weights=weights_param)

    # Fast path: already populated.
    existing = sorted(FONT_DIR.glob("noto-sans-jp-*.woff2"))
    if existing and len(existing) >= len(FONT_WEIGHTS):
        LOG.info("fonts cached  %d files in %s", len(existing), FONT_DIR.relative_to(REPO))
        return existing

    # Modern Chrome UA → woff2 + unicode-range subsets.
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    req = urllib.request.Request(css_url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
            css_text = resp.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        LOG.warning("fonts fetch FAILED — %s. Skipping self-host.", exc)
        return []

    # The returned CSS contains many @font-face blocks (one per weight per
    # unicode-range subset). We download each woff2 once.
    woff2_urls = sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css_text)))
    LOG.info("fonts CSS lists %d woff2 subsets", len(woff2_urls))
    saved: list[Path] = []
    for url in woff2_urls:
        # Local filename: noto-sans-jp-<sha8>.woff2 — deterministic and
        # collision-free.
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        out = FONT_DIR / f"noto-sans-jp-{digest}.woff2"
        if out.exists():
            saved.append(out)
            continue
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": ua}),
                timeout=30,
                context=_SSL_CTX,
            ) as r:
                out.write_bytes(r.read())
        except Exception as exc:
            LOG.warning("woff2 fetch FAILED %s — %s", url, exc)
            continue
        saved.append(out)
    # Save the rewritten CSS pointing at the local files.
    rewritten = css_text
    for url in woff2_urls:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        rewritten = rewritten.replace(url, f"/static/fonts/noto-sans-jp-{digest}.woff2")
    (FONT_DIR / "noto-sans-jp.css").write_text(rewritten, encoding="utf-8")
    LOG.info("fonts saved   %d woff2 + 1 css to %s", len(saved), FONT_DIR.relative_to(REPO))
    return saved


GOOGLE_FONTS_LINK_RE = re.compile(
    r'<link[^>]*href="https://fonts\.googleapis\.com/[^"]*"[^>]*/?>',
)


def patch_mkdocs_html() -> int:
    """Replaces external Google Fonts <link> with self-hosted CSS in
    every site/docs/**/index.html. Returns count of files patched.

    The Cloudflare Pages CSP is `script-src 'self'; font-src 'self' data:` —
    so the original Google Fonts <link> would be CSP-blocked anyway.
    We replace it with `/static/fonts/noto-sans-jp.css`.
    """
    docs_root = SITE / "docs"
    if not docs_root.is_dir():
        LOG.info("docs root missing  %s", docs_root)
        return 0
    patched = 0
    replacement = '<link rel="stylesheet" href="/static/fonts/noto-sans-jp.css">'
    for html in docs_root.rglob("*.html"):
        text = _read(html)
        new = GOOGLE_FONTS_LINK_RE.sub(replacement, text)
        if new != text:
            _write(html, new)
            patched += 1
    LOG.info("html patched  %d files (Google Fonts -> self-host)", patched)
    return patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fonts", action="store_true", help="skip Noto Sans JP self-host (offline)")
    parser.add_argument("--no-webp", action="store_true", help="skip WebP generation")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    css_b, css_a = minify_css()
    js_b, js_a = minify_js()
    if args.no_webp:
        png_b = png_a = 0
    else:
        png_b, png_a = generate_webp()
    if args.no_fonts:
        font_files = []
        html_patched = 0
    else:
        font_files = fetch_noto_sans_jp()
        html_patched = patch_mkdocs_html() if font_files else 0

    LOG.info("")
    LOG.info("=== summary ===")
    LOG.info("CSS  total  %7d -> %7d  (saved %d B)", css_b, css_a, css_b - css_a)
    LOG.info("JS   total  %7d -> %7d  (saved %d B)", js_b, js_a, js_b - js_a)
    if not args.no_webp:
        LOG.info("WebP total  %7d -> %7d  (saved %d B vs PNG sources)", png_b, png_a, png_b - png_a)
    if font_files:
        font_bytes = sum(p.stat().st_size for p in font_files)
        LOG.info("Fonts       %d woff2 (%d B) self-hosted; %d HTML files patched", len(font_files), font_bytes, html_patched)
    LOG.info("Total saved per first-paint (css+js): %d B", (css_b - css_a) + (js_b - js_a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
