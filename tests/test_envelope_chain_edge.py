"""5-5: 3-layer envelope chain edge-case coverage (M9).

The envelope contract spans three coordinated layers:

  L4  envelope_wrapper.build_envelope         (canonical envelope synthesis)
  L5  server._envelope_merge / api._apply_envelope
                                               (additive merge onto raw tool out)
  L6  api/_response_models.SearchResponse(extra="allow")
                                               (Pydantic passthrough on the wire)

The launch CLI's absorption pass left several edge cases under-tested:

  1. Native ``meta`` (``data_as_of``) — must NOT be overwritten.
  2. No native ``meta`` — envelope must ADD meta.suggestions / etc.
  3. ``response_model`` w/ ``extra="allow"`` — every envelope-only key must
     survive Pydantic serialisation (no silent strip).
  4. ``__envelope_fields__="minimal"`` — opt-out must drop meta entirely.
  5. REST ``_apply_envelope`` — wire response carries the 8 envelope keys.
  6. MCP ``_with_mcp_telemetry`` — decorator must call ``_envelope_merge``
     so wrapping a tool function injects envelope keys.
  7. Conflict on ``status`` — original tool key wins on additive merge.
  8. ``fields="minimal"`` (row whitelist trim) vs
     ``__envelope_fields__="minimal"`` (envelope opt-out) — distinct signals.

These are the 3-layer interaction edge cases. Production code is read-only;
tests target only the public ``_envelope_merge`` / ``_apply_envelope`` /
``_with_mcp_telemetry`` / ``SearchResponse`` surfaces.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure src/ is importable for direct test runs (mirrors test_envelope_wiring).
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# Envelope-only keys added on top of the raw tool result by the L5 merge.
# Must match server._envelope_merge ``additive_keys`` tuple.
_MCP_ENVELOPE_ADDITIVE = (
    "status",
    "result_count",
    "explanation",
    "suggested_actions",
    "api_version",
    "tool_name",
    "query_echo",
    "latency_ms",
    "evidence_source_count",
)

# REST side has the same set MINUS latency_ms (api/_apply_envelope omits it
# because the REST timing is captured at the FastAPI middleware layer).
_REST_ENVELOPE_ADDITIVE = (
    "status",
    "result_count",
    "explanation",
    "suggested_actions",
    "api_version",
    "tool_name",
    "query_echo",
    "evidence_source_count",
)


def _import_envelope_merge():
    from jpintel_mcp.mcp.server import _envelope_merge

    return _envelope_merge


def _import_apply_envelope():
    from jpintel_mcp.api.autonomath import _apply_envelope

    return _apply_envelope


# ---------------------------------------------------------------------------
# 1. Native meta wins — envelope must not overwrite tool-published keys.
# ---------------------------------------------------------------------------


def test_native_meta_data_as_of_wins_over_envelope():
    """Tool returns ``meta.data_as_of`` → merge layer keeps it; envelope
    adds the OTHER meta keys (suggestions / wall_time_ms / token_estimate)
    alongside, never displacing data_as_of."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
        "meta": {"data_as_of": "2026-04-25"},
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "存在しないクエリ_xxxxxx"},
        latency_ms=4.2,
    )

    meta = merged.get("meta") or {}
    # Original native key preserved verbatim.
    assert meta.get("data_as_of") == "2026-04-25"
    # Envelope keys are additive — at least one of them lands.
    assert any(k in meta for k in (
        "suggestions", "wall_time_ms", "token_estimate", "tips",
        "alternative_intents", "input_warnings",
    ))


# ---------------------------------------------------------------------------
# 2. No native meta — envelope synthesises one.
# ---------------------------------------------------------------------------


