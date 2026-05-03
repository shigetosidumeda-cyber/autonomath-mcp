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


def _paid_headers(paid_key: str, cap_yen: int, suffix: str) -> dict[str, str]:
    return {
        "X-API-Key": paid_key,
        "X-Cost-Cap-JPY": str(cap_yen),
        "Idempotency-Key": f"programs-batch-{suffix}",
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
    # Include the seeded Tier X/excluded row: public batch treats it like
    # not_found, so it cannot leak into the public Program model.
    ids = [
        "UNI-test-b-1",
        "UNI-test-s-1",
        "UNI-test-x-1",
        "UNI-test-a-1",
    ]
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers=_paid_headers(paid_key, 12, "happy"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"results", "not_found", "billing"}
    assert body["not_found"] == ["UNI-test-x-1"]
    assert [row["unified_id"] for row in body["results"]] == [
        "UNI-test-b-1",
        "UNI-test-s-1",
        "UNI-test-a-1",
    ]
    assert body["billing"] == {
        "billable_units": 3,
        "yen_excl_tax": 9,
        "unit_price_yen": 3,
        "not_found_billed": False,
    }
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
        "UNI-test-s-1",  # exists
        "UNI-not-a-thing-1",  # junk
        "UNI-test-a-1",  # exists
        "UNI-not-a-thing-2",  # junk
        "UNI-test-b-1",  # exists
    ]
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers=_paid_headers(paid_key, 15, "mixed"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["unified_id"] for row in body["results"]] == [
        "UNI-test-s-1",
        "UNI-test-a-1",
        "UNI-test-b-1",
    ]
    assert body["not_found"] == ["UNI-not-a-thing-1", "UNI-not-a-thing-2"]
    assert body["billing"]["billable_units"] == 3
    assert body["billing"]["yen_excl_tax"] == 9
    assert body["billing"]["not_found_billed"] is False


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
        headers=_paid_headers(paid_key, 6, "dedupe-dup"),
    )
    r_clean = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
        headers=_paid_headers(paid_key, 6, "dedupe-clean"),
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
        headers=_paid_headers(paid_key, 150, "exact-50"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"] == []
    assert len(body["not_found"]) == 50
    assert body["billing"]["billable_units"] == 0
    assert body["billing"]["yen_excl_tax"] == 0


def test_batch_requires_cost_cap(client, paid_key):
    """Paid batch requests must bind an explicit per-request cost ceiling."""
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ["UNI-test-s-1"]},
        headers={
            "X-API-Key": paid_key,
            "Idempotency-Key": "programs-batch-cost-cap-required",
        },
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["code"] == "cost_cap_required"
    assert body["detail"]["predicted_yen"] == 3


def test_batch_low_cost_cap_rejects_before_billing(client, paid_key):
    """A cap below the deduped batch cost is rejected before usage logging."""
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ["UNI-test-s-1", "UNI-test-a-1"]},
        headers=_paid_headers(paid_key, 3, "low-cap"),
    )
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["detail"]["code"] == "cost_cap_exceeded"
    assert body["detail"]["predicted_yen"] == 6
    assert body["detail"]["cost_cap_yen"] == 3


# ---------------------------------------------------------------------------
# Empty
# ---------------------------------------------------------------------------


def test_batch_rejects_empty_list(client):
    """[] -> 422. min_length=1 on pydantic."""
    r = client.post("/v1/programs/batch", json={"unified_ids": []})
    assert r.status_code == 422, r.text


def test_paid_batch_requires_idempotency_key(client, paid_key):
    r = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ["UNI-test-s-1"]},
        headers={"X-API-Key": paid_key, "X-Cost-Cap-JPY": "3"},
    )
    assert r.status_code == 428
    assert r.json()["error"] == "idempotency_key_required"


def test_authenticated_bulk_route_is_guarded_by_cost_cap_middleware(client, paid_key):
    """The generic bulk guard must be mounted, not only handler-level checks."""
    r = client.post(
        "/v1/unknown/bulk_preview",
        json={"items": ["x"]},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "cost_cap_required"
    assert r.headers["X-Cost-Cap-Required"] == "true"


# ---------------------------------------------------------------------------
# REST vs MCP shape parity — same dict shape per row in both transports.
# ---------------------------------------------------------------------------


def test_batch_mcp_parity(client, paid_key):
    from jpintel_mcp.mcp.server import batch_get_programs as mcp_batch

    ids = ["UNI-test-s-1", "UNI-test-a-1"]
    rest = client.post(
        "/v1/programs/batch",
        json={"unified_ids": ids},
        headers=_paid_headers(paid_key, 6, "mcp-parity"),
    ).json()
    mcp = mcp_batch(ids)
    # Parity is on the underlying tool envelope. MCP wraps with additive
    # envelope keys (status, api_version, ...); strip them before comparing.
    # REST does not get the envelope, so do not strip from REST.
    mcp_payload_keys = set(mcp.keys()) - _ENVELOPE_ONLY_KEYS
    assert {"results", "not_found"}.issubset(rest.keys())
    assert mcp_payload_keys == {"results", "not_found"}
    assert rest["billing"]["billable_units"] == len(rest["results"])
    # Same per-row key set (values may vary slightly for null placeholders
    # but the schema is the contract).
    assert [r["unified_id"] for r in rest["results"]] == [r["unified_id"] for r in mcp["results"]]
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
