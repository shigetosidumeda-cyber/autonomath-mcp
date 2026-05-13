"""Verify cloudflare-rules.yaml encodes Cloudflare Single Redirects for
canonical public hosts.

Why a structural test (not an HTTP test):
  - cloudflare-rules.yaml is operator-applied via the Cloudflare
    dashboard or scripts/ops/cloudflare_redirect.sh; the file is the
    source of truth, and a real HTTP probe depends on the operator having
    applied those rules to the live zone.
  - Asserting on the YAML structure catches regressions where a future
    edit drops `preserve_query_string`, drops a 301 -> 302 downgrade, or
    accidentally removes the `concat("https://jpcite.com", path)`
    target. Those are the failure modes that would silently break SEO
    transfer.

The optional live-HTTP probe at the bottom is wrapped in a `pytest.mark.skip`
so CI does not flake on transient Cloudflare 5xxs while still leaving
operators an opt-in way to run it locally (`pytest -k 'live_redirect' --runxfail`).

Memory references:
  - project_jpcite_rename — 6-month redirect window, target jpcite.com
  - apex/www GEO split — www.jpcite.com must be a 301 source only
  - feedback_no_trademark_registration — rename-only, no TM filing
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = REPO_ROOT / "cloudflare-rules.yaml"
PAGES_REDIRECTS_FILE = REPO_ROOT / "site" / "_redirects"


@pytest.fixture(scope="module")
def rules_doc() -> dict:
    """Parse cloudflare-rules.yaml. PyYAML is already a transitive dep
    via mkdocs; if a future minimisation drops it, switch to a hand
    parser — the file structure is shallow enough."""
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


def test_redirect_rules_block_exists(rules_doc: dict) -> None:
    """The top-level `redirect_rules` block must be present and non-empty."""
    assert "redirect_rules" in rules_doc, (
        "cloudflare-rules.yaml lost its `redirect_rules` block — the legacy "
        "zeimu-kaikei.ai 301 chain is the SEO carry-over surface for the "
        "2026-04-30 rebrand, do NOT remove without an explicit decommission "
        "decision (see project_jpcite_rename memory)."
    )
    assert isinstance(rules_doc["redirect_rules"], list)
    assert len(rules_doc["redirect_rules"]) >= 1


def test_jpcite_www_rule_is_301_to_apex(rules_doc: dict) -> None:
    """www.jpcite.com must not serve duplicate static HTML.

    The apex host is the canonical URL in JSON-LD, sitemaps, and robots.txt.
    Keeping www as a 200 splits SEO/GEO signals, so the zone-level redirect
    must preserve path/query and point every request to apex.
    """
    rule = next(
        (
            r
            for r in rules_doc["redirect_rules"]
            if r.get("zone") == "jpcite.com" and r.get("name") == "jpcite_www_to_apex"
        ),
        None,
    )
    assert rule is not None, (
        "jpcite_www_to_apex rule is missing — www.jpcite.com must 301 to "
        "apex before Cloudflare Pages serves duplicate HTML."
    )
    assert rule["action"] == "redirect"
    assert rule["expression"] == 'http.host eq "www.jpcite.com"'
    params = rule["action_parameters"]["from_value"]
    assert params["status_code"] == 301
    assert params["preserve_query_string"] is True
    assert params["target_url"]["expression"] == 'concat("https://jpcite.com", http.request.uri.path)'


def test_zeimu_kaikei_apex_rule_is_301_to_jpcite(rules_doc: dict) -> None:
    """The apex zeimu-kaikei.ai rule must:
    - target the `zeimu-kaikei.ai` zone
    - emit HTTP 301 (permanent), not 302
    - preserve the query string
    - rewrite to https://jpcite.com + original path
    """
    apex = next(
        (
            r
            for r in rules_doc["redirect_rules"]
            if r.get("zone") == "zeimu-kaikei.ai" and r.get("name") == "zeimu_kaikei_to_jpcite_apex"
        ),
        None,
    )
    assert apex is not None, (
        "zeimu_kaikei_to_jpcite_apex rule is missing — the rebrand 301 "
        "chain depends on it. Reapply the cloudflare-rules.yaml block."
    )
    assert apex["action"] == "redirect"
    params = apex["action_parameters"]["from_value"]
    assert params["status_code"] == 301, "must be 301 (permanent) for SEO carry-over"
    assert params["preserve_query_string"] is True, (
        "preserve_query_string=False would strip UTM/?ref= params from "
        "inbound campaigns and break paid-bookmark deep-links"
    )
    target_expr = params["target_url"]["expression"]
    assert "jpcite.com" in target_expr
    assert "http.request.uri.path" in target_expr, (
        "target_url must rewrite to https://jpcite.com + original path; "
        "a static target would collapse all legacy inbound links to /"
    )
    # Source matcher must cover both apex AND www
    assert 'http.host eq "zeimu-kaikei.ai"' in apex["expression"]
    assert 'http.host eq "www.zeimu-kaikei.ai"' in apex["expression"]


def test_zeimu_kaikei_indexnow_legacy_rule(rules_doc: dict) -> None:
    """The IndexNow key-file rule keeps Bing/Yandex authentication alive
    on the legacy host while their crawl caches age out."""
    rule = next(
        (
            r
            for r in rules_doc["redirect_rules"]
            if r.get("name") == "zeimu_kaikei_indexnow_key_legacy"
        ),
        None,
    )
    assert rule is not None
    assert rule["zone"] == "zeimu-kaikei.ai"
    params = rule["action_parameters"]["from_value"]
    assert params["status_code"] == 301
    assert params["preserve_query_string"] is True
    # Path matcher should target the IndexNow key-file naming convention
    assert "{32," in rule["expression"], (
        "IndexNow keys are 32+ char URL-safe tokens; pattern must reflect that"
    )


def test_legacy_host_redirects_stay_out_of_pages_redirects() -> None:
    """Host-level legacy redirects belong to Cloudflare Redirect Rules.

    Cloudflare Pages `_redirects` is path-only; putting zeimu-kaikei.ai there
    would either be ignored or become a path rule that can shadow jpcite.com
    assets.
    """
    redirects = PAGES_REDIRECTS_FILE.read_text(encoding="utf-8")
    for needle in ("zeimu-kaikei.ai", "www.zeimu-kaikei.ai"):
        assert needle not in redirects


def test_redirect_rules_do_not_match_apex_jpcite_paths(rules_doc: dict) -> None:
    """The legacy migration must not redirect canonical jpcite.com paths.

    jpcite.com path redirects are owned by site/_redirects and Pages static
    serving. Edge redirect rules may canonicalize www.jpcite.com, but they
    must not capture the apex host.
    """
    offenders: list[str] = []
    for rule in rules_doc["redirect_rules"]:
        expression = rule.get("expression", "")
        quoted_values = set(re.findall(r'"([^"]+)"', expression))
        if "jpcite.com" in quoted_values:
            offenders.append(rule.get("name", "<unnamed>"))
    assert offenders == [], (
        "Cloudflare redirect rule(s) match apex jpcite.com and could break "
        f"canonical paths: {offenders}"
    )


def test_jpcite_json_discovery_cache_rule(rules_doc: dict) -> None:
    """Public AI discovery JSON should be explicitly eligible for edge cache."""
    rule = next(
        (
            r
            for r in rules_doc.get("cache_rules", [])
            if r.get("zone") == "jpcite.com" and r.get("name") == "jpcite_json_discovery_cache"
        ),
        None,
    )
    assert rule is not None, "jpcite_json_discovery_cache rule is missing"
    assert rule["phase"] == "http_request_cache_settings"
    assert rule["action"] == "set_cache_settings"
    expression = rule["expression"]
    for needle in (
        'http.host eq "jpcite.com"',
        'http.request.method eq "GET"',
        '"/server.json"',
        '"/mcp-server.json"',
        '"/openapi.agent.json"',
        '"/v1/mcp-server.json"',
        '"/.well-known/mcp.json"',
        'starts_with(http.request.uri.path, "/docs/openapi/")',
    ):
        assert needle in expression
    params = rule["action_parameters"]
    assert params["cache"] is True
    assert params["edge_ttl"] == {"mode": "override_origin", "default": 600}
    assert params["browser_ttl"] == {"mode": "respect_origin"}


@pytest.mark.skip(
    reason=(
        "Live HTTP probe — opt-in only. Requires the operator to have "
        "applied cloudflare-rules.yaml to the zeimu-kaikei.ai zone. Run "
        "with: pytest tests/test_redirect_zeimu_kaikei.py -k live_redirect "
        "--runxfail -p no:cacheprovider"
    )
)
def test_live_redirect_smoke() -> None:
    """One-shot smoke against the live zone. Asserts URL structure only,
    not body content. Skipped in CI because the rule may not be applied
    yet at test time."""
    httpx = pytest.importorskip("httpx")
    r = httpx.get(
        "https://zeimu-kaikei.ai/programs/some-slug?ref=test",
        follow_redirects=False,
        timeout=10.0,
    )
    assert r.status_code == 301
    location = r.headers["location"]
    assert location.startswith("https://jpcite.com/")
    assert location.endswith("/programs/some-slug?ref=test"), "path + query string must round-trip"
