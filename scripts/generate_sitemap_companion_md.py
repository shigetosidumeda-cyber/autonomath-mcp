#!/usr/bin/env python3
"""Generate ``site/sitemap-companion-md.xml`` from current HTML inventory.

Wave 17 AX — companion-Markdown discovery surface.

Enumerates every SEO HTML page in ``site/cases``, ``site/laws``, and
``site/enforcement`` and emits a ``<url>`` entry pointing at the
GitHub-style ``.md`` companion (``https://jpcite.com/{cat}/{slug}.md``).

The script is idempotent: it always overwrites the output file and is
safe to run on every chunk push. ``lastmod`` is the current UTC date.

Usage
-----
    python scripts/generate_sitemap_companion_md.py
    python scripts/generate_sitemap_companion_md.py --require-md-exists
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"
OUTPUT_PATH = SITE_DIR / "sitemap-companion-md.xml"
CANONICAL_BASE = "https://jpcite.com"

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("cases", "cases"),
    ("laws", "laws"),
    ("enforcement", "enforcement"),
)

# Wave 46 tick2#10: top-level + press/legal/security companion .md files that live
# alongside the public site root (and a handful of nested public subdirs). These
# are NOT 1:1 companions to a cases/laws/enforcement HTML page — they are first
# class doc surfaces (about, pricing, transparency, press kit, subprocessors,
# security policy, etc.). Internal-only repo files (README.md, assets/BRAND.md)
# are intentionally excluded; they are not user-facing.
ROOT_INCLUDE_GLOBS: tuple[str, ...] = (
    "*.html.md",  # site/about.html.md, site/pricing.html.md, etc.
    "press/*.md",  # site/press/*.md (about/contact/fact-sheet/founders/quotes/screenshots)
    "legal/*.md",  # site/legal/subprocessors.md (+ future legal/*.md)
    "security/*.md",  # site/security/policy.md
)
ROOT_EXCLUDE_NAMES: frozenset[str] = frozenset({"README.md", "BRAND.md", "index.md"})


def _today_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _enumerate_root_page_urls() -> list[tuple[str, str]]:
    """Return (category, md_url) for top-level + press/legal/security companions.

    Wave 46 tick2#10: top-level `.html.md` companions plus press/legal/security
    `*.md` surfaces are public companion pages even though they are not in the
    three bulk record directories. This helper enumerates them so the sitemap
    reflects the full public companion-md surface.

    README.md / BRAND.md (repo-internal) and index.md are excluded.
    """
    entries: list[tuple[str, str]] = []
    for pattern in ROOT_INCLUDE_GLOBS:
        for p in sorted(SITE_DIR.glob(pattern)):
            if not p.is_file() or p.name in ROOT_EXCLUDE_NAMES:
                continue
            rel = p.relative_to(SITE_DIR).as_posix()
            md_url = f"{CANONICAL_BASE}/{rel}"
            entries.append(("root", md_url))
    return entries


def _enumerate_md_urls(
    require_md_exists: bool, scan_md_only: bool = False
) -> list[tuple[str, str]]:
    """Return (category, md_url) tuples in scope.

    Modes:
      - default (scan_md_only=False): iterate every ``.html`` page and emit the
        companion ``.md`` URL. Optionally restrict to entries whose ``.md`` sibling
        already exists on disk via ``require_md_exists``.
      - scan_md_only=True (Wave 22 correction): iterate every ``.md`` file directly,
        ignoring ``.html`` presence. This reflects the **actual** companion-Markdown
        inventory on disk rather than a theoretical HTML-derived set.
    """
    entries: list[tuple[str, str]] = []
    for cat, dir_name in CATEGORIES:
        cat_dir = SITE_DIR / dir_name
        if not cat_dir.is_dir():
            continue
        if scan_md_only:
            for p in sorted(cat_dir.iterdir()):
                if not p.is_file() or p.suffix != ".md" or p.name in {"index.md", "README.md"}:
                    continue
                slug = p.stem
                md_url = f"{CANONICAL_BASE}/{dir_name}/{slug}.md"
                entries.append((cat, md_url))
            continue
        for p in sorted(cat_dir.iterdir()):
            if not p.is_file() or p.suffix != ".html" or p.name == "index.html":
                continue
            slug = p.stem
            md_url = f"{CANONICAL_BASE}/{dir_name}/{slug}.md"
            if require_md_exists:
                md_path = p.with_suffix(".md")
                if not md_path.exists():
                    continue
            entries.append((cat, md_url))
    return entries


def _render_sitemap(entries: list[tuple[str, str]], lastmod: str) -> str:
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!--\n"
        "  Companion-Markdown surface sitemap for jpcite.com.\n"
        "  Public discovery surface for Markdown companions.\n"
        "\n"
        "  Each <loc> points at a GitHub-style `{url}.md` companion. LLM\n"
        "  citation crawlers and AEO agents can ingest the .md surface directly\n"
        "  without JS-aware HTML parsing.\n"
        "-->\n"
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    )
    body_parts: list[str] = []
    for _cat, url in entries:
        body_parts.append(
            "  <url>\n"
            f"    <loc>{url}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            "    <changefreq>monthly</changefreq>\n"
            "    <priority>0.5</priority>\n"
            "  </url>\n"
        )
    tail = "</urlset>\n"
    return head + "".join(body_parts) + tail


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--require-md-exists",
        action="store_true",
        help="Only include URLs whose .md sibling already exists on disk.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats but do not write the sitemap.",
    )
    p.add_argument(
        "--scan-md-only",
        action="store_true",
        default=True,
        help=(
            "Wave 22 correction (Wave 46 default ON): enumerate every .md "
            "file on disk directly so the sitemap matches the real on-disk "
            "companion-Markdown inventory across cases/laws/enforcement. "
            "Use --no-scan-md-only to fall back to the legacy HTML-derived "
            "mode."
        ),
    )
    p.add_argument(
        "--no-scan-md-only",
        dest="scan_md_only",
        action="store_false",
        help="Disable Wave 22 .md-direct scan (legacy HTML-derived mode).",
    )
    p.add_argument(
        "--include-root-pages",
        action="store_true",
        default=True,
        help=(
            "Wave 46 tick2#10: include top-level + press/legal/security "
            ".md companions (about/pricing/transparency/press/legal/security). "
            "Default True so the sitemap reflects the full disk companion-md "
            "inventory. Pass --no-include-root-pages to disable."
        ),
    )
    p.add_argument(
        "--no-include-root-pages",
        dest="include_root_pages",
        action="store_false",
        help="Disable Wave 46 root-page inclusion (legacy 3-category mode).",
    )
    args = p.parse_args(argv)
    entries = _enumerate_md_urls(args.require_md_exists, scan_md_only=args.scan_md_only)
    if args.include_root_pages:
        entries.extend(_enumerate_root_page_urls())
    if not entries:
        sys.stderr.write("[sitemap-companion-md] no .md URLs to emit\n")
        return 2
    lastmod = _today_iso()
    body = _render_sitemap(entries, lastmod)
    if not args.dry_run:
        OUTPUT_PATH.write_text(body, encoding="utf-8")
    by_cat: dict[str, int] = {}
    for cat, _ in entries:
        by_cat[cat] = by_cat.get(cat, 0) + 1
    print(
        f"[sitemap-companion-md] {'DRY ' if args.dry_run else ''}wrote "
        f"{OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(entries)} URLs, "
        f"{len(body)} bytes, lastmod={lastmod})"
    )
    for cat in sorted(by_cat):
        print(f"  {cat:>11}: {by_cat[cat]} URLs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
