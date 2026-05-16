from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"

LLMS_FILES = [
    SITE / "llms.txt",
    SITE / "llms.en.txt",
    SITE / "llms-full.txt",
    SITE / "llms-full.en.txt",
]

DISCOVERY_URLS = [
    "https://jpcite.com/sitemap-llms.xml",
    "https://jpcite.com/sitemap-index.xml",
    "https://jpcite.com/robots.txt",
    "https://jpcite.com/.well-known/agents.json",
    "https://jpcite.com/.well-known/mcp.json",
    "https://jpcite.com/.well-known/llms.json",
    "https://jpcite.com/.well-known/openapi-discovery.json",
]


def test_llms_surfaces_use_current_brand_pricing_and_safe_claims() -> None:
    banned_claims = [
        re.compile(r"\bROI\b", re.IGNORECASE),
        re.compile(r"\bARR\b"),
        re.compile(
            r"\bprofit\s+(?:projection|guarantee|uplift|increase|growth)s?\b", re.IGNORECASE
        ),
        re.compile(r"\brevenue\s+guarantee\b", re.IGNORECASE),
    ]

    for path in LLMS_FILES:
        text = path.read_text(encoding="utf-8")
        head = "\n".join(text.splitlines()[:8])

        assert "current primary brand is jpcite" in head
        assert "formerly" in head or "旧称" in head
        assert "税務会計AI" in head
        assert "AutonoMath" in head
        assert "zeimu-kaikei.ai" in head

        assert "JPY 3" in text or "¥3" in text
        assert "billable unit" in text
        assert "3 requests/day/IP" in text or "3 req/日" in text

        for pattern in banned_claims:
            assert not pattern.search(text), (
                f"{path.name} contains unsafe claim pattern {pattern.pattern}"
            )


def test_llms_surfaces_advertise_obvious_crawler_discovery_links() -> None:
    for path in LLMS_FILES:
        text = path.read_text(encoding="utf-8")
        for url in DISCOVERY_URLS:
            assert url in text, f"{path.name} missing discovery URL {url}"


def test_feed_variants_expose_llm_discovery_entry() -> None:
    rss = (SITE / "feed.rss").read_text(encoding="utf-8")
    atom = (SITE / "feed.atom").read_text(encoding="utf-8")

    assert "LLM crawler discovery surfaces" in rss
    assert "https://jpcite.com/sitemap-llms.xml" in rss
    assert "LLM crawler discovery surfaces" in atom
    assert "https://jpcite.com/sitemap-llms.xml" in atom


def test_llms_hreflang_clusters_are_symmetric_in_static_sitemap() -> None:
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "xhtml": "http://www.w3.org/1999/xhtml",
    }
    root = ET.parse(SITE / "sitemap.xml").getroot()
    urls: dict[str, dict[str, str]] = {}

    for url_el in root.findall("sm:url", ns):
        loc = url_el.findtext("sm:loc", namespaces=ns)
        if not loc or "/llms" not in loc:
            continue
        alternates = {
            link.attrib["hreflang"]: link.attrib["href"]
            for link in url_el.findall("xhtml:link", ns)
        }
        urls[loc] = alternates

    assert "https://jpcite.com/en/llms.txt" not in urls
    expected = {
        "https://jpcite.com/llms.txt": {
            "ja": "https://jpcite.com/llms.txt",
            "en": "https://jpcite.com/llms.en.txt",
            "x-default": "https://jpcite.com/llms.txt",
        },
        "https://jpcite.com/llms.en.txt": {
            "ja": "https://jpcite.com/llms.txt",
            "en": "https://jpcite.com/llms.en.txt",
            "x-default": "https://jpcite.com/llms.txt",
        },
        "https://jpcite.com/llms-full.txt": {
            "ja": "https://jpcite.com/llms-full.txt",
            "en": "https://jpcite.com/llms-full.en.txt",
            "x-default": "https://jpcite.com/llms-full.txt",
        },
        "https://jpcite.com/llms-full.en.txt": {
            "ja": "https://jpcite.com/llms-full.txt",
            "en": "https://jpcite.com/llms-full.en.txt",
            "x-default": "https://jpcite.com/llms-full.txt",
        },
    }

    for loc, alternates in expected.items():
        assert urls.get(loc) == alternates


def test_llms_hash_manifest_matches_current_files() -> None:
    manifest = json.loads((SITE / ".well-known" / "llms.json").read_text(encoding="utf-8"))

    targets = {
        "llms_txt": SITE / "llms.txt",
        "llms_full_txt": SITE / "llms-full.txt",
        "llms_en_txt": SITE / "llms.en.txt",
        "llms_full_en_txt": SITE / "llms-full.en.txt",
    }
    for key, path in targets.items():
        payload = path.read_bytes()
        assert manifest["content_hash"][key] == hashlib.sha256(payload).hexdigest()
