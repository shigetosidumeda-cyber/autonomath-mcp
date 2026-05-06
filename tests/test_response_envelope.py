"""Tests for the §28.2 Agent Contract canonical response envelope.

Covers:

  1. ``StandardResponse.rich`` populates status='rich' + meta.
  2. ``StandardResponse.empty`` carries ``empty_reason`` + ``retry_with``.
  3. ``StandardError.rate_limited`` fills retry_after / retryable / code.
  4. Accept-header v2 opt-in on /v1/programs/search returns the v2 shape.
  5. Without opt-in the same route returns the legacy shape (no regression).
  6. Opt-in error path (404 on /v1/houjin/) follows the v2 error envelope.
  7. ``wrap_for_mcp`` returns a CallToolResult with structuredContent + content[].
  8. The opt-in flag is parsed from the vendor Accept header only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from jpintel_mcp.api._envelope import (
    Citation,
    QueryEcho,
    StandardError,
    StandardResponse,
    wants_envelope_v2,
)
from jpintel_mcp.mcp._envelope import wrap_for_mcp

# --------------------------------------------------------------------------
# Test 1 — rich() shape
# --------------------------------------------------------------------------


def test_rich_populates_status_and_meta() -> None:
    rows = [{"unified_id": f"UNI-{i:04x}", "name": f"row{i}"} for i in range(7)]
    citations = [
        {
            "source_id": "src-001",
            "source_url": "https://example.go.jp/foo",
            "publisher": "経産省",
            "title": "中小企業 IT 導入支援",
            "license": "pdl_v1.0",
            "verification_status": "verified",
        }
    ]
    env = StandardResponse.rich(
        results=rows,
        citations=citations,
        request_id="01KQ3XQ77RR7J8XWZ8C0YR2JN2",
        query_echo={
            "normalized_input": {"q": "IT導入"},
            "applied_filters": {"tier": ["S", "A"]},
            "unparsed_terms": [],
        },
        latency_ms=42,
        billable_units=1,
        client_tag="acme-customer-001",
    )
    wire = env.to_wire()

    assert wire["status"] == "rich"
    assert len(wire["results"]) == 7
    assert wire["citations"][0]["license"] == "pdl_v1.0"
    assert wire["query_echo"]["normalized_input"]["q"] == "IT導入"
    assert wire["query_echo"]["applied_filters"]["tier"] == ["S", "A"]
    # meta keys per spec
    assert wire["meta"]["request_id"] == "01KQ3XQ77RR7J8XWZ8C0YR2JN2"
    assert wire["meta"]["api_version"] == "v2"
    assert wire["meta"]["latency_ms"] == 42
    assert wire["meta"]["billable_units"] == 1
    assert wire["meta"]["client_tag"] == "acme-customer-001"
    # None-valued optional fields must be dropped from the wire
    assert "error" not in wire
    assert "empty_reason" not in wire


def test_rich_auto_classifies_under_threshold_to_sparse() -> None:
    """rich() is permissive — fewer than _RICH_THRESHOLD rows fall to sparse."""
    rows = [{"id": 1}]
    env = StandardResponse.rich(results=rows, request_id="rid-001")
    assert env.status == "sparse"
    env2 = StandardResponse.rich(results=[], request_id="rid-002")
    assert env2.status == "empty"


# --------------------------------------------------------------------------
# Test 2 — empty() shape with retry_with
# --------------------------------------------------------------------------


def test_empty_carries_retry_with_and_reason() -> None:
    env = StandardResponse.empty(
        request_id="rid-empty-001",
        empty_reason="no_match",
        retry_with={"q": "wider", "broaden": True, "hint": "drop prefecture filter"},
        query_echo={
            "normalized_input": {"q": "very-narrow-term"},
            "applied_filters": {"prefecture": "東京都"},
            "unparsed_terms": [],
        },
        latency_ms=10,
    )
    wire = env.to_wire()

    assert wire["status"] == "empty"
    assert wire["empty_reason"] == "no_match"
    assert wire["retry_with"] == {
        "q": "wider",
        "broaden": True,
        "hint": "drop prefecture filter",
    }
    assert wire["results"] == []
    assert wire["meta"]["request_id"] == "rid-empty-001"


# --------------------------------------------------------------------------
# Test 3 — StandardError.rate_limited
# --------------------------------------------------------------------------


def test_rate_limited_envelope_shape() -> None:
    err = StandardError.rate_limited(retry_after=60)
    body = err.model_dump(mode="json", exclude_none=True)

    assert body["code"] == "RATE_LIMITED"
    assert body["retryable"] is True
    assert body["retry_after"] == 60
    assert body["documentation"].endswith("#rate_limited")
    assert "user_message" in body
    # Wrapped into a response envelope:
    env = StandardResponse.from_error(err, request_id="rid-rl-001")
    wire = env.to_wire()
    assert wire["status"] == "error"
    assert wire["error"]["code"] == "RATE_LIMITED"
    assert wire["error"]["retry_after"] == 60
    assert wire["meta"]["billable_units"] == 0


def test_other_error_constructors() -> None:
    """Sanity-coverage of the remaining StandardError class methods."""
    assert StandardError.unauthorized().code == "UNAUTHORIZED"
    assert StandardError.unauthorized().retryable is False
    assert StandardError.forbidden().code == "FORBIDDEN"
    nf = StandardError.not_found("houjin", "1234567890123")
    assert nf.code == "NOT_FOUND"
    assert "1234567890123" in (nf.developer_message or "")
    br = StandardError.bad_request("tier", "must be one of S/A/B/C")
    assert br.code == "VALIDATION_ERROR"
    assert "tier" in (br.developer_message or "")
    lg = StandardError.license_gate_blocked("noukaweb.jp")
    assert lg.code == "LICENSE_GATE_BLOCKED"
    qe = StandardError.quota_exceeded()
    assert qe.code == "QUOTA_EXCEEDED"
    ie = StandardError.integrity_error()
    assert ie.code == "INTEGRITY_ERROR"
    assert ie.retryable is True
    ic = StandardError.internal()
    assert ic.code == "INTERNAL_ERROR"
    assert ic.retryable is True


# --------------------------------------------------------------------------
# Test 4 — opt-in via Accept header on /v1/programs/search
# --------------------------------------------------------------------------


def test_programs_search_v2_opt_in_returns_envelope(client: TestClient) -> None:
    r = client.get(
        "/v1/programs/search",
        params={"q": "テスト"},
        headers={"Accept": "application/vnd.jpcite.v2+json"},
    )
    assert r.status_code == 200
    body = r.json()
    # v2 mandatory keys per §28.2:
    assert body["status"] in ("rich", "sparse", "empty")
    assert "results" in body
    assert "citations" in body
    assert "warnings" in body
    assert "suggested_actions" in body
    assert "meta" in body
    assert body["meta"]["api_version"] == "v2"
    assert "request_id" in body["meta"]
    # echo header must announce the v2 negotiation
    assert r.headers.get("X-Envelope-Version") == "v2"


# --------------------------------------------------------------------------
# Test 5 — without opt-in, legacy shape stays intact
# --------------------------------------------------------------------------


def test_programs_search_legacy_shape_unchanged(client: TestClient) -> None:
    r = client.get("/v1/programs/search", params={"q": "テスト"})
    assert r.status_code == 200
    body = r.json()
    # Legacy contract: total / limit / offset / results.
    assert "total" in body
    assert "limit" in body
    assert "offset" in body
    assert "results" in body
    # And NO envelope-v2-only key:
    assert "query_echo" not in body
    assert "meta" not in body or "api_version" not in (body.get("meta") or {})
    assert r.headers.get("X-Envelope-Version") == "v1"


# --------------------------------------------------------------------------
# Test 6 — error path on opt-in route follows StandardError envelope
# --------------------------------------------------------------------------


def test_houjin_404_with_v2_opt_in(client: TestClient) -> None:
    # 13-digit bangou that we know is not in the seeded test corpus.
    r = client.get(
        "/v1/houjin/9999999999999",
        headers={"Accept": "application/vnd.jpcite.v2+json"},
    )
    assert r.status_code in (404, 503)  # 503 if autonomath.db is missing in test sandbox
    body = r.json()
    if r.status_code == 503:
        # 503 short-circuits in the route (autonomath.db not present in
        # CI), and the global handler returns its own envelope. Skip.
        pytest.skip("autonomath.db unavailable in this test environment")
    assert body["status"] == "error"
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["retryable"] is False
    assert body["error"]["documentation"].endswith("#not_found")
    assert "request_id" in body["meta"]


# --------------------------------------------------------------------------
# Test 7 — wrap_for_mcp returns valid CallToolResult shape
# --------------------------------------------------------------------------


def test_wrap_for_mcp_success_shape() -> None:
    env = StandardResponse.rich(
        results=[{"id": i} for i in range(6)],
        request_id="rid-mcp-001",
    )
    out = wrap_for_mcp(env)
    assert "structuredContent" in out
    assert "content" in out
    assert isinstance(out["content"], list)
    assert out["content"][0]["type"] == "text"
    assert "rich" in out["content"][0]["text"]
    assert out["structuredContent"]["status"] == "rich"
    # success path must NOT have isError
    assert "isError" not in out


def test_wrap_for_mcp_error_shape() -> None:
    err = StandardError.rate_limited(retry_after=30)
    env = StandardResponse.from_error(err, request_id="rid-mcp-err-001")
    out = wrap_for_mcp(env)
    assert out["isError"] is True
    assert out["structuredContent"]["status"] == "error"
    assert out["structuredContent"]["error"]["code"] == "RATE_LIMITED"
    assert out["content"][0]["type"] == "text"
    # MCP host renders the user_message inline
    assert isinstance(out["content"][0]["text"], str)
    assert len(out["content"][0]["text"]) > 0


def test_wrap_for_mcp_bare_error() -> None:
    """`wrap_for_mcp` accepts a bare StandardError without a wrapping response."""
    out = wrap_for_mcp(StandardError.internal(developer_message="trace=abc"))
    assert out["isError"] is True
    assert out["structuredContent"]["error"]["code"] == "INTERNAL_ERROR"
    assert out["structuredContent"]["error"]["retryable"] is True


# --------------------------------------------------------------------------
# Test 8 — opt-in flag parses the vendor Accept header
# --------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, qp: dict[str, str] | None = None, accept: str = ""):
        self.query_params = qp or {}
        self.headers = {"accept": accept}


def test_wants_envelope_v2_ignores_query_param() -> None:
    assert wants_envelope_v2(_FakeRequest(qp={"envelope": "v2"})) is False
    assert wants_envelope_v2(_FakeRequest(qp={"envelope": "V2"})) is False
    assert wants_envelope_v2(_FakeRequest(qp={"envelope": "v1"})) is False
    assert wants_envelope_v2(_FakeRequest(qp={})) is False


def test_wants_envelope_v2_recognises_accept_header() -> None:
    assert wants_envelope_v2(_FakeRequest(accept="application/vnd.jpcite.v2+json")) is True
    assert (
        wants_envelope_v2(_FakeRequest(accept="text/html, application/vnd.jpcite.v2+json")) is True
    )
    assert wants_envelope_v2(_FakeRequest(accept="application/json")) is False


def test_wants_envelope_v2_soft_fails_on_bad_request() -> None:
    """Never raises — returns False on broken duck-typed input."""
    assert wants_envelope_v2(object()) is False


# --------------------------------------------------------------------------
# Bonus — query_echo + citation coercion from dicts
# --------------------------------------------------------------------------


def test_query_echo_accepts_pydantic_or_dict() -> None:
    qe = QueryEcho(
        normalized_input={"q": "hello"},
        applied_filters={"tier": ["S"]},
    )
    env_a = StandardResponse.rich(results=[{"x": 1}], request_id="rid-a", query_echo=qe)
    env_b = StandardResponse.rich(
        results=[{"x": 1}],
        request_id="rid-b",
        query_echo={"normalized_input": {"q": "hello"}, "applied_filters": {"tier": ["S"]}},
    )
    assert env_a.query_echo.normalized_input == env_b.query_echo.normalized_input


def test_citation_coerces_from_dict() -> None:
    env = StandardResponse.rich(
        results=[{"id": 1}],
        request_id="rid-cit-001",
        citations=[{"source_url": "https://example.go.jp/foo", "license": "pdl_v1.0"}],
    )
    assert isinstance(env.citations[0], Citation)
    assert env.citations[0].license == "pdl_v1.0"
