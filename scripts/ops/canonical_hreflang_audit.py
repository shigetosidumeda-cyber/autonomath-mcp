#!/usr/bin/env python3
"""Canonical + hreflang integrity audit for site/*.html.

Wave 14 GEO 改善 group ε. Stdlib-only (html.parser).

Walks site/, parses <link rel="canonical">, <link rel="alternate" hreflang="...">
and <meta property="og:url">, then verifies:

  1. canonical exists, is absolute (https://jpcite.com/...) and matches the
     extensionless/extension pattern expected for the page's directory.
  2. canonical = og:url (when og:url is present).
  3. hreflang ja / en / x-default integrity:
       - canonical-only pages (per-record cases/laws/enforcement etc.):
         ja + x-default both present and = canonical.
       - dual-locale pages (top-level + /en/ peer): ja + en + x-default all
         present, ja points at JA peer canonical, en points at EN peer
         canonical, x-default = ja peer.
  4. canonical does not leak legacy brand domains
     (jpintel.com / zeimu-kaikei.ai / autonomath.ai).
  5. canonical URL == sitemap <loc> for any sitemap entry whose path matches.

Exit code 0 = no violations (or report-only mode). With --strict, exit 1 on
any violation.

Usage:
    python3 scripts/ops/canonical_hreflang_audit.py             # report
    python3 scripts/ops/canonical_hreflang_audit.py --strict    # gate
    python3 scripts/ops/canonical_hreflang_audit.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

SITE_ROOT = Path(__file__).resolve().parents[2] / "site"
CANONICAL_HOST = "https://jpcite.com"
LEGACY_BRANDS = ("jpintel.com", "zeimu-kaikei.ai", "autonomath.ai")
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# Directories whose per-record pages canonicalize WITH .html suffix.
HTML_SUFFIX_DIRS = {"cases"}
# Directories whose per-record pages canonicalize WITHOUT .html suffix.
EXTENSIONLESS_DIRS = {
    "laws",
    "enforcement",
    "prefectures",
    "cities",
    "industries",
    "audiences",
    "intel",
    "blog",
    "news",
    "qa",
    "cross",
    "programs",
    "press",
    "compare",
    "connect",
    "dashboard",
    "transparency",
    "trust",
    "contribute",
    "docs",
    "integrations",
    "bench",
    "benchmark",
    "changelog",
    "security",
    "practitioner-eval",
    "status",
}
# Skip directories with templates / generated machinery / per-record indexes.
SKIP_DIR_NAMES = {
    "_assets",
    "_templates",
    "_data",
    "_headers",
    "_redirects",
    ".cursor",
    ".well-known",
    "assets",
    "audit-log.rss",
    "rss",
}
# Skip a few special files where canonical inspection is irrelevant.
SKIP_FILE_NAMES = {"404.html"}

# Filenames whose canonical INTENTIONALLY points to a different consolidated
# page (e.g. `artifact.html` → /artifacts is a name-collision redirect; `line.html`
# is consolidated into /notifications). These are accepted as-is.
CONSOLIDATED_CANONICAL_WHITELIST = {
    "artifact.html",
    "line.html",
}


class LinkExtractor(HTMLParser):
    """Pulls canonical / alternate hreflang / og:url / robots from head."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical: str | None = None
        self.hreflang: dict[str, str] = {}
        self.og_url: str | None = None
        self.html_lang: str | None = None
        self.robots: str | None = None
        self._in_body = False

    def handle_starttag(self, tag: str, attrs_raw: list[tuple[str, str | None]]) -> None:
        if self._in_body:
            return
        attrs = {k.lower(): (v or "") for k, v in attrs_raw}
        if tag == "html" and "lang" in attrs:
            self.html_lang = attrs["lang"]
        elif tag == "body":
            self._in_body = True
        elif tag == "link":
            rel = attrs.get("rel", "").strip().lower()
            href = attrs.get("href", "").strip()
            if rel == "canonical" and href and self.canonical is None:
                self.canonical = href
            elif rel == "alternate":
                hl = attrs.get("hreflang", "").strip().lower()
                if hl and hl not in self.hreflang:
                    self.hreflang[hl] = href
        elif tag == "meta":
            name = attrs.get("name", "").strip().lower()
            prop = attrs.get("property", "").strip().lower()
            content = attrs.get("content", "").strip()
            if prop == "og:url" and content and self.og_url is None:
                self.og_url = content
            if name == "robots" and content and self.robots is None:
                self.robots = content.lower()

    def is_noindex(self) -> bool:
        return bool(self.robots) and "noindex" in self.robots


