#!/usr/bin/env python3
"""Generate companion ``.md`` files next to every SEO HTML page.

Wave 17 AX — full-corpus companion-Markdown surface.

Scope
-----
Three corpora (≈9,964 pages total at the 2026-05-11 snapshot):

  - ``site/cases/*.html``       (2,286 採択事例, canonical `/cases/{slug}.html`)
  - ``site/laws/*.html``        (6,493 法令本文,   canonical `/laws/{slug}`)
  - ``site/enforcement/*.html`` (1,185 行政処分,   canonical `/enforcement/{slug}`)

For each HTML page we emit a sibling ``.md`` file (``site/.../foo.md``)
containing a YAML-ish frontmatter + a Markdown rendering of the
visible-narrative portion of the page. The companion file is the
GitHub-style ``url + ".md"`` surface that LLM crawlers and citation engines
ingest without parsing JS-heavy HTML.

The output URL convention is::

    HTML:  https://jpcite.com/cases/mirasapo_case_118.html
    MD:    https://jpcite.com/cases/mirasapo_case_118.md

    HTML:  https://jpcite.com/laws/abura-mataha-yugai            (no .html)
    MD:    https://jpcite.com/laws/abura-mataha-yugai.md

    HTML:  https://jpcite.com/enforcement/act-10084              (no .html)
    MD:    https://jpcite.com/enforcement/act-10084.md

On disk both pretty-URL variants live as ``{slug}.html`` next to ``{slug}.md``,
and Cloudflare Pages serves either form via static fallback. ``_headers``
declares ``text/markdown; charset=utf-8`` for ``/*.md``.

Frontmatter contract
--------------------
- ``canonical``  — absolute HTML URL (matches the page's <link rel=canonical>)
- ``lang``       — `ja` (parsed from <html lang>; defaults to `ja`)
- ``est_tokens`` — char-count // 4 heuristic (rough JA/EN mix)
- ``source_url`` — first-party government URL (extracted from JSON-LD or meta)
- ``fetched_at`` — ISO-8601 UTC timestamp of *this* companion's generation
- ``category``   — ``cases`` | ``laws`` | ``enforcement``

LLM call: 0. Pure stdlib (html.parser + re + json).

Usage
-----
    # Sample run: generate 5 .md files for smoke verification (no .md written).
    python scripts/generate_companion_md_full.py --sample 5 --dry-run

    # Full run: write all 9,964 .md files (overwrites if exists).
    python scripts/generate_companion_md_full.py

    # Single category only.
    python scripts/generate_companion_md_full.py --category laws

    # Restrict to N pages per category (handy for chunked CI runs).
    python scripts/generate_companion_md_full.py --limit-per-category 200

Exit codes
----------
0 — at least one .md written (or, in --dry-run, the plan walked cleanly)
1 — internal parse error
2 — no input files found in any category
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"
CANONICAL_BASE = "https://jpcite.com"
TOKEN_DIVISOR = 4  # rough char-to-token ratio for JA-mixed Markdown


# Per-category mapping: directory + canonical-URL builder.
# - cases:  /cases/{slug}.html   (HTML extension is part of the canonical)
# - laws / enforcement: /laws/{slug}  (no extension; pretty URL)
@dataclass(frozen=True)
class CategoryConfig:
    name: str  # cases / laws / enforcement
    dir_name: str  # site subdirectory
    canonical_has_html: bool  # True only for cases


CATEGORIES: tuple[CategoryConfig, ...] = (
    CategoryConfig(name="cases", dir_name="cases", canonical_has_html=True),
    CategoryConfig(name="laws", dir_name="laws", canonical_has_html=False),
    CategoryConfig(name="enforcement", dir_name="enforcement", canonical_has_html=False),
)


# HTML tags we strip whole.
SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}
# Tags whose content is structurally repetitive site chrome we drop.
CHROME_TAGS_WITH_CLASS = {
    "nav",  # breadcrumb
    "footer",
}
# Block tags that emit a paragraph break.
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "main", "aside",
    "ul", "ol", "table", "tr", "details", "summary",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _Md(HTMLParser):
    """Best-effort HTML→Markdown converter for jpcite SEO pages.

    Extracts:
      - <title>           -> H1
      - <meta description>-> blockquote
      - <html lang>       -> self.lang (default 'ja')
      - <h1>..<h6>        -> ATX
      - <p> / <li>        -> paragraph / bullet
      - <a href=...>      -> [text](href)

    Drops:
      - <script>/<style>/<svg>/<head>
      - <nav> (breadcrumb)
      - <footer>
    """

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self._skip_depth = 0
        self._link_href: str | None = None
        self.title: str = ""
        self.description: str = ""
        self.lang: str = "ja"
        self.first_external_src_url: str | None = None
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self.jsonld_blobs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "html":
            lang_attr = (attrd.get("lang") or "").strip()
            if lang_attr:
                self.lang = lang_attr
        if tag in SKIP_TAGS:
            if tag == "script" and (attrd.get("type") or "") == "application/ld+json":
                # Capture JSON-LD payload to surface isBasedOn / sameAs URLs.
                self._in_jsonld = True
                self._jsonld_buf = []
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in CHROME_TAGS_WITH_CLASS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            name = (attrd.get("name") or "").lower()
            if name == "description":
                self.description = (attrd.get("content") or "").strip()
            return
        if tag in HEADING_TAGS:
            self._buf.append("\n" + ("#" * int(tag[1])) + " ")
            return
        if tag == "li":
            self._buf.append("\n- ")
            return
        if tag == "a":
            self._link_href = (attrd.get("href") or "").strip() or None
            self._buf.append("[")
            return
        if tag == "br":
            self._buf.append("  \n")
            return
        if tag in BLOCK_TAGS:
            self._buf.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            if self._in_jsonld and tag == "script":
                blob = "".join(self._jsonld_buf).strip()
                if blob:
                    self.jsonld_blobs.append(blob)
                self._in_jsonld = False
                self._jsonld_buf = []
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag in CHROME_TAGS_WITH_CLASS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in HEADING_TAGS:
            self._buf.append("\n")
            return
        if tag == "a":
            href = self._link_href or ""
            self._link_href = None
            self._buf.append(f"]({href})")
            return
        if tag in BLOCK_TAGS:
            self._buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        text = html.unescape(data)
        compact = " ".join(text.split())
        if compact:
            self._buf.append(compact + " ")

    def render(self) -> str:
        body = "".join(self._buf)
        # Collapse 3+ newlines to 2.
        out: list[str] = []
        nl = 0
        for ch in body:
            if ch == "\n":
                nl += 1
                if nl > 2:
                    continue
            else:
                nl = 0
            out.append(ch)
        return "".join(out).strip() + "\n"


# Regex to pull a canonical URL from <link rel="canonical">. Faster than
# re-parsing for the 9,964 file batch path.
_CANONICAL_RE = re.compile(
    r'<link\s+rel="canonical"\s+href="([^"]+)"', re.IGNORECASE
)


def _extract_canonical(raw_html: str, fallback: str) -> str:
    m = _CANONICAL_RE.search(raw_html)
    if m:
        return m.group(1).strip()
    return fallback


def _extract_source_url(jsonld_blobs: list[str]) -> str | None:
    """Walk JSON-LD blocks for the first plausible first-party gov URL.

    Looks at: isBasedOn (case_studies), sameAs (laws), and citation.url.
    """
    for blob in jsonld_blobs:
        try:
            doc = json.loads(blob)
        except json.JSONDecodeError:
            continue
        # Some pages emit a list of @graph nodes inside one <script>.
        nodes: list[dict] = []
        if isinstance(doc, dict):
            if "@graph" in doc and isinstance(doc["@graph"], list):
                nodes = [n for n in doc["@graph"] if isinstance(n, dict)]
            else:
                nodes = [doc]
        elif isinstance(doc, list):
            nodes = [n for n in doc if isinstance(n, dict)]
        for node in nodes:
            # isBasedOn (cases): plain string URL
            ib = node.get("isBasedOn")
            if isinstance(ib, str) and ib.startswith("http"):
                return ib
            # citation.url
            cit = node.get("citation")
            if isinstance(cit, dict):
                u = cit.get("url")
                if isinstance(u, str) and u.startswith("http"):
                    return u
            # sameAs (laws): list of URLs
            sa = node.get("sameAs")
            if isinstance(sa, list):
                for u in sa:
                    if isinstance(u, str) and u.startswith("http") and "jpcite.com" not in u:
                        return u
            elif isinstance(sa, str) and sa.startswith("http") and "jpcite.com" not in sa:
                return sa
    return None


def _category_canonical(cat: CategoryConfig, slug: str) -> str:
    """Return the canonical HTML URL for a given (category, slug)."""
    if cat.canonical_has_html:
        return f"{CANONICAL_BASE}/{cat.dir_name}/{slug}.html"
    return f"{CANONICAL_BASE}/{cat.dir_name}/{slug}"


def _category_md_url(cat: CategoryConfig, slug: str) -> str:
    """Return the published .md URL (GitHub-style url + '.md')."""
    return f"{CANONICAL_BASE}/{cat.dir_name}/{slug}.md"


def _build_companion_md(
    html_path: Path, cat: CategoryConfig, fetched_at: str
) -> tuple[str, str, int]:
    """Render a single .md companion. Returns (content, md_url, est_tokens)."""
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    parser = _Md()
    parser.feed(raw)
    body = parser.render()
    slug = html_path.stem
    canonical = _extract_canonical(raw, _category_canonical(cat, slug))
    md_url = _category_md_url(cat, slug)
    source_url = _extract_source_url(parser.jsonld_blobs)
    est_tokens = max(1, len(body) // TOKEN_DIVISOR)
    title = parser.title.strip() or slug
    description = parser.description.strip()
    lang = parser.lang.strip() or "ja"

    frontmatter_lines = [
        "---",
        f"canonical: {canonical}",
        f"md_url: {md_url}",
        f"lang: {lang}",
        f"category: {cat.name}",
        f"slug: {slug}",
        f"est_tokens: {est_tokens}",
        f"token_divisor: {TOKEN_DIVISOR}",
        f"fetched_at: {fetched_at}",
        "brand: jpcite",
        "operator: Bookyou株式会社",
        "license: see https://jpcite.com/tos",
    ]
    if source_url:
        frontmatter_lines.append(f"source_url: {source_url}")
    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    parts = ["\n".join(frontmatter_lines), f"# {title}\n"]
    if description:
        parts.append(f"> {description}\n")
    parts.append(body)
    return "\n".join(parts), md_url, est_tokens


def _list_html_files(cat: CategoryConfig) -> list[Path]:
    """Return sorted list of .html files in a category (excluding index.html)."""
    cat_dir = SITE_DIR / cat.dir_name
    if not cat_dir.is_dir():
        return []
    return sorted(
        p
        for p in cat_dir.iterdir()
        if p.is_file() and p.suffix == ".html" and p.name != "index.html"
    )


def _md_path_for(html_path: Path) -> Path:
    """Return the .md sibling next to an .html file (replaces .html with .md)."""
    return html_path.with_suffix(".md")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate Wave 17 AX companion .md files")
    p.add_argument(
        "--category",
        choices=[c.name for c in CATEGORIES] + ["all"],
        default="all",
        help="Limit to one category (default: all 3).",
    )
    p.add_argument(
        "--limit-per-category",
        type=int,
        default=0,
        help="Cap number of files processed per category (0 = no cap).",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Smoke-mode: render N files total across categories and print stats.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Render in memory but do not write .md files.",
    )
    args = p.parse_args(argv)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    selected = (
        [c for c in CATEGORIES if c.name == args.category]
        if args.category != "all"
        else list(CATEGORIES)
    )

    total_html = 0
    written = 0
    skipped = 0
    total_tokens = 0
    sample_emitted = 0
    per_cat_counts: dict[str, dict[str, int]] = {}

    for cat in selected:
        files = _list_html_files(cat)
        if args.limit_per_category:
            files = files[: args.limit_per_category]
        per_cat_counts[cat.name] = {"html": len(files), "written": 0, "skipped": 0}
        total_html += len(files)
        for html_path in files:
            if args.sample and sample_emitted >= args.sample:
                break
            try:
                content, md_url, est_tokens = _build_companion_md(
                    html_path, cat, fetched_at
                )
            except Exception as exc:  # noqa: BLE001 -- surface parse error
                sys.stderr.write(
                    f"[companion-md-full] parse error: {html_path}: {exc}\n"
                )
                skipped += 1
                per_cat_counts[cat.name]["skipped"] += 1
                continue
            md_path = _md_path_for(html_path)
            total_tokens += est_tokens
            if args.dry_run or args.sample:
                if args.sample:
                    print(
                        f"[companion-md-full] SAMPLE {md_path.relative_to(REPO_ROOT)} "
                        f"({len(content)} chars, est_tokens={est_tokens}, "
                        f"md_url={md_url})"
                    )
                    sample_emitted += 1
                written += 1
                per_cat_counts[cat.name]["written"] += 1
                continue
            md_path.write_text(content, encoding="utf-8")
            written += 1
            per_cat_counts[cat.name]["written"] += 1
        if args.sample and sample_emitted >= args.sample:
            break

    print(
        "[companion-md-full] done — total_html={th} written={w} skipped={s} "
        "est_total_tokens={t}".format(
            th=total_html, w=written, s=skipped, t=total_tokens
        )
    )
    for name, counts in per_cat_counts.items():
        print(
            f"  {name:>11}: html={counts['html']} "
            f"written={counts['written']} skipped={counts['skipped']}"
        )
    if total_html == 0:
        sys.stderr.write("[companion-md-full] no input HTML found in any category\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
