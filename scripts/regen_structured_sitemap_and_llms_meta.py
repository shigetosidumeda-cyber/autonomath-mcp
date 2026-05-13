#!/usr/bin/env python3
"""Regenerate site/sitemap-structured.xml + site/llms-meta.json (Wave 15 B5+B7).

* sitemap-structured.xml — Schema.org JSON-LD bearing URLs only (a sitemap shard
  that doubles as an AI agent "golden route"). Aggregates the cases / laws /
  enforcement-cases shards plus a small curated set of root pages that carry
  JSON-LD (about, pricing, facts, dashboard, calculator, audiences/*, et al.).
* llms-meta.json — Machine-readable index of the llms.txt cohort + 4 well-known
  discovery surfaces. Enumerates every heading anchor in llms-full.txt /
  llms-full.en.txt / llms.txt / llms.en.txt so AI agents can range-request a
  single section without re-fetching the whole 400KB+ corpus.

This generator is idempotent — re-running it overwrites the two output files
deterministically from current shard contents.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

SHARD_FILES = [
    SITE / "sitemap-cases.xml",
    SITE / "sitemap-laws.xml",
    SITE / "sitemap-enforcement-cases.xml",
]

# Curated root pages that carry Schema.org JSON-LD (verified via
# `grep -l 'application/ld+json' site/*.html site/audiences/*.html`). Treated
# as the "golden route" cohort for AI crawlers that prefer structured data.
# Excludes per-program / per-case pages — those are already in the shards.
STRUCTURED_ROOT_PAGES: list[tuple[str, str, float]] = [
    # (path, changefreq, priority)
    ("/about.html", "weekly", 0.9),
    ("/pricing.html", "weekly", 0.9),
    ("/facts.html", "weekly", 0.9),
    ("/facts.en.html", "weekly", 0.9),
    ("/dashboard.html", "daily", 0.7),
    ("/calculator.html", "monthly", 0.6),
    ("/calculator/", "monthly", 0.6),
    ("/benchmark/", "monthly", 0.6),
    ("/cases/", "weekly", 0.7),
    ("/audit-log.html", "weekly", 0.5),
    ("/advisors.html", "monthly", 0.6),
    ("/alerts.html", "monthly", 0.6),
    ("/bookmarklet.html", "monthly", 0.5),
    ("/blog/v0.3.4-release.html", "monthly", 0.5),
    ("/audiences/", "weekly", 0.8),
    ("/audiences/smb.html", "weekly", 0.8),
    ("/audiences/dev.html", "weekly", 0.8),
    ("/audiences/tax-advisor.html", "weekly", 0.8),
    ("/audiences/subsidy-consultant.html", "weekly", 0.8),
    ("/audiences/journalist.html", "weekly", 0.7),
    ("/audiences/vc.html", "weekly", 0.7),
    ("/audiences/shinkin.html", "weekly", 0.7),
    ("/audiences/shokokai.html", "weekly", 0.7),
    ("/audiences/shihoshoshi.html", "weekly", 0.7),
    ("/audiences/admin-scrivener.html", "weekly", 0.7),
    ("/audiences/construction.html", "weekly", 0.7),
    ("/audiences/manufacturing.html", "weekly", 0.7),
    ("/audiences/real_estate.html", "weekly", 0.7),
]

BASE_URL = "https://jpcite.com"
TODAY = _dt.date.today().isoformat()


def _extract_urls_from_shard(path: Path) -> list[tuple[str, str, str, str]]:
    """Return [(loc, lastmod, changefreq, priority), ...] from a sitemap shard.

    Uses ElementTree with namespace stripping so XPath stays simple. Missing
    optional fields fall back to ("monthly", "0.5") to keep the structured shard
    self-contained.
    """
    text = path.read_text(encoding="utf-8")
    # Strip namespaces inline so .//url works without a registry lookup.
    text = re.sub(r' xmlns="[^"]+"', "", text, count=1)
    root = ET.fromstring(text)
    out: list[tuple[str, str, str, str]] = []
    for url_el in root.findall("url"):
        loc_el = url_el.find("loc")
        if loc_el is None or not loc_el.text:
            continue
        lastmod_el = url_el.find("lastmod")
        cf_el = url_el.find("changefreq")
        pr_el = url_el.find("priority")
        out.append(
            (
                loc_el.text.strip(),
                (lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else TODAY),
                (cf_el.text.strip() if cf_el is not None and cf_el.text else "monthly"),
                (pr_el.text.strip() if pr_el is not None and pr_el.text else "0.5"),
            )
        )
    return out


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _enumerate_anchors(text: str) -> tuple[list[dict], int, int]:
    """Return (anchors, total_h2, total_all_levels) from a markdown body.

    Each anchor dict is {level, text, anchor, line, kind}. `kind` is
    "heading" for ATX headings (`# ... ######`) and "link_target" for
    inline citation list items (`- [Label](#anchor)`) so AI agents can
    deep-link to the same anchor IDs the document already exposes. The
    Markdown anchor convention is kebab-cased lower-snake (with Japanese
    runes retained as-is).
    """
    anchors: list[dict] = []
    h2_count = 0
    for ix, raw in enumerate(text.splitlines(), start=1):
        # Pass 1: ATX headings
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", raw)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            slug_src = title.replace("`", "").replace("/", "-").replace(":", "")
            slug = re.sub(r"\s+", "-", slug_src.strip()).lower()
            slug = re.sub(r"-+", "-", slug).strip("-")
            anchors.append(
                {
                    "level": level,
                    "text": title,
                    "anchor": slug,
                    "line": ix,
                    "kind": "heading",
                }
            )
            if level == 2:
                h2_count += 1
            continue
        # Pass 2: markdown list items with inline citations look like
        # `- [Title](URL)` — surface those as `link_target` anchors so the
        # llms.txt index entries themselves are addressable.
        link = re.match(r"^\s*-\s+\[([^\]]+)\]\(([^)]+)\)\s*$", raw)
        if link:
            label = link.group(1).strip()
            href = link.group(2).strip()
            slug_src = label.replace("`", "").replace("/", "-").replace(":", "")
            slug = re.sub(r"\s+", "-", slug_src.strip()).lower()
            slug = re.sub(r"-+", "-", slug).strip("-")
            anchors.append(
                {
                    "level": 0,
                    "text": label,
                    "anchor": slug,
                    "href": href,
                    "line": ix,
                    "kind": "link_target",
                }
            )
    return anchors, h2_count, len(anchors)


def _file_meta(path: Path, lang: str) -> dict:
    if not path.exists():
        return {
            "file": "/" + path.name,
            "lang": lang,
            "exists": False,
        }
    raw = path.read_bytes()
    if path.suffix in {".txt", ".md", ".json", ".xml"}:
        text = raw.decode("utf-8", errors="replace")
    else:
        text = ""
    anchors, h2_count, total_anchors = _enumerate_anchors(text) if text else ([], 0, 0)
    stat = path.stat()
    last_modified = _dt.datetime.utcfromtimestamp(stat.st_mtime).isoformat(timespec="seconds") + "Z"
    return {
        "file": "/" + path.name,
        "lang": lang,
        "size_bytes": stat.st_size,
        "line_count": text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0,
        "content_hash_sha256": _sha256_hex(raw),
        "last_modified": last_modified,
        "sections": h2_count,
        "anchors_total": total_anchors,
        "section_anchors": anchors,
    }


def _wellknown_meta(rel_path: str, label: str) -> dict:
    """Minimal meta for non-llms discovery surfaces (mcp / agents / ai-plugin)."""
    path = SITE / rel_path.lstrip("/")
    if not path.exists():
        return {"file": rel_path, "kind": label, "exists": False}
    raw = path.read_bytes()
    stat = path.stat()
    last_modified = _dt.datetime.utcfromtimestamp(stat.st_mtime).isoformat(timespec="seconds") + "Z"
    return {
        "file": rel_path,
        "kind": label,
        "size_bytes": stat.st_size,
        "content_hash_sha256": _sha256_hex(raw),
        "last_modified": last_modified,
    }


def build_structured_sitemap() -> tuple[str, int]:
    urls: list[tuple[str, str, str, str]] = []
    for shard in SHARD_FILES:
        urls.extend(_extract_urls_from_shard(shard))
    # Append curated root pages with JSON-LD.
    for path, cf, pr in STRUCTURED_ROOT_PAGES:
        urls.append(
            (f"{BASE_URL}{path}", TODAY, cf, f"{pr:.1f}" if isinstance(pr, float) else str(pr))
        )

    # Deterministic ordering: stable by loc to make diffs review-friendly.
    urls.sort(key=lambda r: r[0])

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        "  sitemap-structured.xml — Schema.org JSON-LD bearing URLs only.",
        "  AI agent 'golden route' shard. Aggregates per-row sitemaps (cases /",
        "  laws / enforcement-cases) plus curated root pages that carry",
        "  application/ld+json for structured-data discovery.",
        f"  Updated: {TODAY}",
        f"  URL count: {len(urls)}",
        "-->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod, cf, pr in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{cf}</changefreq>")
        lines.append(f"    <priority>{pr}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n", len(urls)


def build_llms_meta() -> tuple[dict, int]:
    llms_files = [
        _file_meta(SITE / "llms.txt", "ja"),
        _file_meta(SITE / "llms.en.txt", "en"),
        _file_meta(SITE / "llms-full.txt", "ja"),
        _file_meta(SITE / "llms-full.en.txt", "en"),
    ]
    cohort = [
        _wellknown_meta("sitemap-llms.xml", "ai_surface_sitemap"),
        _wellknown_meta(".well-known/mcp.json", "mcp_discovery"),
        _wellknown_meta(".well-known/agents.json", "agents_protocol"),
        _wellknown_meta(".well-known/ai-plugin.json", "openai_plugin"),
    ]
    total_section_anchors = sum(len(f.get("section_anchors", [])) for f in llms_files)
    payload = {
        "$schema": "https://jpcite.com/.well-known/llms-meta.schema.json",
        "spec": "llms-meta v0 (jpcite forward-looking llms.txt v2 index)",
        "spec_status": "draft — emerging community convention, not yet IETF/RFC",
        "spec_reference": "https://llmstxt.org (v1) + jpcite forward-extension",
        "publisher": "jpcite",
        "publisher_legal_entity": "Bookyou株式会社",
        "publisher_invoice_id": "T8010001213708",
        "canonical": "https://jpcite.com",
        "generated_at": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "generator": "scripts/regen_structured_sitemap_and_llms_meta.py",
        "description": (
            "Machine-readable index of the llms.txt cohort plus the 4 well-known "
            "discovery surfaces (sitemap-llms.xml, .well-known/mcp.json, agents.json, "
            "ai-plugin.json). AI agents can use this index to range-fetch a single "
            "section anchor without re-pulling the whole llms-full.txt body."
        ),
        "license": "CC BY 4.0 (this index file). Underlying program/law data: see /licensing.html.",
        "total_files": len(llms_files) + len(cohort),
        "total_section_anchors": total_section_anchors,
        "files": llms_files,
        "discovery_surfaces": cohort,
        "consumption_notes": {
            "range_request": (
                "Each section_anchor entry has a `line` field; combined with the "
                "`size_bytes` of the parent file, agents can synthesize an HTTP "
                "Range header to fetch just that anchor's body."
            ),
            "anchor_id": (
                "`anchor` is the kebab-cased slug typically derived by Markdown "
                "processors. URL form is e.g. https://jpcite.com/llms-full.txt#<anchor>."
            ),
            "freshness": (
                "`content_hash_sha256` is the canonical freshness key. Compare "
                "against the previous build to detect drift; `last_modified` is "
                "advisory and reflects filesystem mtime."
            ),
            "compat": (
                "This file is additive to llms.txt / llms-full.txt — clients that "
                "only support llms.txt v1 should keep working unchanged."
            ),
        },
    }
    return payload, total_section_anchors


def main() -> int:
    sm_xml, url_count = build_structured_sitemap()
    (SITE / "sitemap-structured.xml").write_text(sm_xml, encoding="utf-8")

    meta, anchor_count = build_llms_meta()
    (SITE / "llms-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"sitemap-structured.xml: {url_count} URLs", file=sys.stderr)
    print(
        f"llms-meta.json: {anchor_count} section_anchors across {meta['total_files']} files",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