def expected_canonical_for(rel_path: Path) -> str:
    """Compute expected canonical URL from filesystem path.

    Rules:
      * index.html  -> https://jpcite.com/<parent>/        (always trailing slash)
      * <dir>/<name>.html where <dir> in HTML_SUFFIX_DIRS  -> keep .html
      * <dir>/<name>.html where <dir> in EXTENSIONLESS_DIRS -> drop .html
      * top-level <name>.html                              -> drop .html (e.g. /about)
      * unknown subdirs                                    -> keep .html (safer)
    """
    parts = rel_path.parts
    if rel_path.name == "index.html":
        if len(parts) == 1:
            return f"{CANONICAL_HOST}/"
        parent = "/".join(parts[:-1])
        return f"{CANONICAL_HOST}/{parent}/"
    stem = rel_path.stem
    if len(parts) == 1:
        # top-level page (e.g. about.html, pricing.html)
        return f"{CANONICAL_HOST}/{stem}"
    top = parts[0]
    if top == "en":
        # mirror logic on EN side
        if rel_path.name == "index.html":
            inner = "/".join(parts[:-1])
            return f"{CANONICAL_HOST}/{inner}/"
        if len(parts) == 2:
            # /en/<name>.html — typically extensionless on EN side
            return f"{CANONICAL_HOST}/en/{stem}"
        sub = parts[1]
        if sub in HTML_SUFFIX_DIRS:
            inside = "/".join(parts[1:])
            return f"{CANONICAL_HOST}/en/{inside}"
        # default: extensionless
        inside = "/".join(parts[1:-1])
        return f"{CANONICAL_HOST}/en/{inside}/{stem}"
    if top in HTML_SUFFIX_DIRS:
        inside = "/".join(parts)
        return f"{CANONICAL_HOST}/{inside}"
    if top in EXTENSIONLESS_DIRS:
        inside = "/".join(parts[:-1])
        return f"{CANONICAL_HOST}/{inside}/{stem}"
    # unknown dir: keep .html as a conservative default
    inside = "/".join(parts)
    return f"{CANONICAL_HOST}/{inside}"


def has_en_peer(rel_path: Path) -> bool:
    """Return True if a parallel /en/<...> file exists for the JA page (and vice versa)."""
    parts = rel_path.parts
    if not parts:
        return False
    if parts[0] == "en":
        peer = Path(*parts[1:])
    else:
        peer = Path("en", *parts)
    return (SITE_ROOT / peer).is_file()


def is_en_page(rel_path: Path) -> bool:
    return bool(rel_path.parts) and rel_path.parts[0] == "en"


def walk_html_files() -> list[Path]:
    out: list[Path] = []
    for p in SITE_ROOT.rglob("*.html"):
        rel = p.relative_to(SITE_ROOT)
        if rel.name in SKIP_FILE_NAMES:
            continue
        if any(part in SKIP_DIR_NAMES for part in rel.parts):
            continue
        out.append(rel)
    out.sort()
    return out


def load_sitemap_locs() -> dict[str, Path]:
    """Map sitemap-loc URL -> sitemap file that contains it."""
    locs: dict[str, Path] = {}
    for sm in SITE_ROOT.glob("sitemap*.xml"):
        try:
            tree = ET.parse(sm)
        except ET.ParseError:
            continue
        for url_el in tree.iterfind(f"{SITEMAP_NS}url"):
            loc_el = url_el.find(f"{SITEMAP_NS}loc")
            if loc_el is not None and loc_el.text:
                locs[loc_el.text.strip()] = sm.relative_to(SITE_ROOT.parent)
    return locs


