#!/usr/bin/env python3
"""Regenerate site/sitemap-structured.xml + site/llms-meta.json (Wave 15 B5+B7).

* sitemap-structured.xml — Schema.org JSON-LD bearing URLs only (a sitemap shard
  that doubles as an AI agent "golden route"). Aggregates the cases / laws /
  enforcement-cases shards plus a small curated set of root pages that carry
  JSON-LD (about, pricing, facts, dashboard, calculator, audiences/*, et al.).
* llms-meta.json — Machine-readable index of 4 llms.txt cohort files plus
  4 well-known discovery surfaces. Enumerates every heading anchor in llms-full.txt /
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
    ("/pricing", "weekly", 0.9),
    ("/products", "weekly", 0.9),
    ("/connect/", "weekly", 0.8),
    ("/prompts/", "weekly", 0.8),
    ("/facts.html", "weekly", 0.9),
    ("/calculator.html", "monthly", 0.6),
    ("/calculator/", "monthly", 0.6),
    ("/benchmark/", "monthly", 0.6),
    ("/cases/", "weekly", 0.7),
    ("/audit-log.html", "weekly", 0.5),
    ("/advisors.html", "monthly", 0.6),
    ("/alerts.html", "monthly", 0.6),
    ("/bookmarklet.html", "monthly", 0.5),
    ("/blog/v0.3.4-release", "monthly", 0.5),
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


def _md5_hex(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _utc_iso_from_timestamp(timestamp: float) -> str:
    return (
        _dt.datetime.fromtimestamp(timestamp, _dt.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    last_modified = _utc_iso_from_timestamp(stat.st_mtime)
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
    last_modified = _utc_iso_from_timestamp(stat.st_mtime)
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
        "generated_at": _utc_now_iso(),
        "generator": "scripts/regen_structured_sitemap_and_llms_meta.py",
        "description": (
            "Machine-readable index of 4 llms.txt cohort files plus 4 well-known "
            "discovery surfaces (sitemap-llms.xml, .well-known/mcp.json, agents.json, "
            "ai-plugin.json). AI agents can use this index to range-fetch a single "
            "section anchor without re-pulling the whole llms-full.txt body."
        ),
        "license": "CC BY 4.0 (this index file). Underlying program/law data: see /data-licensing.html.",
        "total_files": len(llms_files),
        "total_discovery_surfaces": len(cohort),
        "total_indexed_surfaces": len(llms_files) + len(cohort),
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


def sync_llms_well_known_hashes() -> None:
    manifest_path = SITE / ".well-known" / "llms.json"
    if not manifest_path.exists():
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = {
        "llms_txt": SITE / "llms.txt",
        "llms_full_txt": SITE / "llms-full.txt",
        "llms_en_txt": SITE / "llms.en.txt",
        "llms_full_en_txt": SITE / "llms-full.en.txt",
    }
    content_hash = manifest.setdefault("content_hash", {})
    content_hash["algorithm"] = "sha256"
    content_hash_md5 = manifest.setdefault("content_hash_md5", {})
    content_hash_md5["algorithm"] = "md5"
    for key, path in targets.items():
        raw = path.read_bytes()
        content_hash[key] = _sha256_hex(raw)
        content_hash_md5[key] = _md5_hex(raw)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sync_agents_discovery_counts() -> None:
    agents_path = SITE / ".well-known" / "agents.json"
    mcp_path = SITE / "mcp-server.json"
    if not agents_path.exists() or not mcp_path.exists():
        return

    agents = json.loads(agents_path.read_text(encoding="utf-8"))
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    tool_count = len(mcp.get("tools") or [])
    tools_count = agents.setdefault("tools_count", {})
    tools_count["public_default"] = tool_count
    tools_count["runtime_verified"] = tool_count
    tools_count["note"] = f"Public MCP manifests advertise {tool_count} tools."
    agents_path.write_text(
        json.dumps(agents, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sync_openapi_discovery() -> None:
    discovery_path = SITE / ".well-known" / "openapi-discovery.json"
    if not discovery_path.exists():
        return

    discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
    tiers = {
        "full": SITE / "docs" / "openapi" / "v1.json",
        "agent": SITE / "openapi.agent.json",
        "gpt30": SITE / "openapi.agent.gpt30.json",
    }
    for tier in discovery.get("tiers") or []:
        if not isinstance(tier, dict):
            continue
        spec_path = tiers.get(str(tier.get("tier")))
        if spec_path is None or not spec_path.exists():
            continue
        spec_text = spec_path.read_text(encoding="utf-8")
        spec = json.loads(spec_text)
        tier["path_count"] = len(spec.get("paths") or {})
        tier["size_bytes"] = spec_path.stat().st_size
        tier["sha256_prefix"] = _sha256_hex(spec_text.encode("utf-8"))[:16]

    if isinstance(discovery.get("snapshot_at"), str):
        discovery["snapshot_at"] = "2026-05-15"
    discovery_path.write_text(
        json.dumps(discovery, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sync_visible_runtime_counts() -> None:
    counts_path = SITE / "_data" / "public_counts.json"
    full_openapi_path = SITE / "docs" / "openapi" / "v1.json"
    if not counts_path.exists() or not full_openapi_path.exists():
        return

    counts = json.loads(counts_path.read_text(encoding="utf-8"))
    tool_count = int(counts.get("mcp_tools_total", 0) or 0)
    path_count = len(json.loads(full_openapi_path.read_text(encoding="utf-8")).get("paths") or {})
    replacements: dict[Path, tuple[tuple[str, str], ...]] = {
        SITE / "about.html": (
            (
                r'<span class="num">\d+</span><span class="lbl">AI から呼べる MCP ツール</span>',
                f'<span class="num">{tool_count}</span><span class="lbl">AI から呼べる MCP ツール</span>',
            ),
            (
                r'<span class="num">\d+</span><span class="lbl">REST paths \(OpenAPI\)</span>',
                f'<span class="num">{path_count}</span><span class="lbl">REST paths (OpenAPI)</span>',
            ),
        ),
        SITE / "about.html.md": (
            (r"- \d+ AI から呼べる MCP ツール", f"- {tool_count} AI から呼べる MCP ツール"),
        ),
        SITE / "facts.html": (
            (r"MCP 機能数: \d+", f"MCP 機能数: {tool_count}"),
            (r"既定で \d+ 機能", f"既定で {tool_count} 機能"),
            (r"public runtime cohort=\d+", f"public runtime cohort={tool_count}"),
        ),
        SITE / "facts.html.md": (
            (r"MCP 機能数: \d+", f"MCP 機能数: {tool_count}"),
            (r"既定で \d+ 機能", f"既定で {tool_count} 機能"),
            (r"public runtime cohort=\d+", f"public runtime cohort={tool_count}"),
        ),
        SITE / "playground.html": (
            (
                r'"endpoint_catalog_paths", "value": \d+',
                f'"endpoint_catalog_paths", "value": {path_count}',
            ),
        ),
    }
    for path, rules in replacements.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, replacement in rules:
            text = re.sub(pattern, replacement, text)
        path.write_text(text, encoding="utf-8")


def main() -> int:
    sm_xml, url_count = build_structured_sitemap()
    (SITE / "sitemap-structured.xml").write_text(sm_xml, encoding="utf-8")

    meta, anchor_count = build_llms_meta()
    (SITE / "llms-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sync_llms_well_known_hashes()
    sync_agents_discovery_counts()
    sync_openapi_discovery()
    sync_visible_runtime_counts()

    print(f"sitemap-structured.xml: {url_count} URLs", file=sys.stderr)
    print(
        "llms-meta.json: "
        f"{anchor_count} section_anchors across {meta['total_files']} llms files "
        f"+ {meta['total_discovery_surfaces']} discovery surfaces",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
