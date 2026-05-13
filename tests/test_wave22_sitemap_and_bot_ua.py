"""Wave 22 (2026-05-11): regression coverage for the corrected sitemap shards
and the AI-bot User-agent surface in ``site/robots.txt``.

These tests are deliberately filesystem-only — they do not touch the network or
require any FastAPI / DB fixtures. The single source of truth is the static
site under ``site/``.

Background
==========

1. **Sitemap correction (companion-Markdown).** Wave 17 generated companion
   ``.md`` URLs by enumerating every ``.html`` page. Wave 22 swapped the
   generator to ``--scan-md-only`` which walks the *actual* ``.md`` inventory
   on disk. Wave 46 also added the small root/press/legal/security companion
   surface, so this test counts the same public inventory as the generator.

2. **Sitemap shard registration.** ``scripts/sitemap_gen.py``'s
   ``KNOWN_BASENAMES`` must include ``sitemap-companion-md.xml`` so the
   discover routine picks it up and ``sitemap-index.xml`` includes a
   ``<sitemap>`` entry.

3. **Bot UA policy.** Every AI-crawler we depend on for AEO citation
   (Google-Extended / GPTBot / ChatGPT-User / OAI-SearchBot / ClaudeBot /
   anthropic-ai / PerplexityBot / CCBot / Applebot-Extended /
   Meta-ExternalAgent / Amazonbot / xAI-Crawler / cohere-ai / MistralAI-User /
   GoogleOther / Bytespider / Diffbot / YouBot / DuckAssistBot /
   Google-CloudVertexBot / DeepSeekBot) must appear as an explicit
   ``User-agent:`` line. Same applies to the AI-traffic referrers used by
   social link-preview agents (FacebookBot / facebookexternalhit /
   LinkedInBot / Twitterbot / Slackbot / Slackbot-LinkExpanding /
   TelegramBot / WhatsApp). Any silent removal here would cut us off from
   citation traffic without warning.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"
ROBOTS_PATH = SITE_DIR / "robots.txt"
SITEMAP_COMPANION_MD_PATH = SITE_DIR / "sitemap-companion-md.xml"
SITEMAP_INDEX_PATH = SITE_DIR / "sitemap-index.xml"


# ---------------------------------------------------------------------------
# 1. companion-md sitemap reflects the actual .md inventory on disk
# ---------------------------------------------------------------------------


def _count_url_tags(xml_text: str) -> int:
    return len(re.findall(r"<url>\s*<loc>", xml_text))


def _count_md_files(category_dir: Path) -> int:
    if not category_dir.is_dir():
        return 0
    return sum(
        1
        for p in category_dir.iterdir()
        if p.is_file()
        and p.suffix == ".md"
        and p.name not in {"index.md", "README.md"}
    )


def _count_root_companion_md_files() -> int:
    """Count root/press/legal/security .md files included by the generator."""
    include_globs = (
        "*.html.md",
        "press/*.md",
        "legal/*.md",
        "security/*.md",
    )
    exclude_names = {"README.md", "BRAND.md", "index.md"}
    paths = {
        p
        for pattern in include_globs
        for p in SITE_DIR.glob(pattern)
        if p.is_file() and p.name not in exclude_names
    }
    return len(paths)


def test_companion_md_sitemap_matches_disk_inventory() -> None:
    """sitemap-companion-md.xml URL count must match the on-disk .md count.

    The Wave 22 correction shifted from HTML-derived URLs to the actual .md
    inventory. Wave 46 added public root/press/legal/security .md surfaces, so
    the expected count mirrors scripts/generate_sitemap_companion_md.py.
    """
    assert SITEMAP_COMPANION_MD_PATH.is_file(), (
        f"missing {SITEMAP_COMPANION_MD_PATH}"
    )
    xml = SITEMAP_COMPANION_MD_PATH.read_text(encoding="utf-8")
    sitemap_count = _count_url_tags(xml)

    cases_count = _count_md_files(SITE_DIR / "cases")
    laws_count = _count_md_files(SITE_DIR / "laws")
    enforcement_count = _count_md_files(SITE_DIR / "enforcement")
    root_count = _count_root_companion_md_files()
    disk_count = cases_count + laws_count + enforcement_count + root_count

    assert sitemap_count == disk_count, (
        f"sitemap-companion-md.xml has {sitemap_count} URLs but disk has "
        f"{disk_count} .md files (cases={cases_count}, laws={laws_count}, "
        f"enforcement={enforcement_count}, root={root_count})"
    )

    # Hard floor — we never want this to silently regress to zero or to a
    # partial category subset.
    assert 10000 <= sitemap_count <= 11000, (
        f"sitemap-companion-md.xml URL count {sitemap_count} outside the "
        "expected 10,000-11,000 band"
    )


def test_companion_md_sitemap_uses_canonical_apex() -> None:
    """All <loc> entries must use the jpcite.com canonical apex.

    Brand-rename regression guard — the corpus was migrated from
    zeimu-kaikei.ai / autonomath.ai in April 2026; no companion-md URL
    should still point at the legacy hosts.
    """
    xml = SITEMAP_COMPANION_MD_PATH.read_text(encoding="utf-8")
    forbidden_hosts = ("zeimu-kaikei.ai", "autonomath.ai", "jpintel.com")
    for host in forbidden_hosts:
        assert host not in xml, (
            f"sitemap-companion-md.xml still references legacy host {host!r}"
        )
    # Must include the canonical apex on at least one URL.
    assert "https://jpcite.com/" in xml


def test_companion_md_sitemap_referenced_from_index() -> None:
    """sitemap-index.xml must list sitemap-companion-md.xml as a child."""
    assert SITEMAP_INDEX_PATH.is_file(), f"missing {SITEMAP_INDEX_PATH}"
    index_xml = SITEMAP_INDEX_PATH.read_text(encoding="utf-8")
    assert "sitemap-companion-md.xml" in index_xml, (
        "sitemap-index.xml does not reference sitemap-companion-md.xml — "
        "AI crawlers will not discover the companion .md URLs"
    )


# ---------------------------------------------------------------------------
# 2. KNOWN_BASENAMES carries the Wave 17 + Wave 22 surfaces
# ---------------------------------------------------------------------------


def test_known_basenames_includes_wave22_companion_md() -> None:
    """scripts/sitemap_gen.py must register the new shards.

    Without this the discover_sitemaps() routine skips them and the index is
    rebuilt without ``<sitemap>`` references.
    """
    from scripts import sitemap_gen

    required = {
        "sitemap-cases.xml",
        "sitemap-enforcement-cases.xml",
        "sitemap-laws.xml",
        "sitemap-laws-en.xml",
        "sitemap-companion-md.xml",
    }
    missing = required - set(sitemap_gen.KNOWN_BASENAMES)
    assert not missing, (
        f"scripts/sitemap_gen.py KNOWN_BASENAMES missing Wave 17/22 shards: "
        f"{sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# 3. Bot UA policy — AI crawlers we need explicit stanzas for
# ---------------------------------------------------------------------------


# AI training / answer-engine crawlers. Missing here = silently absent from
# citation surface; do NOT remove without a brand-strategy decision.
REQUIRED_AI_BOTS = (
    "Google-Extended",
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "anthropic-ai",
    "PerplexityBot",
    "CCBot",
    "Applebot-Extended",
    "Meta-ExternalAgent",
    "Amazonbot",
    "xAI-Crawler",
    "cohere-ai",
    "MistralAI-User",
    "GoogleOther",
    "Bytespider",
    "Diffbot",
    "YouBot",
    "DuckAssistBot",
    "Google-CloudVertexBot",
    "DeepSeekBot",
)

# Social link-preview bots — small but they show up in 共同通信 / 業界紙
# pre-publish flows.
REQUIRED_SOCIAL_BOTS = (
    "FacebookBot",
    "facebookexternalhit",
    "LinkedInBot",
    "Twitterbot",
    "Slackbot",
    "TelegramBot",
)


@pytest.mark.parametrize("ua", REQUIRED_AI_BOTS + REQUIRED_SOCIAL_BOTS)
def test_robots_explicitly_lists_required_bot_ua(ua: str) -> None:
    """``site/robots.txt`` must carry a ``User-agent: <name>`` stanza."""
    assert ROBOTS_PATH.is_file(), f"missing {ROBOTS_PATH}"
    text = ROBOTS_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^User-agent:\s*{re.escape(ua)}\s*$", re.MULTILINE)
    assert pattern.search(text), (
        f"site/robots.txt is missing explicit `User-agent: {ua}` stanza"
    )


def test_robots_blocks_admin_and_internal_paths_globally() -> None:
    """Sensitive paths must be ``Disallow``-ed for the wildcard agent.

    Without this any new crawler with a non-listed UA falls through to
    ``User-agent: *`` and starts hitting /admin/ + /_internal/.
    """
    text = ROBOTS_PATH.read_text(encoding="utf-8")
    # find the `User-agent: *` block and capture its rule lines
    star_block_match = re.search(
        r"^User-agent:\s*\*\s*$(.*?)(?=^User-agent:|^Sitemap:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert star_block_match, (
        "site/robots.txt has no `User-agent: *` fallback stanza — "
        "every crawler not listed earlier will get an implicit allow"
    )
    block = star_block_match.group(1)
    for path in ("/admin/", "/_internal/", "/v1/admin/"):
        assert f"Disallow: {path}" in block, (
            f"`User-agent: *` block does not Disallow {path}"
        )


def test_robots_advertises_canonical_ai_discovery_paths() -> None:
    """``robots.txt`` should explicitly Allow the AEO discovery files.

    These are the canonical paths advertised in
    ``mcp-server.json`` / ``llms.txt`` / ``.well-known/*`` — silently
    dropping them from the Allow list breaks AI-bot citation discovery.
    """
    text = ROBOTS_PATH.read_text(encoding="utf-8")
    for path in (
        "/llms.txt",
        "/llms-full.txt",
        "/openapi/v1.json",
        "/mcp-server.json",
        "/.well-known/",
    ):
        assert f"Allow: {path}" in text, (
            f"robots.txt does not advertise canonical AEO path {path}"
        )
