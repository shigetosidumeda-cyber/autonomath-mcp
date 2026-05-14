#!/usr/bin/env python3
"""Generate `*.html.md` companion files next to selected HTML pages.

Wave 16 B4 — llms.txt v2 reference implementation.

What this does
--------------
For each root HTML page in `site/` that is a top-level AI-discovery surface
(index / docs root / pricing / mcp-tools / pricing / api-reference 等),
emit a sibling `*.html.md` file containing:

  1. A short YAML-ish frontmatter with: source_html, brand, canonical URL,
     fetched_at (the time this companion was generated), and an estimated
     token budget (rough char/4 heuristic — see TOKEN_DIVISOR).
  2. A Markdown rendering of the page extracted via `html.parser`:
     - <title> → H1
     - <meta name="description"> → blockquote
     - <h1>..<h6> → matching ATX heading
     - <p> / <li> → paragraphs / bullets
     - <a href="..."> → [text](href)
     - everything else (script/style/svg/nav) is stripped

The companion files let LLM indexers ingest the canonical narrative without
parsing HTML (some 2026 crawlers refuse JS-heavy pages). The token-budget
hint in the frontmatter is also surfaced in `llms.txt` so callers can size
their context window.

LLM call: 0. Pure stdlib.

Usage
-----
    python scripts/generate_companion_md.py
    python scripts/generate_companion_md.py --dry-run
    python scripts/generate_companion_md.py --pages index.html docs/index.html

Output
------
    site/<page>.html.md  (always overwritten; safe to commit)
"""

from __future__ import annotations

import argparse
import contextlib
import html
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"
CANONICAL_BASE = "https://jpcite.com"
TOKEN_DIVISOR = 4  # rough char-to-token ratio for JA-mixed Markdown

# Root pages to emit companion .md for. Keep this list curated — it is the
# llms.txt v2 surface and downstream LLM indexers will request these.
DEFAULT_PAGES: tuple[str, ...] = (
    "index.html",
    "about.html",
    "pricing.html",
    "facts.html",
    "data-licensing.html",
    "legal-fence.html",
    "transparency.html",
    "compare.html",
)

# Tags whose contents we drop entirely.
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "head"}
# Tags that emit block-level newlines.
BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "header",
    "main",
    "aside",
    "ul",
    "ol",
    "table",
    "tr",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _Md(HTMLParser):
    """Best-effort HTML → Markdown converter for our hand-written pages."""

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self._skip_depth = 0
        self._in_li = False
        self._heading: str | None = None
        self._link_href: str | None = None
        self.title: str = ""
        self.description: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attrd = dict(attrs)
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta" and attrd.get("name") == "description":
            self.description = (attrd.get("content") or "").strip()
            return
        if tag in HEADING_TAGS:
            self._heading = tag
            self._buf.append("\n" + ("#" * int(tag[1])) + " ")
            return
        if tag == "li":
            self._in_li = True
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
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in HEADING_TAGS:
            self._heading = None
            self._buf.append("\n")
            return
        if tag == "li":
            self._in_li = False
            return
        if tag == "a":
            href = self._link_href or ""
            self._link_href = None
            self._buf.append(f"]({href})")
            return
        if tag in BLOCK_TAGS:
            self._buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        text = html.unescape(data)
        # collapse runs of whitespace to single space, except keep newlines
        # at boundaries already inserted by start/end tag.
        compact = " ".join(text.split())
        if compact:
            self._buf.append(compact + " ")

    def render(self) -> str:
        body = "".join(self._buf)
        # collapse 3+ newlines to 2.
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
        return "\n".join(line.rstrip() for line in "".join(out).strip().splitlines()) + "\n"


def _build_companion(html_path: Path, site_root: Path) -> str:
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    parser = _Md()
    parser.feed(raw)
    body = parser.render()
    rel = html_path.relative_to(site_root).as_posix()
    canonical = f"{CANONICAL_BASE}/{rel}"
    est_tokens = max(1, len(body) // TOKEN_DIVISOR)
    title = parser.title.strip() or rel
    description = parser.description.strip()
    frontmatter = [
        "---",
        f"source_html: {rel}",
        "brand: jpcite",
        f"canonical: {canonical}",
        f"fetched_at: {datetime.now(UTC).isoformat()}",
        f"est_tokens: {est_tokens}",
        f"token_divisor: {TOKEN_DIVISOR}",
        "license: see https://jpcite.com/tos",
        "---",
        "",
    ]
    parts = ["\n".join(frontmatter), f"# {title}\n"]
    if description:
        parts.append(f"> {description}\n")
    parts.append(body)
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate llms.txt v2 companion .md files")
    p.add_argument(
        "--pages",
        nargs="*",
        default=list(DEFAULT_PAGES),
        help="HTML paths relative to site/ (default: 8 root pages)",
    )
    p.add_argument("--dry-run", action="store_true", help="Print stats, do not write")
    args = p.parse_args(argv)

    written = 0
    skipped = 0
    total_tokens = 0
    for rel in args.pages:
        html_path = SITE_DIR / rel
        if not html_path.is_file():
            print(f"[companion-md] skip: {rel} (not found)", file=sys.stderr)
            skipped += 1
            continue
        md_path = html_path.with_suffix(".html.md")
        content = _build_companion(html_path, SITE_DIR)
        # token-budget extracted from frontmatter
        for line in content.splitlines():
            if line.startswith("est_tokens:"):
                with contextlib.suppress(ValueError):
                    total_tokens += int(line.split(":", 1)[1].strip())
                break
        if args.dry_run:
            print(f"[companion-md] DRY {md_path.relative_to(REPO_ROOT)} ({len(content)} chars)")
            written += 1
            continue
        md_path.write_text(content, encoding="utf-8")
        written += 1
        print(f"[companion-md] wrote {md_path.relative_to(REPO_ROOT)} ({len(content)} chars)")
    print(
        f"[companion-md] done — wrote={written} skipped={skipped} est_total_tokens={total_tokens}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