def audit_one(rel_path: Path, sitemap_locs: dict[str, Path]) -> list[dict[str, Any]]:
    full = SITE_ROOT / rel_path
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [{"path": str(rel_path), "code": "READ_ERROR", "detail": str(exc)}]
    head = text[:32_768]  # head is plenty
    parser = LinkExtractor()
    try:
        parser.feed(head)
    except Exception as exc:  # noqa: BLE001 — parser robustness
        return [{"path": str(rel_path), "code": "PARSE_ERROR", "detail": str(exc)}]

    violations: list[dict[str, Any]] = []

    def push(code: str, **detail: Any) -> None:
        violations.append({"path": str(rel_path), "code": code, **detail})

    # noindex pages skip every check except legacy-brand sweep and missing canonical
    # downgrade (missing is acceptable on noindex).
    noindex = parser.is_noindex()
    canonical = parser.canonical
    if not canonical:
        if not noindex:
            push("MISSING_CANONICAL")
        return violations
    if noindex:
        # accept canonical (and any drift) as-is on noindex pages.
        for legacy in LEGACY_BRANDS:
            if legacy in canonical:
                push("LEGACY_BRAND_IN_CANONICAL", canonical=canonical, brand=legacy)
        return violations
    if not canonical.startswith(CANONICAL_HOST):
        push("CANONICAL_NOT_ABSOLUTE", canonical=canonical)
    for legacy in LEGACY_BRANDS:
        if legacy in canonical:
            push("LEGACY_BRAND_IN_CANONICAL", canonical=canonical, brand=legacy)

    expected = expected_canonical_for(rel_path)
    # Consolidated-canonical pattern: pages that intentionally canonicalize to
    # a parent index (e.g. all practitioner-eval/* → /practitioner-eval/).
    # Accept any canonical that is a strict prefix of `expected` and ends in '/'.
    consolidated_to_index = (
        canonical.endswith("/")
        and canonical.startswith(CANONICAL_HOST)
        and expected.startswith(canonical.rstrip("/") + "/")
    )
    if (
        canonical != expected
        and canonical.startswith(CANONICAL_HOST)
        and not consolidated_to_index
        and rel_path.name not in CONSOLIDATED_CANONICAL_WHITELIST
    ):
        push("CANONICAL_PATH_MISMATCH", canonical=canonical, expected=expected)

    if parser.og_url and parser.og_url != canonical:
        push("OG_URL_MISMATCH", canonical=canonical, og_url=parser.og_url)

    # hreflang integrity
    en_present = is_en_page(rel_path)
    peer_present = has_en_peer(rel_path)
    en_only_page = en_present and not peer_present  # EN page with no JA peer
    if en_only_page:
        # EN-only canonical page: en + x-default both = canonical.
        expect_keys = {"en", "x-default"}
    else:
        expect_keys = {"ja", "x-default"} | ({"en"} if peer_present else set())
    actual_keys = set(parser.hreflang.keys())
    missing = expect_keys - actual_keys
    if missing:
        push(
            "HREFLANG_MISSING",
            missing=sorted(missing),
            present=sorted(actual_keys),
            has_en_peer=peer_present,
        )

    # When peer exists, both hreflang ja and hreflang en must align with the
    # respective canonicals on each side.
    if peer_present:
        ja_rel = (
            Path(*rel_path.parts[1:]) if en_present else rel_path
        )  # /en/foo -> foo, /foo -> /foo
        en_rel = rel_path if en_present else Path("en", *rel_path.parts)
        ja_canonical = expected_canonical_for(ja_rel)
        en_canonical = expected_canonical_for(en_rel)
        if "ja" in parser.hreflang and parser.hreflang["ja"] != ja_canonical:
            push(
                "HREFLANG_JA_MISMATCH",
                got=parser.hreflang["ja"],
                expected=ja_canonical,
            )
        if "en" in parser.hreflang and parser.hreflang["en"] != en_canonical:
            push(
                "HREFLANG_EN_MISMATCH",
                got=parser.hreflang["en"],
                expected=en_canonical,
            )
        if (
            "x-default" in parser.hreflang
            and parser.hreflang["x-default"] != ja_canonical
        ):
            push(
                "HREFLANG_XDEFAULT_MISMATCH",
                got=parser.hreflang["x-default"],
                expected=ja_canonical,
            )
    else:
        # canonical-only page (no peer). For EN-only pages we check en+x-default
        # equality; for JA-only pages we check ja+x-default equality.
        keys_to_check = ("en", "x-default") if en_only_page else ("ja", "x-default")
        for key in keys_to_check:
            if key in parser.hreflang and parser.hreflang[key] != canonical:
                push(
                    f"HREFLANG_{key.upper().replace('-', '_')}_NOT_CANONICAL",
                    got=parser.hreflang[key],
                    canonical=canonical,
                )

    # legacy brand sweep on all hreflang values
    for key, val in parser.hreflang.items():
        for legacy in LEGACY_BRANDS:
            if legacy in val:
                push(
                    "LEGACY_BRAND_IN_HREFLANG", hreflang=key, value=val, brand=legacy
                )

    # sitemap loc cross-check (only relevant if a sitemap mentions a URL whose
    # path matches this file). Accept trailing-slash vs non-slash equivalence
    # (mkdocs uses `/foo/` while sitemap commonly lists `/foo`).
    canonical_path = canonical.replace(CANONICAL_HOST, "")
    canonical_normalized = canonical_path.rstrip("/")
    if canonical in sitemap_locs:
        pass
    elif canonical_normalized:
        for loc in sitemap_locs:
            loc_path = loc.replace(CANONICAL_HOST, "").rstrip("/")
            if loc_path and loc_path == canonical_normalized and loc != canonical:
                # both URLs map to same resource; sitemap drift only flagged when
                # the .html stem differs (real path mismatch).
                if loc.endswith(".html") != canonical.endswith(".html"):
                    push(
                        "SITEMAP_LOC_DRIFT",
                        canonical=canonical,
                        sitemap_loc=loc,
                    )
                break

    return violations


