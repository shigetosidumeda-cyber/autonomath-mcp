"""W14-8 SEO brand-history audit.

Ensures all 4 llms.txt variants and index.html JSON-LD carry the legacy
brand names (税務会計AI / AutonoMath / zeimu-kaikei.ai) so AI agents can
bridge from old citations to the new jpcite brand.

Background: W14-8 audit found AI cited 0/60 because the 4 llms files +
index.html lacked any mention of the prior brand, so LLMs that had cached
the legacy name could not connect it back to the renamed product.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).resolve().parent.parent / "site"

LLMS_FILES = [
    "llms.txt",
    "llms-full.txt",
    "llms.en.txt",
    "llms-full.en.txt",
]

LEGACY_TERMS = ["税務会計AI", "AutonoMath", "zeimu-kaikei.ai"]


@pytest.mark.parametrize("fname", LLMS_FILES)
def test_llms_file_mentions_legacy_brand(fname: str) -> None:
    """Each llms.txt variant must mention all 3 legacy names + 'formerly'/'previously'."""
    path = SITE_DIR / fname
    assert path.exists(), f"{fname} missing under site/"
    text = path.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:6])
    # H1 area must carry a brand-history bridge marker.
    assert re.search(
        r"(formerly|previously|旧称)", head, re.IGNORECASE
    ), f"{fname} head lacks 'formerly/previously/旧称' marker:\n{head}"
    for term in LEGACY_TERMS:
        assert term in head, f"{fname} head missing legacy term {term!r}:\n{head}"


def _extract_jsonld_blocks(html: str) -> list[dict]:
    """Pull every <script type='application/ld+json'> JSON object out of html."""
    blocks: list[dict] = []
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


def _find_block(blocks: list[dict], type_name: str) -> dict:
    for b in blocks:
        if b.get("@type") == type_name:
            return b
    raise AssertionError(f"No JSON-LD block with @type={type_name!r}")


def test_index_html_jsonld_carries_legacy_brand() -> None:
    """index.html WebSite + Organization JSON-LD must list every legacy name."""
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    blocks = _extract_jsonld_blocks(html)
    assert blocks, "no JSON-LD blocks parsed from index.html"

    website = _find_block(blocks, "WebSite")
    alt = website.get("alternateName") or []
    assert isinstance(alt, list), "WebSite.alternateName must be a list"
    for term in LEGACY_TERMS:
        assert term in alt, f"WebSite.alternateName missing {term!r}: {alt}"
    assert "jpcite" in alt, "WebSite.alternateName must keep canonical 'jpcite'"
    # 4 entries minimum (jpcite + 3 legacy).
    assert len(alt) >= 4, f"WebSite.alternateName needs >=4 entries (jpcite + 3 legacy), got {alt}"

    same_as = website.get("sameAs") or []
    assert (
        "https://zeimu-kaikei.ai" in same_as
    ), f"WebSite.sameAs missing zeimu-kaikei.ai: {same_as}"

    org = _find_block(blocks, "Organization")
    org_alt = org.get("alternateName") or []
    for term in LEGACY_TERMS:
        assert term in org_alt, f"Organization.alternateName missing {term!r}: {org_alt}"
    org_same = org.get("sameAs") or []
    assert (
        "https://zeimu-kaikei.ai" in org_same
    ), f"Organization.sameAs missing zeimu-kaikei.ai: {org_same}"
    assert any(
        "autonomath-mcp" in s for s in org_same
    ), f"Organization.sameAs missing autonomath-mcp PyPI/GitHub link: {org_same}"
    assert any(
        "project/jpcite" in s for s in org_same
    ), f"Organization.sameAs missing jpcite PyPI link: {org_same}"