def test_no_native_meta_envelope_adds_meta_block():
    """Tool returns no ``meta`` → envelope synthesises it (suggestions on empty)."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    assert "meta" not in result

    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "存在しないクエリ_yyyyyy"},
        latency_ms=2.0,
    )

    meta = merged.get("meta")
    assert isinstance(meta, dict)
    # For empty-status tax_incentives, suggestions is the canonical hint.
    assert isinstance(meta.get("suggestions"), list)
    assert len(meta["suggestions"]) > 0


# ---------------------------------------------------------------------------
# 3. response_model ``extra="allow"`` passes envelope-only keys to the wire.
# ---------------------------------------------------------------------------


def test_response_model_extra_allow_passes_envelope_keys():
    """SearchResponse(extra='allow') must NOT strip envelope-only keys when
    serialising for the wire. This is the L6 contract that lets L5 keep
    extending without breaking JSON output."""
    from jpintel_mcp.api._response_models import SearchResponse

    payload = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
        # Envelope-only fields that L6 must not strip.
        "status": "empty",
        "result_count": 0,
        "explanation": "該当する情報は当 DB に収録されていません。条件を広げてください。",
        "suggested_actions": [{"action": "broaden_query", "details": "..."}],
        "api_version": "1.1",
        "tool_name": "search_tax_incentives",
        "query_echo": "test",
        "latency_ms": 1.5,
        "evidence_source_count": 0,
        "meta": {"suggestions": ["税額控除を試してください"]},
    }

    model = SearchResponse[dict[str, Any]](**payload)
    serialised = model.model_dump()
    # All 9 envelope-only keys must survive the round-trip.
    for key in _MCP_ENVELOPE_ADDITIVE:
        assert key in serialised, f"L6 stripped envelope key {key!r}"
    # Nested meta also passes.
    assert "suggestions" in serialised.get("meta") or {}


# ---------------------------------------------------------------------------
# 4. __envelope_fields__='minimal' — opt-out drops the meta block entirely.
# ---------------------------------------------------------------------------


def test_envelope_fields_minimal_drops_meta_block():
    """The control-plane kwarg ``__envelope_fields__='minimal'`` must skip
    the meta synthesis — caller asked for a slim envelope."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "test", "__envelope_fields__": "minimal"},
        latency_ms=1.0,
    )

    # Status / suggested_actions are always-on hints (not in meta).
    assert merged.get("status") == "empty"
    # Meta block is suppressed: either absent, None, or empty.
    meta = merged.get("meta")
    assert meta is None or "suggestions" not in (meta or {})


# ---------------------------------------------------------------------------
# 5. REST _apply_envelope — wire response carries envelope keys.
# ---------------------------------------------------------------------------


def test_rest_apply_envelope_returns_envelope_keys(client):
    """Hitting an /v1/am/* endpoint with an empty-result query must yield
    a JSON body with the envelope-only keys merged on top of the SearchResponse
    contract. Skip cleanly if the endpoint is not reachable in this test env
    (AUTONOMATH_ENABLED off / quota exhausted)."""
    r = client.get(
        "/v1/am/intent",
        params={"query": "存在しない検索ワード_xxxxxxxxxxx"},
    )
    if r.status_code != 200:
        pytest.skip(
            f"/v1/am/intent returned {r.status_code} — "
            "skipping envelope assertion (AUTONOMATH_ENABLED off / quota / 4xx)."
        )
    body = r.json()

    # Envelope status bucket present (intent_of returns dict, not list).
    assert "status" in body
    assert body["status"] in ("rich", "sparse", "empty", "error")
    # Tool name + query_echo round-trip the route-level _apply_envelope call.
    assert body.get("tool_name") == "intent_of"
    assert body.get("query_echo") == "存在しない検索ワード_xxxxxxxxxxx"
    # api_version is the L4 contract version.
    assert body.get("api_version")  # non-empty
    # Suggested actions is always populated for non-rich buckets.
    assert isinstance(body.get("suggested_actions"), list)


def test_rest_apply_envelope_helper_emits_eight_keys():
    """Direct unit-level check of the REST helper's additive key set
    (avoids the FastAPI client + AUTONOMATH_ENABLED gate)."""
    _apply_envelope = _import_apply_envelope()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }
    out = _apply_envelope(
        "search_tax_incentives", result, query="zzzzzzzzz_no_match",
    )
    # All 8 REST-side envelope keys must land on the merged dict.
    for key in _REST_ENVELOPE_ADDITIVE:
        assert key in out, f"_apply_envelope dropped {key!r}"
    # latency_ms is intentionally NOT added by the REST helper (FastAPI
    # captures timing separately) — confirm the documented divergence.
    assert "latency_ms" not in out or out["latency_ms"] == 0.0


# ---------------------------------------------------------------------------
# 6. MCP-side: _with_mcp_telemetry must invoke _envelope_merge internally.
# ---------------------------------------------------------------------------


