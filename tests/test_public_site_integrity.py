from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"


def _site_path_for_url(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != "jpcite.com":
        return None
    path = parsed.path or "/"
    if path.endswith("/"):
        return SITE / path.lstrip("/") / "index.html"
    if Path(path).suffix:
        return SITE / path.lstrip("/")
    return SITE / (path.lstrip("/") + ".html")


def test_jsonld_logo_and_search_action_resolve() -> None:
    payload = (SITE / "_assets" / "jsonld" / "_common.json").read_text(encoding="utf-8")
    assert "https://jpcite.com/_assets/logo.svg" not in payload
    assert "https://jpcite.com/assets/logo-v2.svg" in payload
    assert (SITE / "assets" / "logo-v2.svg").exists()
    assert "https://jpcite.com/search?q={query}" in payload
    assert (SITE / "search.html").exists()
    redirects = (SITE / "_redirects").read_text(encoding="utf-8")
    assert "/search /search.html 200" in redirects


def test_known_broken_public_links_are_not_reintroduced() -> None:
    targets = [
        SITE / "index.html",
        SITE / "pricing.html",
        SITE / "roi_calculator.html",
        *sorted((SITE / "audiences").glob("*.html")),
    ]
    banned = (
        "/docs/use_cases/by_industry_2026_05_11/",
        "/docs/pricing/justification_2026_05_11/",
        "docs/canonical/cost_saving_examples.md",
        "https://jpcite.com/device",
    )
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in text, f"{path.relative_to(REPO_ROOT)} contains {needle}"


def test_llms_full_top_search_anchors_resolve() -> None:
    text = (SITE / "llms-full.txt").read_text(encoding="utf-8")
    block = text.split("Top search keyword anchors:", 1)[1].split("---", 1)[0]
    urls = re.findall(r"`(https://jpcite.com/[^`]+)`", block)
    assert urls
    missing = []
    for url in urls:
        path = _site_path_for_url(url)
        if path is not None and not path.exists():
            missing.append(f"{url} -> {path.relative_to(REPO_ROOT)}")
    assert missing == []


def test_unneeded_noto_css_not_loaded_on_system_font_pages() -> None:
    offenders: list[str] = []
    for path in sorted(SITE.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "/static/fonts/noto-sans-jp.css" not in text:
            continue
        if "Noto Sans JP" not in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_playground_uses_external_deferred_bundle() -> None:
    text = (SITE / "playground.html").read_text(encoding="utf-8")
    assert '<script src="/assets/playground.bundle.js" defer></script>' in text
    assert "playground.html — vanilla JS controller." not in text
    assert (SITE / "assets" / "playground.bundle.js").exists()


def test_public_manifests_and_trust_pages_do_not_expose_internal_markers() -> None:
    targets = [
        REPO_ROOT / "mcp-server.json",
        REPO_ROOT / "mcp-server.full.json",
        SITE / "mcp-server.json",
        SITE / "mcp-server.full.json",
        SITE / "server.json",
        SITE / ".well-known" / "mcp.json",
        SITE / ".well-known" / "agents.json",
        SITE / "trust" / "purchasing.html",
        SITE / "security" / "index.html",
    ]
    banned = re.compile(
        r"\bmig\s+\d+\b|\bmigration\s+\d+\b|\bWave\s+\d+\b|"
        r"\bROI\b|\bARR\b|Solo zero-touch|zero-touch ops|DPA / 営業 / CS",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if match := banned.search(text):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
    assert offenders == []


def test_public_openapi_and_api_reference_hide_operational_surfaces() -> None:
    specs = [
        REPO_ROOT / "docs" / "openapi" / "v1.json",
        SITE / "docs" / "openapi" / "v1.json",
        REPO_ROOT / "docs" / "openapi" / "agent.json",
        SITE / "openapi.agent.json",
        SITE / "openapi" / "agent.json",
        SITE / "docs" / "openapi" / "agent.json",
        SITE / "openapi.agent.gpt30.json",
    ]
    hidden_paths = {
        "/v1/am/health/deep",
        "/v1/me/benchmark_vs_industry",
        "/v1/status/all",
        "/v1/status/alerts",
        "/v1/status/six_axis",
        "/v1/status/six_axis/{axis_id}/{sub_id}",
    }
    for path in specs:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "contact" not in (payload.get("info") or {}), (
            f"{path.relative_to(REPO_ROOT)} exposes spec-level contact metadata"
        )
        paths = set((payload.get("paths") or {}).keys())
        leaked = sorted(hidden_paths & paths)
        assert leaked == [], f"{path.relative_to(REPO_ROOT)} exposes {leaked}"

    public_targets = [
        REPO_ROOT / "docs" / "api-reference.md",
        SITE / "docs" / "api-reference" / "index.html",
        SITE / ".well-known" / "openapi-discovery.json",
        SITE / ".well-known" / "llms.json",
        *specs,
    ]
    banned = re.compile(
        r"/v1/am/health/deep|/v1/me/benchmark_vs_industry|"
        r"/v1/status/(?:all|alerts|six_axis)|leakage_programs|"
        r"parent/child tree|Heartbeat / deep-health|unrate-limited|"
        r"key_hash \+|scripts/check_openapi_drift|admin paths|"
        r"info@bookyou\.net|Bookyou株式会社|T8010001213708",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in public_targets:
        text = path.read_text(encoding="utf-8")
        if match := banned.search(text):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
        assert "https://api.jpcite.com/openapi.public.json" not in text, (
            f"{path.relative_to(REPO_ROOT)} references a non-live OpenAPI URL"
        )
    assert offenders == []


def test_site_ai_discovery_tool_counts_advertise_runtime_total() -> None:
    for path in (SITE / "mcp-server.json", SITE / "mcp-server.full.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert len(payload["tools"]) == 151
        assert payload["_meta"]["tool_count"] == 151
        assert payload["_meta"]["io.modelcontextprotocol.registry/publisher-provided"][
            "tool_count"
        ] == 151
        assert "151 tools" in payload["description"]
        assert "150 tools" not in payload["description"]

    agents = json.loads((SITE / ".well-known" / "agents.json").read_text(encoding="utf-8"))
    assert agents["tools_count"]["public_default"] == 151
    assert agents["tools_count"]["runtime_verified"] == 151
    assert "139" not in json.dumps(agents["tools_count"], ensure_ascii=False)
