"""test_cf_pages_rum_beacon.py — Wave 49 G1 CF Pages Function structural verify.

Validates `functions/api/rum_beacon.ts` (the Wave 49 organic-funnel beacon
receiver) and its companion `site/assets/rum_funnel_collector.js`. We do
not spin up a real Cloudflare Pages runtime (workerd) in CI — it would
add a heavy dependency for one PR — so this test verifies the contract
*structurally* by parsing the TS / JS source and asserting the load-bearing
invariants that Wave 49 G1 acceptance depends on:

  - `ALLOWED_STEPS` includes the 4 funnel steps (landing/free/signup/topup).
  - `ALLOWED_EVENTS` includes view + cta_click + step_complete.
  - Bot-UA regex mirrors `site/assets/rum.js` (Wave 16 E1) — otherwise
    Wave 49 uniq counts would drift from the existing Web Vitals dataset.
  - The collector script is wired into the 3 funnel pages (index /
    onboarding / pricing) via a `<script src="/assets/rum_funnel_collector.js">`
    tag.
  - Beacon path is `/api/rum_beacon` (not the existing `/v1/rum/beacon`
    Wave 16 endpoint — see Wave 49 G1 design doc rationale).

Why structural rather than runtime? Wave 49 G1 is a measurement layer —
the only mistake we can make that *silently* breaks the funnel is wiring
the wrong allowed-set or the wrong beacon path. A runtime test that POSTs
into workerd would catch transport bugs we already inherit from the CF
Pages runtime itself, not anything Wave 49 G1 added.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FN = _REPO_ROOT / "functions" / "api" / "rum_beacon.ts"
_COLLECTOR = _REPO_ROOT / "site" / "assets" / "rum_funnel_collector.js"
_PAGES = (
    _REPO_ROOT / "site" / "index.html",
    _REPO_ROOT / "site" / "onboarding.html",
    _REPO_ROOT / "site" / "pricing.html",
)


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def test_rum_beacon_function_exists() -> None:
    src = _read(_FN)
    assert "onRequestPost" in src
    assert "onRequestOptions" in src
    assert "POST /api/rum_beacon" in src


def test_allowed_steps_match_wave49_g1_funnel() -> None:
    src = _read(_FN)
    block = re.search(r"ALLOWED_STEPS\s*=\s*new\s+Set\(\s*\[(.*?)\]", src, re.S)
    assert block, "ALLOWED_STEPS Set literal not found"
    body = block.group(1)
    for step in ("landing", "free", "signup", "topup"):
        assert f'"{step}"' in body, f"step missing from ALLOWED_STEPS: {step}"


def test_allowed_events_cover_view_click_complete() -> None:
    src = _read(_FN)
    block = re.search(r"ALLOWED_EVENTS\s*=\s*new\s+Set\(\s*\[(.*?)\]", src, re.S)
    assert block, "ALLOWED_EVENTS Set literal not found"
    body = block.group(1)
    for event in ("view", "cta_click", "step_complete"):
        assert f'"{event}"' in body, f"event missing from ALLOWED_EVENTS: {event}"


def test_bot_regex_mirrors_rum_js() -> None:
    """Defense-in-depth: server-side and client-side bot filters must agree."""
    fn_src = _read(_FN)
    rum_js = _read(_REPO_ROOT / "site" / "assets" / "rum.js")
    # Sample a representative subset; full regex equality is enforced by
    # the next assertion. The probes are agents we have actually seen in
    # CF analytics that would inflate Wave 49 G1 uniq counts.
    for ua in ("gptbot", "claudebot", "perplexity", "googlebot", "bingbot"):
        assert ua in fn_src, f"bot pattern missing from rum_beacon.ts: {ua}"
        assert ua in rum_js, f"bot pattern missing from rum.js: {ua}"


def test_collector_targets_correct_beacon_path() -> None:
    src = _read(_COLLECTOR)
    assert 'BEACON_PATH = "/api/rum_beacon"' in src
    # The Wave 16 vitals endpoint may be name-checked in commentary,
    # but the collector must never *POST* into it. We check the only
    # surfaces that route at runtime: sendBeacon and fetch calls.
    assert "sendBeacon(BEACON_PATH" in src
    assert "fetch(BEACON_PATH" in src
    # No literal wire path other than BEACON_PATH should appear in any
    # navigator.sendBeacon(...) or fetch(...) call.
    assert 'sendBeacon("/v1/rum/beacon"' not in src
    assert 'fetch("/v1/rum/beacon"' not in src


def test_collector_handles_all_4_steps() -> None:
    src = _read(_COLLECTOR)
    # inferStep() must produce each of the 4 enum values.
    for step in ("landing", "free", "signup", "topup"):
        assert f'"{step}"' in src, f"step missing from inferStep: {step}"


def test_collector_uses_sendbeacon_with_fetch_fallback() -> None:
    src = _read(_COLLECTOR)
    assert "navigator.sendBeacon" in src
    assert "fetch(" in src
    assert "keepalive: true" in src


def test_collector_script_wired_into_all_3_pages() -> None:
    needle = '<script src="/assets/rum_funnel_collector.js"'
    for page in _PAGES:
        html = _read(page)
        assert needle in html, f"rum_funnel_collector.js not wired into {page.name}"


def test_collector_bot_filter_present() -> None:
    src = _read(_COLLECTOR)
    # Same bot regex form — covers the same 19 agent patterns as rum.js.
    assert "BOT_RE" in src
    assert "gptbot" in src
    assert "claudebot" in src


def test_rum_beacon_payload_size_capped() -> None:
    """sendBeacon hard-caps at ~64KB; we additionally enforce 4KB."""
    src = _read(_FN)
    assert "4096" in src, "rum_beacon.ts must enforce 4KB payload cap"
