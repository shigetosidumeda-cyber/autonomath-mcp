"""Wave 46 tick5 #8 — robots.txt direct Sitemap entry for sitemap-companion-md.xml.

The companion .md sitemap (`sitemap-companion-md.xml`) is referenced from
`sitemap-index.xml`, but **older crawlers / AI bots** sometimes ignore
sitemap-index files and only honor direct `Sitemap:` directives in
robots.txt. This test gates the explicit `Sitemap:` line so the companion
.md shard is unambiguously discoverable by every conformance level of
crawler.

Read-only static file check — no FastAPI, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROBOTS_TXT = REPO_ROOT / "site" / "robots.txt"

EXPECTED_COMPANION = "https://jpcite.com/sitemap-companion-md.xml"


def _read_robots() -> str:
    assert ROBOTS_TXT.exists(), f"robots.txt missing: {ROBOTS_TXT}"
    return ROBOTS_TXT.read_text(encoding="utf-8")


def test_companion_sitemap_directly_listed() -> None:
    """`Sitemap: .../sitemap-companion-md.xml` must appear verbatim."""
    body = _read_robots()
    expected = f"Sitemap: {EXPECTED_COMPANION}"
    assert expected in body, (
        f"Direct Sitemap line for companion .md shard missing.\n"
        f"Expected line: {expected}\n"
        f"Older crawlers that ignore sitemap-index.xml will not discover "
        f"the companion .md shard without this direct entry."
    )


def test_companion_sitemap_not_duplicated() -> None:
    """The companion .md Sitemap line must appear exactly once (no duplicates)."""
    body = _read_robots()
    pattern = re.compile(
        r"^Sitemap:\s+https://jpcite\.com/sitemap-companion-md\.xml\s*$",
        re.MULTILINE,
    )
    hits = pattern.findall(body)
    assert len(hits) == 1, (
        f"Expected exactly 1 companion-md Sitemap line, found {len(hits)}. "
        "Duplicates confuse crawlers and waste crawl budget."
    )


def test_existing_sitemaps_preserved() -> None:
    """Adding companion-md must not delete pre-existing Sitemap lines.

    Wave 19+ established a 17-line Sitemap block. The Wave 46 tick5 #8 patch
    appends one new line (+1 → 18 expected) and must leave the originals
    untouched. This guards against accidental destruction during edits.
    """
    body = _read_robots()
    sitemap_lines = [
        ln.strip() for ln in body.splitlines() if ln.strip().startswith("Sitemap:")
    ]
    # Minimum: pre-existing shards we know shipped before this patch.
    required_pre_existing = [
        "https://jpcite.com/sitemap-index.xml",
        "https://jpcite.com/sitemap.xml",
        "https://jpcite.com/sitemap-programs.xml",
        "https://jpcite.com/sitemap-prefectures.xml",
        "https://jpcite.com/sitemap-llms.xml",
        "https://jpcite.com/docs/sitemap.xml",
    ]
    joined = "\n".join(sitemap_lines)
    for url in required_pre_existing:
        assert url in joined, (
            f"Pre-existing Sitemap line for {url} disappeared — "
            "destructive edit detected, see "
            "feedback_destruction_free_organization."
        )
    # Total Sitemap lines must be >= 18 (17 pre-existing + 1 new companion-md).
    assert len(sitemap_lines) >= 18, (
        f"Expected >= 18 Sitemap directives after companion-md append, "
        f"found {len(sitemap_lines)}. Lines: {sitemap_lines}"
    )
