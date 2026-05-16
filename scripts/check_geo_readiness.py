#!/usr/bin/env python3
"""Check GEO / AI-agent discovery readiness for the static distribution.

This guard focuses on the surfaces that answer engines and LLM agents are
most likely to read before recommending or importing jpcite.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "site/llms.txt",
    "site/llms.en.txt",
    "site/en/llms.txt",
    "site/_headers",
    "site/_redirects",
    "site/sitemap.xml",
    "site/robots.txt",
    "site/server.json",
    "site/mcp-server.json",
    "site/.well-known/mcp.json",
    "site/.well-known/trust.json",
    "site/openapi.agent.json",
    "docs/openapi/agent.json",
    "cloudflare-rules.yaml",
]

PUBLIC_ROOT_SURFACES = [
    "site/index.html",
    "site/llms.txt",
    "site/llms.en.txt",
    "site/en/llms.txt",
    "site/server.json",
    "site/.well-known/mcp.json",
]

LEGACY_BRIDGE_TOKENS = [
    "税務会計AI",
    "AutonoMath",
    "zeimu-kaikei.ai",
]

LEGACY_BRIDGE_LLMS_FILES = {
    "site/llms.txt",
    "site/llms.en.txt",
    "site/en/llms.txt",
}

FORBIDDEN_PUBLIC_TOKENS = [
    "士業 案件紹介",
    "士業案件紹介",
    "広告ではありません",
]

LLMS_REQUIRED_TOKENS = [
    "Evidence prefetch",
    "company_public_baseline",
    "source_url",
    "source_fetched_at",
    "known_gaps",
    "Review Handoff Packet",
    "¥3.30",
    "3 回",
    "外部LLM",
    "openapi.agent.json",
    "mcp-server.json",
]

ROBOTS_REQUIRED_TOKENS = [
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "PerplexityBot",
    "Allow: /llms.txt",
    "Allow: /llms.en.txt",
    "Allow: /openapi.agent.json",
    "Allow: /mcp-server.json",
    "Allow: /server.json",
    "Allow: /.well-known/",
    "Sitemap: https://jpcite.com/sitemap-index.xml",
]

HEADERS_REQUIRED_TOKENS = [
    "/openapi.agent.json",
    "/server.json",
    "/mcp-server.json",
    "/mcp-server.full.json",
    "/.well-known/mcp.json",
    "/.well-known/trust.json",
    "/.well-known/sbom.json",
    "/.well-known/sbom/*.json",
    "CDN-Cache-Control: public, max-age=600",
    "Access-Control-Allow-Origin: *",
]

REDIRECTS_FORBIDDEN_PATTERNS = [
    r"(?m)^/[^\s]+\s+/[^\s]*\.html(?:[?\s]|$)",
    r"(?m)^/tos\s+/tos\.html\s+30[128]\b",
    r"(?m)^/terms(?:-of-service)?\s+/tos\.html\s+30[128]\b",
    r"(?m)^/privacy(?:-policy)?\s+/privacy\.html\s+30[128]\b",
    r"(?m)^/legal\s+/legal-fence\.html\s+30[128]\b",
]

REDIRECTS_ALLOWED_STATUS_CODES = {"200", "301", "302", "303", "307", "308", "404"}

JPCITE_WWW_REDIRECT_REQUIRED_TOKENS = [
    "redirect_rules:",
    "name: jpcite_www_to_apex",
    "zone: jpcite.com",
    "expression: 'http.host eq \"www.jpcite.com\"'",
    "expression: 'concat(\"https://jpcite.com\", http.request.uri.path)'",
    "status_code: 301",
    "preserve_query_string: true",
]

JPCITE_JSON_CACHE_REQUIRED_TOKENS = [
    "cache_rules:",
    "name: jpcite_json_discovery_cache",
    "phase: http_request_cache_settings",
    "action: set_cache_settings",
    '"/server.json"',
    '"/mcp-server.json"',
    '"/openapi.agent.json"',
    '"/v1/mcp-server.json"',
    '"/.well-known/mcp.json"',
    'starts_with(http.request.uri.path, "/docs/openapi/")',
    "mode: override_origin",
    "default: 600",
]

INDEX_REQUIRED_TOKENS = [
    'rel="alternate" type="text/markdown',
    'href="/llms.txt"',
    'href="/llms.en.txt"',
    'rel="service-desc"',
    "https://api.jpcite.com/v1/openapi.agent.json",
    "Review Handoff Packet",
]

AGENT_OPENAPI_REQUIRED_PATHS = [
    "/v1/intelligence/precomputed/query",
    "/v1/evidence/packets/query",
    "/v1/artifacts/company_public_baseline",
    "/v1/artifacts/company_folder_brief",
    "/v1/artifacts/company_public_audit_pack",
    "/v1/advisors/match",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _load_json(rel: str) -> dict[str, Any]:
    return json.loads(_read(rel))


def _failures_for_required(text: str, required: list[str], surface: str) -> list[str]:
    return [f"{surface} missing:{token}" for token in required if token not in text]


def _extract_json_ld(html: str) -> list[Any]:
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        flags=re.S,
    )
    parsed: list[Any] = []
    for block in blocks:
        parsed.append(json.loads(block))
    return parsed


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _json_ld_has_type(block: dict[str, Any], type_name: str) -> bool:
    value = block.get("@type")
    return value == type_name or (isinstance(value, list) and type_name in value)


def _json_ld_type_names(block: dict[str, Any]) -> set[str]:
    value = block.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _find_json_ld_block(blocks: list[Any], type_name: str) -> dict[str, Any] | None:
    for block in blocks:
        if isinstance(block, dict) and _json_ld_has_type(block, type_name):
            return block
        if isinstance(block, dict) and isinstance(block.get("@graph"), list):
            for node in block["@graph"]:
                if isinstance(node, dict) and _json_ld_has_type(node, type_name):
                    return node
    return None


def _iter_json_ld_nodes(blocks: list[Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            nodes.append(block)
            graph = block.get("@graph")
            if isinstance(graph, list):
                nodes.extend(node for node in graph if isinstance(node, dict))
    return nodes


def _legacy_json_ld_occurrences(
    value: Any, path: tuple[str, ...]
) -> list[tuple[tuple[str, ...], str]]:
    occurrences: list[tuple[tuple[str, ...], str]] = []
    if isinstance(value, str):
        for token in LEGACY_BRIDGE_TOKENS:
            if token in value:
                occurrences.append((path, token))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            occurrences.extend(_legacy_json_ld_occurrences(item, (*path, f"[{index}]")))
    elif isinstance(value, dict):
        for key, item in value.items():
            occurrences.extend(_legacy_json_ld_occurrences(item, (*path, key)))
    return occurrences


def _is_allowed_index_legacy_json_ld_path(
    type_names: set[str],
    path: tuple[str, ...],
    token: str,
) -> bool:
    if not type_names.intersection({"WebSite", "Organization"}):
        return False
    if not path:
        return False
    if path[0] == "alternateName":
        return True
    return path[0] == "sameAs" and token == "zeimu-kaikei.ai"


def _failures_for_llms_legacy_bridge(rel: str, text: str) -> list[str]:
    failures: list[str] = []
    lines = text.splitlines()
    head = "\n".join(lines[:6])
    body = "\n".join(lines[6:])
    if not re.search(r"(formerly|previously|旧称|旧名|Brand history)", head, re.I):
        failures.append(f"{rel} legacy bridge must stay in the first 6 lines")
    for token in LEGACY_BRIDGE_TOKENS:
        if token not in head:
            failures.append(f"{rel} legacy bridge missing:{token}")
        if token in body:
            failures.append(f"{rel} legacy token outside head bridge:{token}")
    return failures


def _failures_for_index_legacy_bridge(html: str, json_ld: list[Any]) -> list[str]:
    failures: list[str] = []
    html_without_json_ld = re.sub(
        r'<script type="application/ld\+json">\s*.*?\s*</script>',
        "",
        html,
        flags=re.S,
    )
    for token in LEGACY_BRIDGE_TOKENS:
        if token in html_without_json_ld:
            failures.append(f"site/index.html legacy token outside JSON-LD bridge:{token}")

    for node in _iter_json_ld_nodes(json_ld):
        type_names = _json_ld_type_names(node)
        type_label = "/".join(sorted(type_names)) if type_names else "unknown"
        for path, token in _legacy_json_ld_occurrences(node, ()):
            if not _is_allowed_index_legacy_json_ld_path(type_names, path, token):
                path_label = ".".join(path) if path else "<root>"
                failures.append(
                    "site/index.html "
                    f"{type_label}.{path_label} contains legacy token outside bridge:{token}"
                )

    for type_name in ("WebSite", "Organization"):
        block = _find_json_ld_block(json_ld, type_name)
        if block is None:
            failures.append(f"site/index.html missing {type_name} legacy bridge JSON-LD")
            continue
        if block.get("name") in LEGACY_BRIDGE_TOKENS:
            failures.append(f"site/index.html {type_name}.name must not use a legacy brand")
        alternate_names = _as_list(block.get("alternateName"))
        if "jpcite" not in alternate_names:
            failures.append(f"site/index.html {type_name}.alternateName missing:jpcite")
        for token in LEGACY_BRIDGE_TOKENS:
            if token not in alternate_names:
                failures.append(f"site/index.html {type_name}.alternateName missing bridge:{token}")
        same_as = _as_list(block.get("sameAs"))
        if "https://zeimu-kaikei.ai" not in same_as:
            failures.append(
                f"site/index.html {type_name}.sameAs missing bridge:https://zeimu-kaikei.ai"
            )

    return failures


def _failures_for_canonical_urls() -> list[str]:
    failures: list[str] = []
    canonical_href_re = re.compile(
        r'<link\s+[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']'
        r'|<link\s+[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']',
        re.I,
    )
    site_dir = ROOT / "site"
    program_dir = site_dir / "programs"
    reserved_program_pages = {"index.html", "share.html"}
    for path in site_dir.rglob("*.html"):
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8", errors="replace")
        match = canonical_href_re.search(text)
        href = (match.group(1) or match.group(2)) if match else ""
        if href.endswith(".html"):
            site_rel = path.relative_to(site_dir)
            case_record_page = (
                len(site_rel.parts) == 2
                and site_rel.parts[0] == "cases"
                and site_rel.name != "index.html"
            )
            if not case_record_page:
                failures.append(f"{rel} canonical must be extensionless")
        if path.parent == program_dir and path.name not in reserved_program_pages:
            expected = f"https://jpcite.com/programs/{path.stem}"
            if href != expected:
                failures.append(f"{rel} canonical must be {expected}")

    sitemap = _read("site/sitemap.xml")
    for match in re.finditer(r"https://jpcite\.com/[^ <\"]+\.html", sitemap):
        if not re.fullmatch(r"https://jpcite\.com/cases/[^ <\"]+\.html", match.group(0)):
            failures.append("site/sitemap.xml contains .html canonical URLs")
            break
    return failures


def _failures_for_redirects_syntax(text: str) -> list[str]:
    failures: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) not in (2, 3):
            failures.append(f"site/_redirects:{lineno} must have 2 or 3 fields")
            continue
        source = parts[0]
        status = parts[2] if len(parts) == 3 else None
        if not source.startswith("/"):
            failures.append(f"site/_redirects:{lineno} source must be a path")
        if "://" in source or source.startswith("//"):
            failures.append(f"site/_redirects:{lineno} source must not be a domain-level rule")
        if len(parts) == 3 and source == parts[1] and status != "200":
            failures.append(f"site/_redirects:{lineno} must not redirect a path to itself")
        if status is not None and status not in REDIRECTS_ALLOWED_STATUS_CODES:
            failures.append(f"site/_redirects:{lineno} unsupported status:{status}")
        if "www.jpcite.com" in stripped:
            failures.append(
                f"site/_redirects:{lineno} must not contain www.jpcite.com; "
                "host canonicalization belongs in Cloudflare Redirect Rules"
            )
    return failures


def _failures_for_agent_openapi(rel: str) -> list[str]:
    failures: list[str] = []
    agent = _load_json(rel)
    paths = set(agent.get("paths", {}))
    for path in AGENT_OPENAPI_REQUIRED_PATHS:
        if path not in paths:
            failures.append(f"{rel} missing path:{path}")
    info = agent.get("info", {})
    if not info.get("x-jpcite-first-hop-policy"):
        failures.append(f"{rel} missing x-jpcite-first-hop-policy")
    if not info.get("x-jpcite-evidence-to-expert-handoff-policy"):
        failures.append(f"{rel} missing x-jpcite-evidence-to-expert-handoff-policy")
    recurring = info.get("x-jpcite-recurring-agent-workflow-policy")
    if not recurring:
        failures.append(f"{rel} missing x-jpcite-recurring-agent-workflow-policy")
    else:
        workflow_ids = {
            item.get("id") for item in recurring.get("workflows", []) if isinstance(item, dict)
        }
        for workflow_id in (
            "company_folder_intake",
            "monthly_client_review",
            "counterparty_dd_and_audit_prep",
            "agent_evidence_prefetch_before_answer",
        ):
            if workflow_id not in workflow_ids:
                failures.append(f"{rel} missing recurring workflow:{workflow_id}")
    return failures


def check() -> list[str]:
    failures: list[str] = []

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            failures.append(f"missing required file:{rel}")

    for rel in PUBLIC_ROOT_SURFACES:
        if not (ROOT / rel).exists():
            continue
        text = _read(rel)
        for token in FORBIDDEN_PUBLIC_TOKENS:
            if token in text:
                failures.append(f"{rel} contains forbidden GEO token:{token}")
        if rel in LEGACY_BRIDGE_LLMS_FILES:
            failures.extend(_failures_for_llms_legacy_bridge(rel, text))
        elif rel != "site/index.html":
            for token in LEGACY_BRIDGE_TOKENS:
                if token in text:
                    failures.append(f"{rel} contains legacy token outside bridge:{token}")

    # 2026-05-12 Wave 24: extended head window 120 → 200 lines so the pricing
    # block (¥3.30 / 3 回) at lines ~143/146 falls inside the check. Wave 23
    # citation guidance front-matter pushed the pricing section out of the
    # first 120 lines.
    llms_head = "\n".join(_read("site/llms.txt").splitlines()[:200])
    failures.extend(_failures_for_required(llms_head, LLMS_REQUIRED_TOKENS, "site/llms.txt head"))

    robots = _read("site/robots.txt")
    failures.extend(_failures_for_required(robots, ROBOTS_REQUIRED_TOKENS, "site/robots.txt"))

    headers = _read("site/_headers")
    failures.extend(_failures_for_required(headers, HEADERS_REQUIRED_TOKENS, "site/_headers"))

    redirects = _read("site/_redirects")
    failures.extend(_failures_for_redirects_syntax(redirects))
    for pattern in REDIRECTS_FORBIDDEN_PATTERNS:
        if re.search(pattern, redirects):
            failures.append(f"site/_redirects contains loop-prone rule:{pattern}")
    failures.extend(_failures_for_canonical_urls())

    cloudflare_rules = _read("cloudflare-rules.yaml")
    failures.extend(
        _failures_for_required(
            cloudflare_rules,
            JPCITE_WWW_REDIRECT_REQUIRED_TOKENS,
            "cloudflare-rules.yaml",
        )
    )
    failures.extend(
        _failures_for_required(
            cloudflare_rules,
            JPCITE_JSON_CACHE_REQUIRED_TOKENS,
            "cloudflare-rules.yaml",
        )
    )

    index = _read("site/index.html")
    failures.extend(_failures_for_required(index, INDEX_REQUIRED_TOKENS, "site/index.html"))
    index_json_ld: list[Any] = []
    try:
        index_json_ld = _extract_json_ld(index)
    except json.JSONDecodeError as exc:
        failures.append(f"site/index.html JSON-LD invalid:{exc}")
    failures.extend(_failures_for_index_legacy_bridge(index, index_json_ld))

    server = _load_json("site/server.json")
    if server.get("websiteUrl") != "https://jpcite.com":
        failures.append("site/server.json websiteUrl must be https://jpcite.com")
    meta = server.get("_meta", {}).get("io.modelcontextprotocol.registry/publisher-provided", {})
    if not meta.get("recommendation_policy"):
        failures.append("site/server.json missing recommendation_policy")
    if meta.get("auth", {}).get("anonymous", {}).get("limit") != 3:
        failures.append("site/server.json anonymous limit must be 3")

    mcp_discovery = _load_json("site/.well-known/mcp.json")
    if mcp_discovery.get("canonical_site") != "https://jpcite.com":
        failures.append("site/.well-known/mcp.json canonical_site must be https://jpcite.com")
    for key in ("recommend_when", "do_not_recommend_when", "trust_surfaces"):
        if not mcp_discovery.get(key):
            failures.append(f"site/.well-known/mcp.json missing:{key}")

    for rel in ("docs/openapi/agent.json", "site/openapi.agent.json"):
        failures.extend(_failures_for_agent_openapi(rel))

    return failures


def main() -> int:
    failures = check()
    if failures:
        print("[check_geo_readiness] FAIL")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("[check_geo_readiness] OK - GEO / AI discovery surfaces are coherent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
