"""Tests for the ?fields={minimal|default|full} query param on
/v1/programs/search and /v1/programs/{unified_id}, plus the
``PROGRAM_SEARCH_MAX_OFFSET`` deep-OFFSET performance guard.

Covers:
- each endpoint with each fields value
- whitelist accuracy for minimal
- backwards-compat default shape (no param or fields=default are identical)
- wire size cap for minimal (20-row search result < 2 KB)
- full-mode guarantee: enriched / source_mentions / lineage keys present,
  value may be null.
- offset-cap guard rejects deep crawl attempts at the API edge.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.models import MINIMAL_FIELD_WHITELIST

# Extra fields only present on fields=full (both endpoints).
_FULL_ONLY_KEYS = {
    "enriched",
    "source_mentions",
    "source_url",
    "source_fetched_at",
    "source_checksum",
}

# Envelope keys MCP server adds via _envelope_merge (server.py:780-820) that
# are NOT part of the underlying tool's payload. Strip from MCP side before
# parity comparison with REST (REST does not get the envelope wrapping).
# `meta` is also envelope-added when the tool has no native meta block.
_ENVELOPE_ONLY_KEYS = {
    "status",
    "result_count",
    "explanation",
    "suggested_actions",
    "api_version",
    "tool_name",
    "query_echo",
    "latency_ms",
    "evidence_source_count",
    "meta",
}

# REST-only payload keys not shared with MCP transport. Strip from the
# REST side before parity comparison with MCP.
#
#   corpus_snapshot_id / corpus_checksum
#       会計士 work-paper reproducibility (2026-04-29). Injected by
#       `attach_corpus_snapshot()` after the L4 cache fetch so the snapshot
#       reflects the LIVE corpus state at request time. MCP gets the same
#       row payload but its envelope does not surface this audit pair.
#   static_url
#       /v1/programs/{id} ships a hyperlink to the per-program SEO page
#       (`site/_templates/program.html`). MCP returns the same row payload
#       without the static_url because MCP is for AI agents, not browsers.
_REST_ONLY_KEYS = {
    "corpus_snapshot_id",
    "corpus_checksum",
    "static_url",
}


# ---------------------------------------------------------------------------
# /v1/programs/search
# ---------------------------------------------------------------------------


def test_search_fields_minimal_whitelist(client):
    r = client.get("/v1/programs/search", params={"fields": "minimal", "limit": 100})
    assert r.status_code == 200
    d = r.json()
    assert len(d["results"]) >= 1
    for row in d["results"]:
        # Only whitelist keys present — no extras, no omissions.
        assert set(row.keys()) == set(MINIMAL_FIELD_WHITELIST)


def test_search_fields_default_matches_no_param(client):
    r_default = client.get("/v1/programs/search", params={"limit": 100}).json()
    r_explicit = client.get(
        "/v1/programs/search", params={"fields": "default", "limit": 100}
    ).json()
    # Structural equality across the whole envelope: total/limit/offset/results.
    assert r_default == r_explicit


def test_search_fields_full_has_enriched_keys(client, paid_key):
    r = client.get(
        "/v1/programs/search",
        params={"fields": "full", "limit": 100},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200
    d = r.json()
    assert len(d["results"]) >= 1
    for row in d["results"]:
        # Full mode: keys must be present even if the stored value was null.
        for key in _FULL_ONLY_KEYS:
            assert key in row, f"fields=full must include {key!r} (may be null)"


def test_search_anon_fields_full_is_402(client):
    """fields=full is paid-only. Anon (no X-API-Key) hitting full → 402."""
    r = client.get("/v1/programs/search", params={"fields": "full", "limit": 1})
    assert r.status_code == 402
    body = r.json()
    # FastAPI wraps non-str detail in {"detail": {...}}; unwrap one level.
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        assert "fields=full" in detail.get("detail", "")
        assert detail.get("upgrade_url") == "/pricing"


def test_search_anon_fields_default_is_200(client):
    """The gate is strictly on fields=full. minimal + default stay open for anon."""
    assert client.get("/v1/programs/search", params={"limit": 1}).status_code == 200
    assert (
        client.get("/v1/programs/search", params={"fields": "default", "limit": 1}).status_code
        == 200
    )
    assert (
        client.get("/v1/programs/search", params={"fields": "minimal", "limit": 1}).status_code
        == 200
    )


def test_search_offset_above_guard_is_422(client):
    """R3 P0-3 (2026-05-13): the offset cap was tightened from 10_000 to
    1_000 once ``?cursor=`` keyset pagination shipped. The historical
    10_001 value still triggers the cap (well above 1_000); the new
    1_001 boundary check below confirms the guard moved to the tighter
    threshold rather than just rejecting >>cap values."""
    r = client.get("/v1/programs/search", params={"offset": 10001})
    assert r.status_code == 422
    assert "offset" in r.text


def test_search_offset_at_new_cap_boundary(client):
    """R3 P0-3: offset=1_000 (the new cap) must succeed; 1_001 must 422.

    Pins the lowered cap so a future drift back to the legacy 10_000
    ceiling triggers a test failure rather than silently re-introducing
    the 2-5 s p99 dedupe-partition walk."""
    from jpintel_mcp.api.programs import PROGRAM_SEARCH_MAX_OFFSET

    assert PROGRAM_SEARCH_MAX_OFFSET == 1_000

    r_at = client.get(
        "/v1/programs/search",
        params={"offset": PROGRAM_SEARCH_MAX_OFFSET, "limit": 1},
    )
    assert r_at.status_code == 200, r_at.text

    r_over = client.get(
        "/v1/programs/search",
        params={"offset": PROGRAM_SEARCH_MAX_OFFSET + 1, "limit": 1},
    )
    assert r_over.status_code == 422
    assert "offset" in r_over.text


def test_search_cursor_roundtrip_matches_offset_path(client, paid_key):
    """R3 P0-3: paging via ``?cursor=`` returns the SAME row sequence as
    the legacy ``?offset=`` walk over the small seeded corpus.

    The seeded DB has 3 searchable rows (S/A/B) once tier='X' is excluded.
    We walk them with limit=1, comparing the offset path's results[0]
    against the cursor path's results[0] at each step. The cursor path
    must also surface ``next_cursor`` while rows remain and drop it
    (None) on the final page. Uses ``paid_key`` to dodge the 3/day anon
    quota — the walk takes ~6 round-trips."""
    headers = {"X-API-Key": paid_key}
    # Offset baseline — read all 3 rows in order to establish the
    # expected sequence under the production ORDER BY.
    seen_offset: list[str] = []
    for off in range(0, 5):
        resp = client.get(
            "/v1/programs/search",
            params={"offset": off, "limit": 1},
            headers=headers,
        )
        assert resp.status_code == 200, (
            f"offset={off} walk failed at status {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        results = body.get("results")
        if not results:
            break
        seen_offset.append(results[0]["unified_id"])

    # Cursor walk — kick off from offset=0 then chase ``next_cursor`` until
    # the server stops emitting one (= tail).
    seen_cursor: list[str] = []
    resp = client.get("/v1/programs/search", params={"limit": 1}, headers=headers)
    assert resp.status_code == 200, (
        f"first cursor-walk request failed: {resp.status_code} {resp.text[:200]}"
    )
    while resp.status_code == 200:
        body = resp.json()
        results = body.get("results") or []
        if not results:
            break
        seen_cursor.append(results[0]["unified_id"])
        token = body.get("next_cursor")
        if not token:
            break
        resp = client.get(
            "/v1/programs/search",
            params={"cursor": token, "limit": 1},
            headers=headers,
        )

    assert seen_offset == seen_cursor, (
        f"cursor path diverged from offset path: "
        f"offset={seen_offset!r} cursor={seen_cursor!r}"
    )
    # Sanity: the seeded corpus has 3 searchable rows.
    assert len(seen_cursor) == 3


def test_search_cursor_dedupe_preserved(client, paid_key):
    """R3 P0-3: cursor round-trip must not return the same unified_id twice.

    The dedup-by-primary_name partition is the whole reason the legacy
    OFFSET path was 2-5 s — a flawed cursor predicate could either skip
    rows (off-by-one keyset) or duplicate them (equal-score tie not
    handled). Walk with limit=1 and assert every unified_id is unique.
    Authed (``paid_key``) to skip the 3/day anon cap."""
    headers = {"X-API-Key": paid_key}
    seen: list[str] = []
    resp = client.get("/v1/programs/search", params={"limit": 1}, headers=headers)
    safety_budget = 50  # never loop more than 50× the seed corpus.
    while resp.status_code == 200 and safety_budget > 0:
        body = resp.json()
        results = body.get("results") or []
        if not results:
            break
        seen.append(results[0]["unified_id"])
        token = body.get("next_cursor")
        if not token:
            break
        resp = client.get(
            "/v1/programs/search",
            params={"cursor": token, "limit": 1},
            headers=headers,
        )
        safety_budget -= 1

    assert safety_budget > 0, "cursor walk did not terminate within budget"
    assert seen, "cursor walk returned 0 rows"
    assert len(seen) == len(set(seen)), f"duplicate unified_id in cursor walk: {seen!r}"


def test_search_cursor_malformed_is_422(client):
    """Malformed cursor token must fail closed at 422 (with ``cursor`` in
    the error body) — never silently return offset=0 results which would
    bill the caller without delivering the resumed page they asked for."""
    r = client.get(
        "/v1/programs/search",
        params={"cursor": "not_a_real_base64_token!!", "limit": 1},
    )
    assert r.status_code == 422, r.text
    assert "cursor" in r.text


def test_search_cursor_short_page_drops_next_cursor(client):
    """When the final page returns < limit rows the server must NOT emit
    a ``next_cursor`` — otherwise clients keep walking forever and pay
    ¥3 per empty page. ``limit=100`` against the 3-row seed corpus
    forces the short-page branch on the very first call."""
    body = client.get("/v1/programs/search", params={"limit": 100}).json()
    assert len(body["results"]) >= 1
    assert len(body["results"]) < 100
    assert body.get("next_cursor") is None, (
        f"next_cursor must be None on a short page, got {body.get('next_cursor')!r}"
    )


def test_search_cursor_fts_path_mismatch_is_422(client, paid_key):
    """A cursor minted against the FTS sort path must NOT silently apply
    when the next call routes through the non-FTS path (no ``q=``).

    The seed FTS rows let ``q=補助金`` exercise the FTS branch (returns 1
    row -> ``UNI-test-s-1``). Dropping ``q`` on the next call falls into
    the non-FTS branch (different ORDER BY direction); the cursor's
    ``f=1`` byte must trip the 422 guard rather than mis-rank the page."""
    headers = {"X-API-Key": paid_key}
    # Hit FTS path. With the limit=1 + one matching row the result is a
    # short page (1 < limit only if limit > 1 — set limit=1 to force the
    # full-page branch so next_cursor IS emitted).
    fts_resp = client.get(
        "/v1/programs/search",
        params={"q": "補助金", "limit": 1},
        headers=headers,
    )
    assert fts_resp.status_code == 200, fts_resp.text
    fts_body = fts_resp.json()
    # FTS path with limit=1 must populate next_cursor when a row came back.
    if not fts_body["results"] or not fts_body.get("next_cursor"):
        pytest.skip("seed corpus did not produce a full FTS page for the mismatch test")
    fts_token = fts_body["next_cursor"]

    # Now use that FTS-built token against a non-FTS call (no q).
    mismatch_resp = client.get(
        "/v1/programs/search",
        params={"cursor": fts_token, "limit": 1},
        headers=headers,
    )
    assert mismatch_resp.status_code == 422, mismatch_resp.text
    assert "cursor" in mismatch_resp.text


def test_search_cursor_encoder_is_urlsafe_base64(client):
    """Quick property check: every ``next_cursor`` issued must round-trip
    through standard urlsafe-base64 decode without padding repair.

    The encoder strips ``=`` padding for URL compactness; the decoder
    re-pads. A client that copy-pastes the token into a URL must not
    have to do any quoting work — the alphabet stays in the urlsafe set."""
    import re as _re

    body = client.get("/v1/programs/search", params={"limit": 1}).json()
    token = body.get("next_cursor")
    if token is None:
        # Corpus may be too small for a 1-row page to flip the
        # "more rows remain" gate — that case is exercised by
        # test_search_cursor_roundtrip_matches_offset_path so we don't
        # duplicate the assertion here.
        pytest.skip("seed corpus too small to emit next_cursor")
    # urlsafe-base64 alphabet: A-Z a-z 0-9 - _
    assert _re.fullmatch(r"[A-Za-z0-9_\-]+", token), f"token has non-urlsafe chars: {token!r}"


def test_search_tier_list_length_cap_is_422(client):
    """R3 guard: ?tier repeated >4× returns 422.

    Tier domain is 4 ({S,A,B,C}). Pydantic Literal validates values but
    not list length; without the explicit ``max_length=4`` on the Query
    annotation, a caller could repeat ``?tier=S&tier=A&...`` 1000 times
    to inflate the prepared statement parameter list. The Query-level
    cap rejects the request at the FastAPI validation boundary before
    any SQL is built.
    """
    # 5 entries (one duplicate is fine value-wise but breaks length cap).
    r = client.get(
        "/v1/programs/search",
        params=[("tier", "S"), ("tier", "A"), ("tier", "B"), ("tier", "C"), ("tier", "S")],
    )
    assert r.status_code == 422, r.text
    # FastAPI/Pydantic length-violation error mentions either "tier" loc
    # or a length-bound message; both are acceptable.
    assert "tier" in r.text


def test_search_tier_list_length_at_max_is_200(client):
    """Boundary: exactly 4 tier values is allowed (the full tier domain)."""
    r = client.get(
        "/v1/programs/search",
        params=[("tier", "S"), ("tier", "A"), ("tier", "B"), ("tier", "C")],
    )
    assert r.status_code == 200, r.text


def test_batch_anon_is_402(client):
    """Batch is hardcoded fields=full; anon must upgrade to use it."""
    r = client.post("/v1/programs/batch", json={"unified_ids": ["UNI-test-s-1"]})
    assert r.status_code == 402


def test_batch_paid_is_200(client, paid_key):
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ["UNI-test-s-1"]},
        headers={
            "X-API-Key": paid_key,
            "X-Cost-Cap-JPY": "3",
            "Idempotency-Key": "programs-batch-paid-is-200",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 1
    assert body["not_found"] == []


def test_search_fields_minimal_size_budget(client):
    """Minimal per-row content should be well under 300 B.

    Spec target: a 20-row minimal search result under 2 KB. This holds for
    ASCII-dominant rows. Seed rows carry multi-char Japanese names (3 B /
    char in UTF-8) so 20 of those can legitimately exceed 2 KB even when
    the trimming is working — the important contract is (a) per-row stays
    small, (b) minimal is much smaller than default (asserted in a separate
    test). Cap per-row at 300 B as the hard budget.
    """
    r = client.get("/v1/programs/search", params={"fields": "minimal", "limit": 100})
    d = r.json()
    total_bytes = len(json.dumps(d, ensure_ascii=False))
    envelope_bytes = len(
        json.dumps(
            {"total": d["total"], "limit": d["limit"], "offset": d["offset"], "results": []},
            ensure_ascii=False,
        )
    )
    rows = len(d["results"])
    assert rows >= 1
    per_row = (total_bytes - envelope_bytes) / rows
    assert per_row < 300, f"minimal per-row {per_row:.1f} B exceeded 300 B budget"


def test_search_minimal_smaller_than_default(client):
    """Sanity: minimal must be strictly smaller than default for same predicate."""
    p = {"limit": 100}
    d_min = len(
        json.dumps(
            client.get("/v1/programs/search", params={**p, "fields": "minimal"}).json(),
            ensure_ascii=False,
        )
    )
    d_def = len(
        json.dumps(client.get("/v1/programs/search", params={**p}).json(), ensure_ascii=False)
    )
    assert d_min < d_def, f"minimal ({d_min}) should be smaller than default ({d_def})"


@pytest.mark.parametrize(
    ("path", "endpoint"),
    [
        ("/v1/programs/search", "programs.search"),
        ("/v1/programs/UNI-test-s-1", "programs.get"),
    ],
)
def test_paid_final_cap_failure_returns_503_without_usage_event(
    client,
    seeded_db,
    paid_key,
    monkeypatch,
    path,
    endpoint,
):
    key_hash = hash_api_key(paid_key)

    def usage_count() -> int:
        conn = sqlite3.connect(seeded_db)
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
                (key_hash, endpoint),
            ).fetchone()
            return int(count)
        finally:
            conn.close()

    def _reject_final_cap(*_args, **_kwargs):
        return False, False

    import jpintel_mcp.api.deps as deps

    before = usage_count()
    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    r = client.get(path, headers={"X-API-Key": paid_key})

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert usage_count() == before


# ---------------------------------------------------------------------------
# /v1/programs/{unified_id}
# ---------------------------------------------------------------------------


def test_get_fields_minimal_whitelist(client):
    r = client.get("/v1/programs/UNI-test-s-1", params={"fields": "minimal"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == set(MINIMAL_FIELD_WHITELIST)
    assert body["unified_id"] == "UNI-test-s-1"
    assert body["primary_name"] == "テスト S-tier 補助金"
    assert body["tier"] == "S"


def test_get_fields_default_matches_no_param(client):
    r_default = client.get("/v1/programs/UNI-test-s-1").json()
    r_explicit = client.get("/v1/programs/UNI-test-s-1", params={"fields": "default"}).json()
    assert r_default == r_explicit


def test_get_fields_full_has_null_placeholders(client):
    """The seeded row has enriched_json=NULL and source_mentions_json=NULL.

    Full mode must still include the keys; value == null tells the caller
    "we looked, there was nothing" vs "server didn't ship the field".
    """
    r = client.get("/v1/programs/UNI-test-s-1", params={"fields": "full"})
    assert r.status_code == 200
    body = r.json()
    for key in _FULL_ONLY_KEYS:
        assert key in body, f"fields=full must include {key!r}"
    # Seed has no enriched / source_mentions -> null is the contract.
    assert body["enriched"] is None
    assert body["source_mentions"] is None


# ---------------------------------------------------------------------------
# Rejection / validation
# ---------------------------------------------------------------------------


def test_search_rejects_unknown_fields_value(client):
    r = client.get("/v1/programs/search", params={"fields": "weird"})
    assert r.status_code == 422


def test_get_rejects_unknown_fields_value(client):
    r = client.get("/v1/programs/UNI-test-s-1", params={"fields": "weird"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# MCP parity — /v1/programs/{id}?fields=full and MCP get_program(fields=full)
# must return the same dict shape.
# ---------------------------------------------------------------------------


def test_mcp_rest_parity_full(client):
    from jpintel_mcp.mcp.server import get_program as mcp_get_program

    rest = client.get("/v1/programs/UNI-test-s-1", params={"fields": "full"}).json()
    mcp = mcp_get_program("UNI-test-s-1", fields="full")
    # Parity is on the underlying tool fields. MCP wraps the payload with
    # an additive envelope (status, api_version, ...); strip those before
    # comparing. REST does not get the envelope, but does get REST-only
    # additions (corpus_snapshot_id / corpus_checksum / static_url) —
    # strip those from the REST side before comparison.
    mcp_payload_keys = set(mcp.keys()) - _ENVELOPE_ONLY_KEYS
    rest_payload_keys = set(rest.keys()) - _REST_ONLY_KEYS
    assert rest_payload_keys == mcp_payload_keys


def test_mcp_minimal_same_whitelist(client):
    from jpintel_mcp.mcp.server import get_program as mcp_get_program

    rest = client.get("/v1/programs/UNI-test-s-1", params={"fields": "minimal"}).json()
    mcp = mcp_get_program("UNI-test-s-1", fields="minimal")
    # REST returns exactly the whitelist; MCP returns whitelist + envelope.
    # Subset assertion verifies the whitelist is present in both transports
    # without rejecting MCP's additive envelope keys.
    assert set(rest.keys()) == set(MINIMAL_FIELD_WHITELIST)
    assert set(MINIMAL_FIELD_WHITELIST).issubset(set(mcp.keys()))
