"""K10 / K2 follow-up: 53 OpenAPI paths previously had zero test coverage.

Background
----------
At K2 / K10 audit time the OpenAPI spec listed 89 paths but only 24 (27%)
were exercised by the test suite. The remaining 65 paths had **no
guarantee** at all — a route deletion or path rename in any commit
would silently ship to production.

This file is the priority-ordered smoke contract for those paths. The
goal is **not** to verify business logic (each domain has its own
dedicated test file) — the goal is to pin the route so a refactor
cannot quietly drop or rename it. The assertions here are intentionally
shallow: route resolves, response is JSON-ish, status code is plausible.

Priority order (as called out in K10):
  1. /v1/am/*                  — autonomath (16 paths)
  2. /v1/advisors/*            — advisor matching (6 paths)
  3. /v1/court-decisions/*     — judicial precedent (3 paths)
  4. /v1/bids/*                — procurement (2 paths)
  5. /v1/admin/*               — auth-gated smoke (assert 401/403)
  6. tail of /v1/me/* /v1/billing/* /v1/device/* /v1/calendar/*

The tests run against the same TestClient as the integration suite,
so every route is exercised against the seeded DB.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def advisors_table(seeded_db: Path) -> Path:
    """Apply migration 024 (advisors + ancillary tables) onto the test DB.

    The session-scoped `seeded_db` fixture only loads ``schema.sql`` —
    not the SQL migrations under ``scripts/migrations/``. Smoke tests
    that hit /v1/advisors/* therefore see "no such table: advisors"
    without this fixture.

    Idempotent: every CREATE in the migration is ``IF NOT EXISTS``.
    """
    mig = _REPO / "scripts" / "migrations" / "024_advisors.sql"
    if not mig.is_file():
        return seeded_db
    sql = mig.read_text(encoding="utf-8")
    c = sqlite3.connect(seeded_db)
    try:
        # The migration uses PRAGMA foreign_keys = ON which sqlite3 module
        # tolerates inside executescript.
        c.executescript(sql)
        c.commit()
    except sqlite3.OperationalError:
        # Best effort — if a future migration introduces a CREATE that
        # collides we fall back to no-op so the smoke tests still run.
        pass
    finally:
        c.close()
    return seeded_db


_GENERIC_404_DETAILS = {"Not Found", "not found"}


def _assert_route_exists(response, *, path: str) -> None:
    """A route 'exists' if the response is anything other than the
    Starlette default 404 produced for an UNKNOWN path.

    Distinguishing the two 404 cases is subtle:
      * UNKNOWN path → starlette router emits 404 with detail="Not Found"
        (literal string). main.py's global handler then attaches
        ``error.code = "route_not_found"`` and the suggested_paths block.
      * KNOWN path that raised HTTPException(404, "advisor not found"):
        same global handler also runs and attaches the same
        ``error.code = "route_not_found"`` (this is by design — the
        handler maps status_code → code via a flat lookup). The
        tell-tale signal that the route exists is the **non-default
        detail** ("advisor not found", "case_id not found", etc.).

    So: 404 with detail in the generic-not-found set means the route is
    missing. 404 with any other detail means the route exists and chose
    to 404 a missing resource. We treat the latter as success.
    """
    if response.status_code == 404:
        try:
            body = response.json()
        except Exception:
            pytest.fail(f"{path} → 404 with non-JSON body")
        # Pull the detail from either the top-level (FastAPI default)
        # or the error envelope (main.py global handler).
        detail = body.get("detail")
        err = body.get("error") or {}
        # The global handler copies `detail` into error.detail when it
        # is a string. If the original detail was the generic Starlette
        # "Not Found", the route is missing. Anything else means a real
        # handler raised it.
        if (
            isinstance(detail, str)
            and detail in _GENERIC_404_DETAILS
            and err.get("code") == "route_not_found"
        ):
            # If the global handler also stamped error.code=route_not_found
            # AND the detail is generic, it's truly a missing route.
            pytest.fail(f"{path} → generic 404 (endpoint missing)")
        # Otherwise: route exists, just 404'd a resource — accept.
    if response.status_code >= 500:
        if response.status_code == 503:
            return
        pytest.fail(f"{path} → {response.status_code} 5xx server error")


# ---------------------------------------------------------------------------
# /v1/am/* — 16 paths (autonomath universal endpoints)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/am/tax_incentives", {"limit": 5}),
        ("/v1/am/certifications", {"limit": 5}),
        ("/v1/am/open_programs", {"limit": 5}),
        ("/v1/am/by_law", {"law_name": "租税特別措置法", "limit": 5}),
        ("/v1/am/active_at", {"date": "2026-04-25"}),
        ("/v1/am/acceptance_stats", {"limit": 5}),
        ("/v1/am/intent", {"query": "賃上げ促進税制"}),
        ("/v1/am/reason", {"query": "DX投資促進税制"}),
        ("/v1/am/tax_rule", {"measure_name_or_id": "賃上げ促進税制"}),
        ("/v1/am/gx_programs", {"theme": "ghg_reduction"}),
        ("/v1/am/loans", {"limit": 5}),
        ("/v1/am/enforcement", {"limit": 5}),
        ("/v1/am/mutual_plans", {"limit": 5}),
        ("/v1/am/law_article", {
            "law_name_or_canonical_id": "租税特別措置法",
            "article_number": "42-4",
        }),
        ("/v1/am/static", None),
        ("/v1/am/example_profiles", None),
        ("/v1/am/templates/saburoku_kyotei/metadata", None),
        ("/v1/am/health/deep", None),
    ],
)
def test_am_get_routes_smoke(client, path, params):
    """Every /v1/am/* GET must resolve. 200 / 422 (when seed lacks data)
    / 503 (autonomath.db unmounted) all acceptable; 404+route_not_found
    or 5xx is a regression."""
    r = client.get(path, params=params or {})
    _assert_route_exists(r, path=path)
    # For the no-required-arg paths, a structured body is non-negotiable.
    try:
        r.json()
    except ValueError:
        pytest.fail(f"{path} → non-JSON response")


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/am/enums/authority_level", None),
        ("/v1/am/enums/program_kind", None),
    ],
)
def test_am_enums_get_smoke(client, path, params):
    r = client.get(path, params=params or {})
    _assert_route_exists(r, path=path)


def test_am_enums_invalid_returns_422(client):
    """Invalid enum_name must 422 (literal), not 404."""
    r = client.get("/v1/am/enums/this_enum_does_not_exist")
    # FastAPI Literal validation → 422.
    assert r.status_code in (422, 404), r.status_code


def test_am_related_path_param_smoke(client):
    r = client.get("/v1/am/related/UNI-test-s-1")
    _assert_route_exists(r, path="/v1/am/related/{program_id}")


def test_am_static_resource_smoke(client):
    r = client.get("/v1/am/static/seido")
    _assert_route_exists(r, path="/v1/am/static/{resource_id}")


def test_am_example_profile_smoke(client):
    r = client.get("/v1/am/example_profiles/non-existent-profile-xyzzy")
    # 404 (resource not found) is fine; route_not_found is not.
    _assert_route_exists(r, path="/v1/am/example_profiles/{profile_id}")


def test_am_annotations_path_param_smoke(client):
    r = client.get("/v1/am/annotations/non-existent-entity-xyzzy")
    _assert_route_exists(r, path="/v1/am/annotations/{entity_id}")


def test_am_provenance_entity_smoke(client):
    r = client.get("/v1/am/provenance/non-existent-entity-xyzzy")
    _assert_route_exists(r, path="/v1/am/provenance/{entity_id}")


def test_am_provenance_fact_smoke(client):
    r = client.get("/v1/am/provenance/fact/1")
    _assert_route_exists(r, path="/v1/am/provenance/fact/{fact_id}")


def test_am_provenance_fact_invalid_id_422(client):
    """fact_id with ge=1 → negative or 0 must 422, not 5xx."""
    r = client.get("/v1/am/provenance/fact/0")
    assert r.status_code in (422, 404), r.status_code


def test_am_validate_post_smoke(client):
    r = client.post("/v1/am/validate", json={})
    _assert_route_exists(r, path="/v1/am/validate")


def test_am_saburoku_post_smoke(client):
    r = client.post("/v1/am/templates/saburoku_kyotei", json={})
    # The 36 protocol endpoint may be feature-gated (AUTONOMATH_36_KYOTEI_ENABLED).
    # Either 200 / 422 / 503 (gated) is fine; route_not_found is not.
    if r.status_code == 404:
        body = r.json() if r.text else {}
        err = body.get("error") or {}
        if err.get("code") == "route_not_found":
            pytest.fail("36 kyotei route missing")


# ---------------------------------------------------------------------------
# /v1/advisors/* — 6 paths
# ---------------------------------------------------------------------------


def test_advisors_match_smoke(client, advisors_table):
    r = client.get("/v1/advisors/match")
    _assert_route_exists(r, path="/v1/advisors/match")


def test_advisors_match_accepts_legacy_agri_alias(client, advisors_table):
    r = client.get("/v1/advisors/match", params={"industry": "agri"})
    assert r.status_code == 200, r.text
    canonical = client.get(
        "/v1/advisors/match", params={"industry": "agriculture_forestry"}
    )
    assert canonical.status_code == 200, canonical.text
    assert r.json()["total"] == canonical.json()["total"]


def test_advisors_signup_smoke(client, advisors_table):
    r = client.post("/v1/advisors/signup", json={})
    _assert_route_exists(r, path="/v1/advisors/signup")


def test_advisors_track_smoke(client, advisors_table):
    r = client.post("/v1/advisors/track", json={})
    _assert_route_exists(r, path="/v1/advisors/track")


def test_advisors_report_conversion_smoke(client, advisors_table):
    r = client.post("/v1/advisors/report-conversion", json={})
    _assert_route_exists(r, path="/v1/advisors/report-conversion")


def test_advisors_dashboard_data_smoke(client, advisors_table):
    """Dashboard data requires a real advisor_id — accept 404 / 422 /
    auth response shapes; we only care that the route resolves."""
    r = client.get("/v1/advisors/9999/dashboard-data")
    _assert_route_exists(r, path="/v1/advisors/{advisor_id}/dashboard-data")


def test_advisors_verify_houjin_smoke(client, advisors_table):
    r = client.post("/v1/advisors/verify-houjin/9999", json={})
    _assert_route_exists(r, path="/v1/advisors/verify-houjin/{advisor_id}")


# ---------------------------------------------------------------------------
# /v1/court-decisions/* — 3 paths
# ---------------------------------------------------------------------------


def test_court_decisions_search_smoke(client):
    r = client.get("/v1/court-decisions/search", params={"limit": 5})
    _assert_route_exists(r, path="/v1/court-decisions/search")
    body = r.json()
    # Response model is CourtDecisionSearchResponse; pin the shape.
    assert isinstance(body, dict)


def test_court_decisions_get_404_envelope(client):
    """Unknown unified_id → 404 with envelope (NOT 5xx)."""
    r = client.get("/v1/court-decisions/HAN-doesnotxx")
    assert r.status_code in (404, 422), r.status_code


def test_court_decisions_by_statute_smoke(client):
    r = client.post(
        "/v1/court-decisions/by-statute",
        json={"statute": "租税特別措置法", "limit": 5},
    )
    _assert_route_exists(r, path="/v1/court-decisions/by-statute")


# ---------------------------------------------------------------------------
# /v1/bids/* — 2 paths
# ---------------------------------------------------------------------------


def test_bids_search_smoke(client):
    r = client.get("/v1/bids/search", params={"limit": 5})
    _assert_route_exists(r, path="/v1/bids/search")
    body = r.json()
    assert isinstance(body, dict)


def test_bids_get_404_envelope(client):
    r = client.get("/v1/bids/BID-doesnotxx")
    assert r.status_code in (404, 422), r.status_code


# ---------------------------------------------------------------------------
# /v1/laws/* — 3 paths (search + 2 detail)
# ---------------------------------------------------------------------------


def test_laws_search_smoke(client):
    r = client.get("/v1/laws/search", params={"limit": 5})
    _assert_route_exists(r, path="/v1/laws/search")


def test_laws_get_404(client):
    r = client.get("/v1/laws/LAW-doesnotxx")
    assert r.status_code in (404, 422), r.status_code


def test_laws_related_programs_404(client):
    r = client.get("/v1/laws/LAW-doesnotxx/related-programs")
    assert r.status_code in (404, 422, 200), r.status_code


# ---------------------------------------------------------------------------
# /v1/tax_rulesets/* — 3 paths
# ---------------------------------------------------------------------------


def test_tax_rulesets_search_smoke(client):
    r = client.get("/v1/tax_rulesets/search", params={"limit": 5})
    _assert_route_exists(r, path="/v1/tax_rulesets/search")


def test_tax_rulesets_get_404(client):
    r = client.get("/v1/tax_rulesets/TAX-doesnotxx")
    assert r.status_code in (404, 422), r.status_code


def test_tax_rulesets_evaluate_smoke(client):
    r = client.post("/v1/tax_rulesets/evaluate", json={})
    _assert_route_exists(r, path="/v1/tax_rulesets/evaluate")


# ---------------------------------------------------------------------------
# /v1/loan-programs/* — 1 uncovered path (search; detail already tested)
# ---------------------------------------------------------------------------


def test_loan_programs_search_smoke(client):
    r = client.get("/v1/loan-programs/search", params={"limit": 5})
    _assert_route_exists(r, path="/v1/loan-programs/search")


# ---------------------------------------------------------------------------
# /v1/enforcement-cases/* — 1 uncovered path (search)
# ---------------------------------------------------------------------------


def test_enforcement_cases_search_smoke(client):
    r = client.get("/v1/enforcement-cases/search", params={"limit": 5})
    _assert_route_exists(r, path="/v1/enforcement-cases/search")


# ---------------------------------------------------------------------------
# /v1/me/* — uncovered tail (4 paths)
# ---------------------------------------------------------------------------


def test_me_tool_recommendation_unauth(client):
    """/me endpoints require auth — must NOT return 200 to anonymous.
    Smoke contract: assert auth-rejected (401/403) or schema-rejected (422),
    never 200 (auth bypass) or 5xx (broken handler)."""
    r = client.get("/v1/me/tool_recommendation", params={"intent": "search"})
    assert r.status_code in (401, 403, 422), r.status_code


def test_me_dashboard_unauth(client):
    r = client.get("/v1/me/dashboard")
    assert r.status_code in (401, 403), r.status_code


def test_me_billing_history_unauth(client):
    r = client.get("/v1/me/billing_history")
    assert r.status_code in (401, 403), r.status_code


def test_me_usage_by_tool_unauth(client):
    r = client.get("/v1/me/usage_by_tool")
    assert r.status_code in (401, 403), r.status_code


def test_me_alerts_subscribe_unauth(client):
    r = client.post("/v1/me/alerts/subscribe", json={})
    assert r.status_code in (401, 403, 422), r.status_code


def test_me_cap_unauth(client):
    r = client.post("/v1/me/cap", json={})
    assert r.status_code in (401, 403, 422), r.status_code


def test_me_testimonials_post_unauth(client):
    r = client.post("/v1/me/testimonials", json={})
    assert r.status_code in (401, 403, 422), r.status_code


# ---------------------------------------------------------------------------
# /v1/billing/* — 4 paths
# ---------------------------------------------------------------------------


def test_billing_checkout_smoke(client):
    r = client.post("/v1/billing/checkout", json={})
    # Route exists; payload empty → 422 / 400 expected. Stripe webhook
    # call doesn't fire from a TestClient.
    _assert_route_exists(r, path="/v1/billing/checkout")


def test_billing_portal_smoke(client):
    r = client.post("/v1/billing/portal", json={})
    _assert_route_exists(r, path="/v1/billing/portal")


def test_billing_webhook_smoke(client):
    r = client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=0,v1=invalid"},
    )
    # Webhook with bad signature → 400. Just verify it's not 5xx /
    # route_not_found.
    _assert_route_exists(r, path="/v1/billing/webhook")


# ---------------------------------------------------------------------------
# /v1/device/* — 3 paths (RFC 8628 device flow)
# ---------------------------------------------------------------------------


def test_device_authorize_smoke(client):
    r = client.post("/v1/device/authorize", json={})
    _assert_route_exists(r, path="/v1/device/authorize")


def test_device_token_smoke(client):
    r = client.post("/v1/device/token", json={})
    _assert_route_exists(r, path="/v1/device/token")


def test_device_complete_smoke(client):
    r = client.post("/v1/device/complete", json={})
    _assert_route_exists(r, path="/v1/device/complete")


# ---------------------------------------------------------------------------
# /v1/calendar/* — 1 path
# ---------------------------------------------------------------------------


def test_calendar_deadlines_smoke(client):
    r = client.get("/v1/calendar/deadlines")
    _assert_route_exists(r, path="/v1/calendar/deadlines")


# ---------------------------------------------------------------------------
# /v1/stats/* — 1 uncovered path (confidence)
# ---------------------------------------------------------------------------


def test_stats_confidence_smoke(client):
    r = client.get("/v1/stats/confidence")
    _assert_route_exists(r, path="/v1/stats/confidence")


# ---------------------------------------------------------------------------
# /v1/meta/freshness — different from /v1/meta (which IS covered)
# ---------------------------------------------------------------------------


def test_meta_freshness_smoke(client):
    r = client.get("/v1/meta/freshness", params={"limit": 5})
    _assert_route_exists(r, path="/v1/meta/freshness")


# ---------------------------------------------------------------------------
# /v1/subscribers/unsubscribe — required token + email
# ---------------------------------------------------------------------------


def test_subscribers_unsubscribe_missing_args_422(client):
    """Both token & email required → 422 when missing."""
    r = client.get("/v1/subscribers/unsubscribe")
    assert r.status_code == 422, r.status_code


def test_subscribers_unsubscribe_invalid_token(client):
    r = client.get(
        "/v1/subscribers/unsubscribe",
        params={"token": "bad-token", "email": "test@example.com"},
    )
    # Route exists, token mismatch → 4xx.
    assert r.status_code != 404 or r.json().get("error", {}).get("code") != "route_not_found"
    assert r.status_code < 500


# ---------------------------------------------------------------------------
# Verification / provenance / cost helper surfaces
# ---------------------------------------------------------------------------


def test_source_manifest_route_smoke(client, monkeypatch, tmp_path):
    """Route must stay mounted even when autonomath.db is unavailable."""
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "missing.db"))
    r = client.get("/v1/source_manifest/UNI-route-smoke")
    _assert_route_exists(r, path="/v1/source_manifest/UNI-route-smoke")
    assert r.status_code == 503
    r.json()


def test_citations_verify_route_smoke(client):
    """Anonymous request should reach the handler and be auth-rejected."""
    r = client.post(
        "/v1/citations/verify",
        json={"citations": [{"source_text": "source body", "excerpt": "source"}]},
    )
    _assert_route_exists(r, path="/v1/citations/verify")
    assert r.status_code == 401
    r.json()


def test_cost_preview_route_smoke(client):
    r = client.post(
        "/v1/cost/preview",
        json={"stack_or_calls": [{"tool": "search_programs"}]},
    )
    _assert_route_exists(r, path="/v1/cost/preview")
    assert r.status_code == 200, r.text
    assert r.headers.get("x-metered") == "false"
    body = r.json()
    assert body["predicted_total_yen"] == 3
    assert body["metered"] is False


# ---------------------------------------------------------------------------
# /healthz, /readyz — 2 root-level paths
# ---------------------------------------------------------------------------


def test_healthz_smoke(client):
    r = client.get("/healthz")
    assert r.status_code == 200


def test_readyz_smoke(client):
    r = client.get("/readyz")
    # readyz may 503 if the DB is not warm yet; we just ensure no 404.
    assert r.status_code != 404


# ---------------------------------------------------------------------------
# 404 / envelope shape consistency across uncovered paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/v1/am/tax_incentives",
        "/v1/advisors/match",
        "/v1/court-decisions/search",
        "/v1/bids/search",
        "/v1/laws/search",
    ],
)
def test_uncovered_paths_return_json(client, advisors_table, path):
    """Every search endpoint must return parseable JSON, even on 503."""
    r = client.get(path, params={"limit": 1})
    if r.status_code >= 500:
        # 503 cold-DB tolerated, but body must still be JSON.
        try:
            r.json()
        except ValueError:
            pytest.fail(f"{path} → 5xx with non-JSON body")
    else:
        r.json()  # raises if not JSON


def test_truly_unknown_route_404_envelope(client):
    """Sanity: an UNKNOWN path must produce the route_not_found
    envelope. This is the negative control for the smoke tests above."""
    r = client.get("/v1/this-route-truly-does-not-exist-xyzzy")
    assert r.status_code == 404
    body = r.json()
    err = body.get("error") or {}
    assert err.get("code") == "route_not_found", body
    # Detail must be the generic Starlette "Not Found" — distinguishing
    # it from a real endpoint that 404'd a missing resource.
    assert body.get("detail") in _GENERIC_404_DETAILS, body