def test_with_mcp_telemetry_invokes_envelope_merge():
    """Wrapping a plain function with ``@_with_mcp_telemetry`` must produce
    an envelope-shaped return value (status / suggested_actions / etc.).
    This is the wiring that ensures every @mcp.tool gets envelope keys
    without per-tool plumbing."""
    from jpintel_mcp.mcp.server import _with_mcp_telemetry

    @_with_mcp_telemetry
    def fake_search_programs(*, q: str = "") -> dict[str, Any]:
        return {
            "total": 0,
            "limit": 20,
            "offset": 0,
            "results": [],
        }

    out = fake_search_programs(q="完全にヒットしない検索語_qqqqqq")
    assert isinstance(out, dict)
    # Decorator merged envelope keys onto the raw tool return.
    assert out.get("status") == "empty"
    assert isinstance(out.get("suggested_actions"), list)
    assert out.get("tool_name") == "fake_search_programs"
    assert out.get("query_echo") == "完全にヒットしない検索語_qqqqqq"
    # latency_ms is set by the decorator (>= 0, may be 0.0 on a tight loop).
    assert isinstance(out.get("latency_ms"), (int, float))
    assert out["latency_ms"] >= 0.0


# ---------------------------------------------------------------------------
# 7. Native key wins on conflict — original status/result_count are sticky.
# ---------------------------------------------------------------------------


def test_native_status_key_wins_over_envelope():
    """Tool that publishes its own ``status='success'`` must not be
    rebadged as ``'empty'`` by the additive merge — original key wins."""
    _envelope_merge = _import_envelope_merge()

    result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
        # Tool-supplied status (legacy / non-canonical bucket).
        "status": "success",
    }
    merged = _envelope_merge(
        tool_name="search_tax_incentives",
        result=result,
        kwargs={"query": "x"},
        latency_ms=1.0,
    )

    # Original status preserved (additive merge — never overwrites).
    assert merged["status"] == "success"
    # Envelope still adds the OTHER hint keys around it.
    assert isinstance(merged.get("suggested_actions"), list)
    assert merged.get("tool_name") == "search_tax_incentives"


# ---------------------------------------------------------------------------
# 8. fields="minimal" (row trim) vs __envelope_fields__="minimal" (env opt-out)
# ---------------------------------------------------------------------------


def test_tool_fields_minimal_distinct_from_envelope_fields_minimal():
    """The two ``minimal`` kwargs are DIFFERENT signals:

       fields="minimal"            → search_programs row whitelist trim
       __envelope_fields__="minimal" → drop envelope meta block

    Conflating them was the original β1 wiring regression. This test pins
    the distinction in place: ``fields=minimal`` MUST keep meta;
    ``__envelope_fields__=minimal`` MUST drop it.
    """
    _envelope_merge = _import_envelope_merge()

    base_result = {
        "total": 0,
        "limit": 20,
        "offset": 0,
        "results": [],
    }

    # (a) tool-level fields=minimal → meta block STILL present.
    merged_tool_minimal = _envelope_merge(
        tool_name="search_tax_incentives",
        result=dict(base_result),
        kwargs={"query": "test", "fields": "minimal"},
        latency_ms=2.0,
    )
    meta_a = merged_tool_minimal.get("meta") or {}
    assert isinstance(meta_a.get("suggestions"), list), (
        "fields='minimal' (row trim) MUST NOT strip the envelope meta block"
    )
    assert len(meta_a["suggestions"]) > 0

    # (b) envelope-level __envelope_fields__=minimal → meta block GONE.
    merged_env_minimal = _envelope_merge(
        tool_name="search_tax_incentives",
        result=dict(base_result),
        kwargs={"query": "test", "__envelope_fields__": "minimal"},
        latency_ms=2.0,
    )
    meta_b = merged_env_minimal.get("meta")
    assert meta_b is None or "suggestions" not in (meta_b or {}), (
        "__envelope_fields__='minimal' MUST drop the meta block"
    )

    # Final invariant: the two kwargs produce DIFFERENT meta states given
    # otherwise identical inputs. If a future regression makes them aliases,
    # this assertion fails loudly.
    a_has_meta = isinstance(meta_a.get("suggestions"), list) and meta_a["suggestions"]
    b_has_meta = isinstance((merged_env_minimal.get("meta") or {}).get("suggestions"), list)
    assert a_has_meta and not b_has_meta, (
        "fields=minimal and __envelope_fields__=minimal must remain distinct signals"
    )
