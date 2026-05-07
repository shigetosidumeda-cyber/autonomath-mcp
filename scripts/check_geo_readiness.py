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
    "Evidence-to-Expert Handoff",
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

INDEX_REQUIRED_TOKENS = [
    'rel="alternate" type="text/markdown',
    'href="/llms.txt"',
    'href="/llms.en.txt"',
    'rel="service-desc"',
    "https://api.jpcite.com/v1/openapi.agent.json",
    "Evidence-to-Expert Handoff",
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
                failures.append(f"site/index.html {type_name}.alternateName missing:{token}")
        same_as = _as_list(block.get("sameAs"))
        if "https://zeimu-kaikei.ai" not in same_as:
            failures.append(f"site/index.html {type_name}.sameAs missing:https://zeimu-kaikei.ai")

    return failures


def _failures_for_canonical_urls() -> list[str]:
    failures: list[str] = []
    canonical_re = re.compile(r'<link rel="canonical"[^>]+https://jpcite\.com/[^">]+\.html')
    site_dir = ROOT / "site"
    for path in site_dir.rglob("*.html"):
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8", errors="replace")
        if canonical_re.search(text):
            failures.append(f"{rel} canonical must be extensionless")

    sitemap = _read("site/sitemap.xml")
    if re.search(r"https://jpcite\.com/[^ <\"]+\.html", sitemap):
        failures.append("site/sitemap.xml contains .html canonical URLs")
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

    llms_head = "\n".join(_read("site/llms.txt").splitlines()[:120])
    failures.extend(_failures_for_required(llms_head, LLMS_REQUIRED_TOKENS, "site/llms.txt head"))

    robots = _read("site/robots.txt")
    failures.extend(_failures_for_required(robots, ROBOTS_REQUIRED_TOKENS, "site/robots.txt"))

    headers = _read("site/_headers")
    failures.extend(_failures_for_required(headers, HEADERS_REQUIRED_TOKENS, "site/_headers"))

    redirects = _read("site/_redirects")
    for pattern in REDIRECTS_FORBIDDEN_PATTERNS:
        if re.search(pattern, redirects):
            failures.append(f"site/_redirects contains loop-prone rule:{pattern}")
    failures.extend(_failures_for_canonical_urls())

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

    agent = _load_json("docs/openapi/agent.json")
    paths = set(agent.get("paths", {}))
    for path in AGENT_OPENAPI_REQUIRED_PATHS:
        if path not in paths:
            failures.append(f"docs/openapi/agent.json missing path:{path}")
    info = agent.get("info", {})
    if not info.get("x-jpcite-first-hop-policy"):
        failures.append("docs/openapi/agent.json missing x-jpcite-first-hop-policy")
    if not info.get("x-jpcite-evidence-to-expert-handoff-policy"):
        failures.append(
            "docs/openapi/agent.json missing x-jpcite-evidence-to-expert-handoff-policy"
        )

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
