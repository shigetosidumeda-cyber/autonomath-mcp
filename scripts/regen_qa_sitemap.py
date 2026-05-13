#!/usr/bin/env python3
"""Regenerate site/sitemap-qa.xml from the on-disk QA pages.

After the 2026-04-29 SEO AI-feel reduction collapsed /qa/ from 99 → 30
pages, the sitemap shipped by `generate_geo_citation_pages.py` is stale.
This standalone helper walks `site/qa/**/*.html` and emits a fresh sitemap
that mirrors the on-disk truth.

The HTML generator is unchanged because we kept the curated 30 pages as-is
(no regeneration needed) — only the sitemap shard is rewritten.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QA_DIR = REPO_ROOT / "site" / "qa"
DEFAULT_SITEMAP = REPO_ROOT / "site" / "sitemap-qa.xml"
DEFAULT_DOMAIN = "jpcite.com"

_JST = timezone(timedelta(hours=9))
LOG = logging.getLogger("regen_qa_sitemap")


def _today() -> str:
    return datetime.now(_JST).date().isoformat()


def _path_to_loc(path: Path, qa_root: Path, domain: str) -> str:
    rel = path.relative_to(qa_root.parent)  # → "qa/{section}/{name}.html"
    if rel.name == "index.html":
        # /qa/ or /qa/{section}/  (drop trailing index.html)
        url_path = "/" + str(rel.parent).replace("\\", "/") + "/"
        if url_path == "/.//":
            url_path = "/"
    else:
        url_path = "/" + str(rel).replace("\\", "/")
    return f"https://{domain}{url_path}"


def regenerate(qa_dir: Path, sitemap_path: Path, domain: str) -> int:
    files = sorted(qa_dir.rglob("*.html"))
    today = _today()
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- QA sitemap shard for jpcite.com. -->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in files:
        loc = _path_to_loc(path, qa_dir, domain)
        priority = "0.7" if path.name == "index.html" else "0.5"
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append("    <changefreq>weekly</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    sitemap_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("wrote %d entries to %s", len(files), sitemap_path)
    return len(files)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--qa-dir", default=str(DEFAULT_QA_DIR), type=Path)
    p.add_argument("--sitemap", default=str(DEFAULT_SITEMAP), type=Path)
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    regenerate(args.qa_dir, args.sitemap, args.domain)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
