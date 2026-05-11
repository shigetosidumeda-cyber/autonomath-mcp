"""SEO brand-history audit (revised 2026-05-11 per Wave 14 seo_health_audit).

Policy split between two surface tiers, per memory ``feedback_legacy_brand_marker``:

1. **llms.txt 系 (SEO citation bridge for AI crawlers)** — MUST carry the
   legacy brand names (税務会計AI / AutonoMath / zeimu-kaikei.ai) in the
   H1 head so LLMs that cached the prior brand can bridge to jpcite.
2. **Visible HTML + Schema.org JSON-LD** — MUST NOT contain any legacy
   brand string. Schema.org alternateName/sameAs leaks into Google
   Knowledge Graph permanently; leaving 税務会計AI / AutonoMath /
   zeimu-kaikei.ai in those fields freezes the legacy name in the KG and
   undermines the rename to jpcite (Wave 14 seo_health_audit critical
   leak finding, FIXED in audit).

Originally (W14-8) the test enforced that index.html JSON-LD ALSO carried
the legacy brand. That policy was reversed by ``feedback_legacy_brand_marker``
because Schema.org markup is a permanent Knowledge Graph signal and the
bridge purpose is better served by llms.txt only.
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
    assert re.search(r"(formerly|previously|旧称)", head, re.IGNORECASE), (
        f"{fname} head lacks 'formerly/previously/旧称' marker:\n{head}"
    )
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


def test_index_html_jsonld_excludes_legacy_brand() -> None:
    """index.html WebSite + Organization JSON-LD must NOT carry legacy brand.

    Schema.org markup permanently feeds Google Knowledge Graph; legacy brand
    names there would freeze 税務会計AI/AutonoMath/zeimu-kaikei.ai as
    alternateName forever. The SEO citation bridge purpose is served by
    llms.txt 系 (above); Schema.org must be jpcite-only.
    """
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    blocks = _extract_jsonld_blocks(html)
    assert blocks, "no JSON-LD blocks parsed from index.html"

    website = _find_block(blocks, "WebSite")
    alt = website.get("alternateName") or []
    if isinstance(alt, str):
        alt = [alt]
    assert "jpcite" in alt, "WebSite.alternateName must keep canonical 'jpcite'"
    for term in LEGACY_TERMS:
        assert term not in alt, (
            f"WebSite.alternateName must NOT contain legacy term {term!r} "
            f"(Schema.org → Knowledge Graph permanent residue): {alt}"
        )

    same_as = website.get("sameAs") or []
    for legacy_url in ("https://zeimu-kaikei.ai", "https://autonomath.ai"):
        assert legacy_url not in same_as, (
            f"WebSite.sameAs must NOT contain legacy URL {legacy_url!r}: {same_as}"
        )
    for term in LEGACY_TERMS:
        for s in same_as:
            assert term not in s, (
                f"WebSite.sameAs entry {s!r} contains legacy term {term!r}"
            )

    org = _find_block(blocks, "Organization")
    org_alt = org.get("alternateName") or []
    if isinstance(org_alt, str):
        org_alt = [org_alt]
    for term in LEGACY_TERMS:
        assert term not in org_alt, (
            f"Organization.alternateName must NOT contain legacy term {term!r}: {org_alt}"
        )
    org_same = org.get("sameAs") or []
    for legacy_url in ("https://zeimu-kaikei.ai", "https://autonomath.ai"):
        assert legacy_url not in org_same, (
            f"Organization.sameAs must NOT contain legacy URL {legacy_url!r}: {org_same}"
        )
