"""SEO brand-history audit (revised 2026-05-13 per GEO bridge contract).

Policy split between two public surface tiers:

1. **llms.txt 系 (SEO citation bridge for AI crawlers)** — MUST carry the
   legacy brand names (税務会計AI / AutonoMath / zeimu-kaikei.ai) in the
   H1 head so LLMs that cached the prior brand can bridge to jpcite.
2. **Visible HTML + Schema.org JSON-LD** — visible HTML MUST NOT contain any
   legacy brand string. Schema.org JSON-LD may carry a tightly scoped legacy
   bridge only on WebSite/Organization alternateName and the zeimu-kaikei.ai
   sameAs URL, matching scripts/check_geo_readiness.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

SITE_DIR = Path(__file__).resolve().parent.parent / "site"

LLMS_FILES = [
    "llms.txt",
    "llms-full.txt",
    "llms.en.txt",
    "llms-full.en.txt",
]

LEGACY_TERMS = ["税務会計AI", "AutonoMath", "zeimu-kaikei.ai"]
LEGACY_BRIDGE_TYPES = {"WebSite", "Organization"}
LEGACY_BRIDGE_SAME_AS = "https://zeimu-kaikei.ai"
FORBIDDEN_LEGACY_SAME_AS = {"https://autonomath.ai"}


@pytest.mark.parametrize("fname", LLMS_FILES)
def test_llms_file_mentions_legacy_brand(fname: str) -> None:
    """Each llms.txt variant must mention all 3 legacy names + 'formerly'/'previously'."""
    path = SITE_DIR / fname
    assert path.exists(), f"{fname} missing under site/"
    text = path.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:6])
    # H1 area must carry a brand-history bridge marker.
    assert re.search(r"(formerly|previously|旧称)", head, re.IGNORECASE), (
        f"{fname} head lacks 'formerly/previously/旧称' marker:\n{head}"
    )
    for term in LEGACY_TERMS:
        assert term in head, f"{fname} head missing legacy term {term!r}:\n{head}"


def _extract_jsonld_blocks(html: str) -> list[dict[str, Any]]:
    """Pull every <script type='application/ld+json'> JSON object out of html."""
    blocks: list[dict[str, Any]] = []
    for match in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        body = match.group(1).strip()
        try:
            blocks.append(json.loads(body))
        except json.JSONDecodeError:
            continue
    return blocks


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _jsonld_type_names(block: dict[str, Any]) -> set[str]:
    value = block.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _iter_jsonld_nodes(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for block in blocks:
        nodes.append(block)
        graph = block.get("@graph")
        if isinstance(graph, list):
            nodes.extend(node for node in graph if isinstance(node, dict))
    return nodes


def _find_block(blocks: list[dict[str, Any]], type_name: str) -> dict[str, Any]:
    for b in _iter_jsonld_nodes(blocks):
        if type_name in _jsonld_type_names(b):
            return b
    raise AssertionError(f"No JSON-LD block with @type={type_name!r}")


def _legacy_jsonld_occurrences(
    value: Any, path: tuple[str, ...]
) -> list[tuple[tuple[str, ...], str]]:
    occurrences: list[tuple[tuple[str, ...], str]] = []
    if isinstance(value, str):
        for term in LEGACY_TERMS:
            if term in value:
                occurrences.append((path, term))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            occurrences.extend(_legacy_jsonld_occurrences(item, (*path, f"[{index}]")))
    elif isinstance(value, dict):
        for key, item in value.items():
            occurrences.extend(_legacy_jsonld_occurrences(item, (*path, key)))
    return occurrences


def _is_allowed_legacy_jsonld_path(
    type_names: set[str],
    path: tuple[str, ...],
    term: str,
) -> bool:
    if not type_names.intersection(LEGACY_BRIDGE_TYPES):
        return False
    if not path:
        return False
    if path[0] == "alternateName":
        return True
    return path[0] == "sameAs" and term == "zeimu-kaikei.ai"


def test_index_html_jsonld_limits_legacy_brand_bridge() -> None:
    """index.html may carry legacy brands only in the JSON-LD bridge.

    The bridge is intentionally narrow: WebSite/Organization alternateName keeps
    all prior names, and sameAs keeps only the zeimu-kaikei.ai URL. Other JSON-LD
    fields and visible HTML remain jpcite-only.
    """
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    html_without_jsonld = re.sub(
        r'<script[^>]+type="application/ld\+json"[^>]*>.*?</script>',
        "",
        html,
        flags=re.DOTALL,
    )
    for term in LEGACY_TERMS:
        assert term not in html_without_jsonld, (
            f"visible index.html must not contain legacy term {term!r}"
        )
    for url in FORBIDDEN_LEGACY_SAME_AS:
        assert url not in html, f"index.html must not contain legacy URL {url!r}"

    blocks = _extract_jsonld_blocks(html)
    assert blocks, "no JSON-LD blocks parsed from index.html"

    for node in _iter_jsonld_nodes(blocks):
        type_names = _jsonld_type_names(node)
        for path, term in _legacy_jsonld_occurrences(node, ()):
            assert _is_allowed_legacy_jsonld_path(type_names, path, term), (
                "legacy term outside the allowed WebSite/Organization JSON-LD "
                f"bridge: types={sorted(type_names)} path={'.'.join(path)} term={term!r}"
            )

    website = _find_block(blocks, "WebSite")
    assert website.get("name") not in LEGACY_TERMS, "WebSite.name must stay canonical"
    alt = _as_list(website.get("alternateName"))
    assert "jpcite" in alt, "WebSite.alternateName must keep canonical 'jpcite'"
    for term in LEGACY_TERMS:
        assert term in alt, f"WebSite.alternateName missing bridge term {term!r}: {alt}"

    same_as = _as_list(website.get("sameAs"))
    assert LEGACY_BRIDGE_SAME_AS in same_as, (
        f"WebSite.sameAs missing bridge URL {LEGACY_BRIDGE_SAME_AS!r}: {same_as}"
    )
    assert FORBIDDEN_LEGACY_SAME_AS.isdisjoint(set(same_as)), (
        f"WebSite.sameAs contains forbidden legacy URL: {same_as}"
    )

    org = _find_block(blocks, "Organization")
    assert org.get("name") not in LEGACY_TERMS, "Organization.name must not use legacy brand"
    org_alt = _as_list(org.get("alternateName"))
    assert "jpcite" in org_alt, "Organization.alternateName must keep canonical 'jpcite'"
    for term in LEGACY_TERMS:
        assert term in org_alt, (
            f"Organization.alternateName missing bridge term {term!r}: {org_alt}"
        )
    org_same = _as_list(org.get("sameAs"))
    assert LEGACY_BRIDGE_SAME_AS in org_same, (
        f"Organization.sameAs missing bridge URL {LEGACY_BRIDGE_SAME_AS!r}: {org_same}"
    )
    assert FORBIDDEN_LEGACY_SAME_AS.isdisjoint(set(org_same)), (
        f"Organization.sameAs contains forbidden legacy URL: {org_same}"
    )
