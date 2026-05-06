"""Verify cloudflare-rules.yaml encodes a 301 redirect from the legacy
zeimu-kaikei.ai zone to jpcite.com that preserves both the request path
and the query string.

Why a structural test (not an HTTP test):
  - cloudflare-rules.yaml is operator-applied via the Cloudflare
    dashboard; the file is the source of truth, and a real HTTP probe
    against zeimu-kaikei.ai depends on the operator having applied
    those rules to the live zone (which is precisely the manual step
    the rebrand runbook covers).
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
  - feedback_no_trademark_registration — rename-only, no TM filing
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = REPO_ROOT / "cloudflare-rules.yaml"


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
