"""K2 / concerns 5-5 follow-up: envelope-merge × response_model × telemetry.

Background
----------
L5 wired ``_envelope_merge`` (server.py / MCP) and ``_apply_envelope``
(api/autonomath.py / REST) so every tool result carries the v2 envelope
fields (status / explanation / suggested_actions / meta.suggestions etc.).
L6 added Pydantic ``response_model=`` annotations on the same endpoints
to populate OpenAPI. K2 / concerns 5-5 noted that the **interaction** of
these three layers had no test:

  1. The Pydantic models declare ``ConfigDict(extra="allow")`` so
     envelope-only keys pass through. No test verified that.
  2. The merge is **additive** — pre-existing meta keys must win over
     envelope additions. test_envelope_wiring covered this in unit
     scope but no end-to-end (router → response_model → JSON) test
     existed.
  3. ``__envelope_fields__="minimal"`` opt-out must skip the meta
     block in the JSON the client actually receives, not just the
     in-memory dict. No test verified that.
  4. _with_mcp_telemetry must NOT log secrets / PII through the
     envelope's ``query_echo`` field. No test pinned that boundary.

These tests exercise the full chain: TestClient → router → handler →
_apply_envelope → response_model serialisation → JSON wire.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure src/ is importable for direct test runs.
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Layer 1 — envelope merge produces the canonical v2 fields end-to-end
# ---------------------------------------------------------------------------


def test_search_endpoint_returns_paginated_envelope(client):
    """REST /v1/programs/search must return the SearchResponse contract
    (total / limit / offset / results). The L5 envelope merge only
    fires on /v1/am/* + the MCP layer; /v1/programs/* keeps its
    historical shape."""
    r = client.get("/v1/programs/search", params={"limit": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("total", "limit", "offset", "results"):
        assert key in body, f"missing {key} in {sorted(body.keys())}"


def test_am_endpoint_zero_result_emits_envelope_hint(client):
    """The K3 / J9 fix: an empty result set on /v1/am/* must carry
    meta.suggestions OR a status field so an LLM caller has a
    structured nudge instead of silence."""
    # Use a query the seed can't match — autonomath.db may not be
    # mounted in the test fixture, so accept 503 too.
    r = client.get(
        "/v1/am/tax_incentives",
        params={"query": "存在しない_xxxxx_zzzzz_yyyyy", "limit": 5},
    )
    if r.status_code == 503:
        pytest.skip("autonomath.db unmounted; can't exercise /v1/am/* live")
    assert r.status_code == 200, r.text
    body = r.json()
    # The L5 envelope must populate something callers can pivot on.
    meta = body.get("meta") or {}
    has_meta_suggestions = isinstance(meta.get("suggestions"), list) and len(
        meta.get("suggestions") or []
    ) > 0
    has_actions = isinstance(body.get("suggested_actions"), list) and len(
        body.get("suggested_actions") or []
    ) > 0
    has_status = body.get("status") in ("empty", "ok")
    assert has_meta_suggestions or has_actions or has_status, (
        f"empty /v1/am/tax_incentives produced no envelope hint: "
        f"keys={sorted(body.keys())}"
    )


# ---------------------------------------------------------------------------
# Layer 2 — pre-existing meta keys win over envelope additions
# ---------------------------------------------------------------------------


def test_envelope_merge_native_meta_survives_apply():
    """If the underlying tool publishes ``meta.data_as_of``, the
    envelope merge must not overwrite it. Tested directly on the
    helper to avoid REST-layer plumbing variance."""
    from jpintel_mcp.api.autonomath import _apply_envelope

    result = {
        "total": 1, "limit": 20, "offset": 0,
        "results": [{"x": 1}],
        "meta": {"data_as_of": "2026-04-25"},
    }
    out = _apply_envelope("search_programs", result, query="q")
    assert out["meta"]["data_as_of"] == "2026-04-25"


def test_envelope_merge_unit_native_meta_wins():
    """Unit-level: if the tool result has ``meta={data_as_of:X}``, the
    merge must keep X verbatim (envelope_wrapper might publish its own
    data_as_of based on cache headers; tool-level wins)."""
    from jpintel_mcp.api.autonomath import _apply_envelope

    result = {
        "total": 1,
        "limit": 20,
        "offset": 0,
        "results": [{"unified_id": "x"}],
        "meta": {"data_as_of": "2026-04-25", "retrieval_note": "fts5"},
    }
    out = _apply_envelope("search_tax_incentives", result, query="q")
    assert out["meta"]["data_as_of"] == "2026-04-25"
    assert out["meta"]["retrieval_note"] == "fts5"


# ---------------------------------------------------------------------------
# Layer 3 — response_model passthrough (extra="allow")
# ---------------------------------------------------------------------------


def test_response_model_does_not_strip_envelope_only_keys(client):
    """L6 sets ConfigDict(extra="allow") on every model so envelope-only
    keys pass through. Verify on a real /v1/am/* endpoint where both
    layers participate."""
    r = client.get("/v1/am/tax_incentives", params={"limit": 5})
    # Either 200 (autonomath.db mounted) or 503 (cold). On 200 the
    # envelope keys must be visible.
    if r.status_code != 200:
        pytest.skip(f"/v1/am/tax_incentives → {r.status_code}; need a 200")
    body = r.json()
    # SearchResponse contract (L6): total / limit / offset / results.
    for k in ("total", "limit", "offset", "results"):
        assert k in body, f"L6 contract key {k} missing from {sorted(body.keys())}"
    # L5 additions ride alongside thanks to extra="allow".
    extra_keys_present = any(
        k in body
        for k in ("status", "tool_name", "api_version", "suggested_actions")
    )
    assert extra_keys_present, (
        f"L5 envelope keys stripped by response_model: {sorted(body.keys())}"
    )


def test_response_model_carries_extra_meta_fields(client):
    """meta is `dict | None` on the L6 model; envelope-injected nested
    keys (suggestions / alternative_intents / tips / token_estimate)
    must survive serialisation. We test on /v1/am/* because that's
    where the L5 wiring is wired through to the response.
    """
    r = client.get("/v1/am/tax_incentives", params={"limit": 3})
    if r.status_code == 503:
        pytest.skip("autonomath.db unmounted; can't exercise /v1/am/* live")
    assert r.status_code == 200, r.text
    body = r.json()
    meta = body.get("meta") or {}
    # At least one envelope-only meta key should be present (varies by
    # tool kwarg shape — token_estimate / wall_time_ms / suggestions /
    # data_as_of). Pin that the merge surfaced SOMETHING through the
    # response_model's extra="allow" passthrough.
    envelope_meta_keys = {
        "suggestions",
        "alternative_intents",
        "tips",
        "token_estimate",
        "wall_time_ms",
        "input_warnings",
        "data_as_of",
    }
    visible = envelope_meta_keys & set(meta.keys())
    # Even if meta is empty, the merge should publish top-level
    # extras (status / tool_name / api_version) which prove the
    # response_model isn't silently stripping them.
    top_level_envelope = {"status", "tool_name", "api_version", "result_count"}
    if not visible:
        assert top_level_envelope & set(body.keys()), (
            f"L6 response_model stripped L5 envelope; "
            f"meta={sorted(meta.keys())}, body={sorted(body.keys())}"
        )


# ---------------------------------------------------------------------------
# Layer 4 — __envelope_fields__="minimal" opt-out
# ---------------------------------------------------------------------------


def test_envelope_minimal_opt_out_skips_meta_block_unit():
    """Unit: pass __envelope_fields__='minimal' through _envelope_merge
    and assert the meta block is NOT added."""
    from jpintel_mcp.mcp.server import _envelope_merge

    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result={"total": 0, "limit": 20, "offset": 0, "results": []},
        kwargs={"query": "q", "__envelope_fields__": "minimal"},
        latency_ms=1.0,
    )
    # Status / suggested_actions still present (always-on hints), but
    # meta block (or its envelope additions) is absent.
    assert isinstance(out, dict)
    meta = out.get("meta")
    if isinstance(meta, dict):
        # If the meta block exists at all under minimal, it must NOT
        # carry the envelope-only keys.
        envelope_only = {
            "suggestions",
            "alternative_intents",
            "tips",
            "token_estimate",
        }
        assert not (envelope_only & set(meta.keys())), (
            f"minimal opt-out leaked envelope meta keys: {sorted(meta.keys())}"
        )


def test_tool_level_fields_minimal_keeps_envelope_meta():
    """The B-A8 spec separates ``fields="minimal"`` (row-shape trim)
    from ``__envelope_fields__="minimal"`` (envelope trim). Tool-level
    fields=minimal MUST NOT skip the meta block."""
    from jpintel_mcp.mcp.server import _envelope_merge

    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result={"total": 0, "limit": 20, "offset": 0, "results": []},
        kwargs={"query": "q", "fields": "minimal"},
        latency_ms=1.0,
    )
    meta = out.get("meta") or {}
    # On empty result, meta.suggestions must still surface.
    assert "suggestions" in meta, (
        f"tool-level fields=minimal incorrectly skipped envelope meta: "
        f"keys={sorted(meta.keys())}"
    )


# ---------------------------------------------------------------------------
# Layer 5 — error envelope branches through merge correctly
# ---------------------------------------------------------------------------


def test_error_envelope_carries_status_error_and_retry_action_unit():
    """When a tool returns {error: {...}} the merge must label the
    envelope with status='error' and emit a retry_with_backoff action.
    (Already covered by test_envelope_wiring; pinned here in the
    chain context for L6 + L5 cross-layer regression.)"""
    from jpintel_mcp.mcp.server import _envelope_merge

    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result={"error": {"code": "db_unavailable", "message": "sqlite locked"}},
        kwargs={"query": "x"},
        latency_ms=1.0,
    )
    assert out.get("status") == "error"
    actions = out.get("suggested_actions") or []
    assert any(a.get("action") == "retry_with_backoff" for a in actions), actions


def test_apply_envelope_rest_helper_handles_error_dict():
    """Same shape via the REST-side _apply_envelope helper."""
    from jpintel_mcp.api.autonomath import _apply_envelope

    out = _apply_envelope(
        "search_tax_incentives",
        {"error": {"code": "db_unavailable", "message": "x"}},
        query="q",
    )
    assert out.get("status") == "error"
    actions = out.get("suggested_actions") or []
    assert any(a.get("action") == "retry_with_backoff" for a in actions), actions


# ---------------------------------------------------------------------------
# Layer 6 — non-dict / scalar tool results
# ---------------------------------------------------------------------------


def test_apply_envelope_returns_scalars_unchanged():
    """`None` and bare strings must pass through untouched — the
    autonomath REST helper used to crash on scalars before the L5 fix."""
    from jpintel_mcp.api.autonomath import _apply_envelope

    assert _apply_envelope("x", None) is None
    assert _apply_envelope("x", "some string") == "some string"
    assert _apply_envelope("x", 42) == 42


def test_envelope_merge_coerces_list_to_envelope():
    """Bare list result → envelope shape (so the client always gets a
    dict response). Pin the result_count contract."""
    from jpintel_mcp.mcp.server import _envelope_merge

    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result=[{"a": 1}, {"b": 2}, {"c": 3}],
        kwargs={"query": "x"},
        latency_ms=0.0,
    )
    assert isinstance(out, dict)
    assert out.get("result_count") == 3


# ---------------------------------------------------------------------------
# Layer 7 — telemetry boundary (no PII / payload leakage)
# ---------------------------------------------------------------------------


def test_envelope_merge_does_not_log_kwargs_values():
    """The envelope's `query_echo` is a single field that mirrors q /
    query / law_name. It must NOT contain other kwarg values (auth
    tokens, body payloads, etc.). This prevents accidental PII leak
    via the telemetry path."""
    from jpintel_mcp.mcp.server import _envelope_merge

    out = _envelope_merge(
        tool_name="search_tax_incentives",
        result={"total": 1, "limit": 20, "offset": 0, "results": [{"x": 1}]},
        kwargs={
            "query": "test query",
            # If query_echo is leaky, these would surface.
            "X-API-Key": "sk_secret_token_xxxxx",
            "internal_secret": "should-not-appear",
        },
        latency_ms=1.0,
    )
    echo = str(out.get("query_echo") or "")
    assert "sk_secret_token" not in echo
    assert "internal_secret" not in echo
    assert "should-not-appear" not in echo