def _violation_key(v: dict[str, Any]) -> tuple[str, str]:
    return (v.get("code", ""), v.get("path", ""))


def _abridge(values: list[Any], limit: int = 5) -> str:
    if len(values) <= limit:
        return ", ".join(str(x) for x in values)
    return ", ".join(str(x) for x in values[:limit]) + f" ... (+{len(values) - limit})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any violation found.",
    )
    ap.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write full violation list as JSON to this path.",
    )
    ap.add_argument(
        "--max-print",
        type=int,
        default=40,
        help="Max example violations to print per code (default 40).",
    )
    ap.add_argument(
        "--include-record-pages",
        action="store_true",
        help="Include per-record pages (cases/laws/enforcement) in audit. "
        "Default: included.",
    )
    args = ap.parse_args()

    files = walk_html_files()
    sitemap_locs = load_sitemap_locs()
    print(
        f"[audit] scanning {len(files)} HTML files under site/ "
        f"(sitemap entries: {len(sitemap_locs)})",
        file=sys.stderr,
    )

    all_violations: list[dict[str, Any]] = []
    for rel in files:
        all_violations.extend(audit_one(rel, sitemap_locs))

    all_violations.sort(key=_violation_key)

    # bucket by code for reporting
    by_code: dict[str, list[dict[str, Any]]] = {}
    for v in all_violations:
        by_code.setdefault(v["code"], []).append(v)

    print(f"\n=== canonical_hreflang_audit summary ===")
    print(f"scanned : {len(files)} pages")
    print(f"violations : {len(all_violations)} total across {len(by_code)} codes")
    for code in sorted(by_code):
        rows = by_code[code]
        print(f"\n[{code}] {len(rows)} occurrence(s)")
        examples = rows[: args.max_print]
        for ex in examples:
            detail_keys = [k for k in ex if k not in ("code", "path")]
            detail = ", ".join(f"{k}={ex[k]}" for k in detail_keys)
            print(f"  - {ex['path']}  {detail}")
        if len(rows) > args.max_print:
            print(f"  ... (+{len(rows) - args.max_print} more)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "scanned": len(files),
                    "violations": all_violations,
                    "by_code_count": {k: len(v) for k, v in by_code.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n[audit] full report written to {args.json}", file=sys.stderr)

    if args.strict and all_violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
