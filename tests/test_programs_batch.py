"""Tests for POST /v1/programs/batch and the MCP parity tool
`batch_get_programs`.

Covers the five deliverables from the ticket:
  - happy path (5 valid ids)
  - mixed (valid + junk -> results + not_found)
  - dedupe (`[x, x, y]` == `[x, y]`)
  - over-limit 51 ids -> 422
  - empty list -> 422

Seed data lives in tests/conftest.py — 4 programs (UNI-test-s-1 / a-1 / b-1 / x-1).
"""
from __future__ import annotations

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

# REST-only payload keys not present on MCP transport. See
# tests/test_programs.py::_REST_ONLY_KEYS for full rationale; mirrored
# here so the per-row batch parity check below recognises them.
_REST_ONLY_ROW_KEYS = {
    "static_url",
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_batch_happy_path_preserves_order(client, paid_key):
    """5 valid ids (we only have 4 seeded; repeat one via different ids).

    Order contract: results[i].unified_id == input_ids[i] after dedupe.
    Batch endpoint uses fields=full, so enriched/source_mentions/lineage keys
    must be present on every row (value may be null).
    """
    # All 4 seeded ids; use include_excluded-style coverage by asking for
    # tier=X too. Order is intentionally NOT alphabetical or tier-sorted so
    # the order-preservation assertion is load-bearing.
    ids = [
        "UNI-test-b-1",
        "UNI-test-s-1",
        "UNI-test-x-1",
        "UNI-test-a-1",
    ]
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"results", "not_found"}
    assert body["not_found"] == []
    assert [row["unified_id"] for row in body["results"]] == ids
    # fields=full contract: enriched/source_mentions/lineage keys always present.
    for row in body["results"]:
        for k in _FULL_ONLY_KEYS:
            assert k in row, f"fields=full must include {k!r} (may be null)"


# ---------------------------------------------------------------------------
# Mixed: valid + junk ids
# ---------------------------------------------------------------------------


def test_batch_mixed_valid_and_missing(client, paid_key):
    """3 real + 2 junk ids -> 3 in results, 2 in not_found.

    not_found order is the order the junk ids appeared in the deduped input.
    Not a 404 — partial success is the whole point of batch.
    """
    ids = [
        "UNI-test-s-1",       # exists
        "UNI-not-a-thing-1",  # junk
        "UNI-test-a-1",       # exists
        "UNI-not-a-thing-2",  # junk
        "UNI-test-b-1",       # exists
    ]
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["unified_id"] for row in body["results"]] == [
        "UNI-test-s-1",
        "UNI-test-a-1",
        "UNI-test-b-1",
    ]
    assert body["not_found"] == ["UNI-not-a-thing-1", "UNI-not-a-thing-2"]


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


def test_batch_dedupes_input(client, paid_key):
    """[x, x, y] -> 2 results in order [x, y]. Matches [x, y] exactly."""
    r_dup = client.post(
        "/v1/programs/batch",
        json={
            "unified_ids": [
                "UNI-test-s-1",
                "UNI-test-s-1",
                "UNI-test-a-1",
            ]
        },
        headers={"X-API-Key": paid_key},
    )
    r_clean = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
        headers={"X-API-Key": paid_key},
    )
    assert r_dup.status_code == 200
    assert r_clean.status_code == 200
    # Whole envelope equal — dedupe should be indistinguishable from a
    # clean input.
    assert r_dup.json() == r_clean.json()
    assert [r["unified_id"] for r in r_dup.json()["results"]] == [
        "UNI-test-s-1",
        "UNI-test-a-1",
    ]


# ---------------------------------------------------------------------------
# Over-limit
# ---------------------------------------------------------------------------


def test_batch_rejects_over_50_ids(client):
    """51 ids -> 422. The cap lives in pydantic (max_length=50)."""
    ids = [f"UNI-bogus-{i}" for i in range(51)]
    r = client.post("/v1/programs/batch", json={"unified_ids": ids})
    assert r.status_code == 422, r.text


def test_batch_accepts_exactly_50_ids(client, paid_key):
    """Edge: 50 ids is the ceiling (inclusive). All junk, so all go to
    not_found — but the request must NOT 422."""
    ids = [f"UNI-bogus-{i}" for i in range(50)]
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"] == []
    assert len(body["not_found"]) == 50


# ---------------------------------------------------------------------------
# Empty
# ---------------------------------------------------------------------------


def test_batch_rejects_empty_list(client):
    """[] -> 422. min_length=1 on pydantic."""
    r = client.post("/v1/programs/batch", json={"unified_ids": []})
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# REST vs MCP shape parity — same dict shape per row in both transports.
# ---------------------------------------------------------------------------


def test_batch_mcp_parity(client, paid_key):
    from jpintel_mcp.mcp.server import batch_get_programs as mcp_batch

    ids = ["UNI-test-s-1", "UNI-test-a-1"]
    rest = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers={"X-API-Key": paid_key},
    ).json()
    mcp = mcp_batch(ids)
    # Parity is on the underlying tool envelope. MCP wraps with additive
    # envelope keys (status, api_version, ...); strip them before comparing.
    # REST does not get the envelope, so do not strip from REST.
    mcp_payload_keys = set(mcp.keys()) - _ENVELOPE_ONLY_KEYS
    assert set(rest.keys()) == mcp_payload_keys == {"results", "not_found"}
    # Same per-row key set (values may vary slightly for null placeholders
    # but the schema is the contract).
    assert [r["unified_id"] for r in rest["results"]] == [
        r["unified_id"] for r in mcp["results"]
    ]
    for rest_row, mcp_row in zip(rest["results"], mcp["results"], strict=False):
        # REST rows ship static_url (per-program SEO link) in addition to
        # the shared payload; MCP rows omit it. Compare modulo that.
        rest_row_keys = set(rest_row.keys()) - _REST_ONLY_ROW_KEYS
        assert rest_row_keys == set(mcp_row.keys())


def test_batch_mcp_over_50_returns_error_envelope(client):
    """MCP tool returns a structured error envelope for the over-limit path."""
    from jpintel_mcp.mcp.server import batch_get_programs as mcp_batch

    res = mcp_batch([f"UNI-bogus-{i}" for i in range(51)])
    assert isinstance(res.get("error"), dict), "expected nested error envelope"
    assert res["error"]["code"] == "limit_exceeded"
    assert "50" in res["error"]["message"]
    assert "retry_with" in res["error"]


def test_batch_mcp_empty_returns_error_envelope(client):
    from jpintel_mcp.mcp.server import batch_get_programs as mcp_batch

    res = mcp_batch([])
    assert isinstance(res.get("error"), dict), "expected nested error envelope"
    assert res["error"]["code"] == "empty_input"
    assert "retry_with" in res["error"]
