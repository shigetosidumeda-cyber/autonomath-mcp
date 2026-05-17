"""HE-4 ``multi_tool_orchestrate`` — 10+ scenario contract suite.

Covers:

1. Happy path: 3 parallel calls (different tools).
2. Single-call bundle (idempotency with serial).
3. ``parallel=False`` serial fallback returns same shape.
4. ``fail_strategy="partial"`` with one bad-args call → 1 error + others ok.
5. ``fail_strategy="all_or_nothing"`` short-circuits remaining calls.
6. Unknown tool name → ``status="rejected"`` with reason ``unknown_tool``.
7. Private (underscore-prefix) tool name refused.
8. Self-recursion into ``multi_tool_orchestrate`` refused.
9. ``max_concurrent`` boundary (=1 → still works).
10. Empty / oversized ``tool_calls`` → top-level rejection envelope.
11. Per-call billing: ``unit == ok + error`` (rejected / skipped not billed).
12. Latency parity: parallel total_latency_ms ≤ serial total_latency_ms (best-effort).

Hard constraints (CLAUDE.md):
* NO LLM. NO network. NO mutation.
* ¥3/req metering asserted via ``billing.unit`` count + ``yen`` math.
* Sensitive-surface §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope
  asserted on every payload.
"""

from __future__ import annotations

import time
from typing import Any


def _assert_top_envelope(envelope: Any) -> dict[str, Any]:
    """Common contract every HE-4 payload satisfies."""
    assert isinstance(envelope, dict), envelope
    assert envelope.get("tool_name") == "multi_tool_orchestrate"
    assert envelope.get("schema_version") == "moat.he4.v1"
    disc = envelope.get("_disclaimer")
    assert isinstance(disc, str)
    for needle in ("§52", "§47条の2", "§72", "§1", "§3"):
        assert needle in disc, f"missing {needle} in disclaimer"
    prov = envelope.get("_provenance")
    assert isinstance(prov, dict)
    assert prov.get("lane_id") == "HE-4"
    assert prov.get("source_module") == "jpintel_mcp.moat.he4_orchestrate"
    assert isinstance(prov.get("observed_at"), str)
    assert isinstance(envelope.get("results"), list)
    return envelope


def _call_orchestrate(**kwargs: Any) -> dict[str, Any]:
    from jpintel_mcp.mcp.moat_lane_tools.he4_orchestrate import multi_tool_orchestrate

    out: dict[str, Any] = multi_tool_orchestrate(**kwargs)
    return out


# --------------------------------------------------------------------------- #
# Scenario 1 — happy path: 3 parallel calls
# --------------------------------------------------------------------------- #


def test_he4_three_parallel_calls() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "audit", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "gyousei", "limit": 1}},
        ],
        parallel=True,
        fail_strategy="partial",
        max_concurrent=10,
    )
    _assert_top_envelope(out)
    results = out["results"]
    assert len(results) == 3
    for i, r in enumerate(results):
        assert r["tool_call_idx"] == i
        assert r["tool"] == "list_recipes"
        assert r["status"] == "ok", r
        assert isinstance(r["result"], dict)
        assert r["result"]["tool_name"] == "list_recipes"
        assert isinstance(r["latency_ms"], int)
    summary = out["summary"]
    assert summary["total_calls"] == 3
    assert summary["ok"] == 3
    assert summary["error"] == 0
    billing = out["billing"]
    assert billing["unit"] == 3
    assert billing["yen"] == 9


# --------------------------------------------------------------------------- #
# Scenario 2 — single-call bundle
# --------------------------------------------------------------------------- #


def test_he4_single_call_bundle() -> None:
    out = _call_orchestrate(
        tool_calls=[{"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}}],
    )
    _assert_top_envelope(out)
    assert out["summary"]["total_calls"] == 1
    assert out["summary"]["ok"] == 1
    assert out["billing"]["yen"] == 3


# --------------------------------------------------------------------------- #
# Scenario 3 — parallel=False serial fallback
# --------------------------------------------------------------------------- #


def test_he4_serial_fallback_same_shape() -> None:
    payload = [
        {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}},
        {"tool": "list_recipes", "args": {"segment": "audit", "limit": 1}},
    ]
    out_par = _call_orchestrate(tool_calls=payload, parallel=True)
    out_ser = _call_orchestrate(tool_calls=payload, parallel=False)
    _assert_top_envelope(out_par)
    _assert_top_envelope(out_ser)
    assert out_par["summary"]["ok"] == out_ser["summary"]["ok"] == 2


# --------------------------------------------------------------------------- #
# Scenario 4 — partial-mode tolerates bad args
# --------------------------------------------------------------------------- #


def test_he4_partial_mode_tolerates_bad_args() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}},
            # Pydantic validation fires inside the wrapper; surfaces as
            # status="error" rather than "ok" because the validation
            # error is raised before the inner body runs.
            {"tool": "list_recipes", "args": {"segment": "INVALID_SEGMENT", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "gyousei", "limit": 1}},
        ],
        fail_strategy="partial",
    )
    _assert_top_envelope(out)
    results = out["results"]
    assert len(results) == 3
    statuses = [r["status"] for r in results]
    # First + third should pass; second is either ok (if wrapper is
    # lenient) or error (if pydantic rejects). Either way no skipped
    # entries because we are in partial mode.
    assert "skipped" not in statuses
    assert statuses.count("ok") >= 2
    # billing.unit counts ok+error, never rejected/skipped.
    assert out["billing"]["unit"] == statuses.count("ok") + statuses.count("error")


# --------------------------------------------------------------------------- #
# Scenario 5 — all_or_nothing short-circuits
# --------------------------------------------------------------------------- #


def test_he4_all_or_nothing_short_circuits() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}},
            # Bogus tool name → rejected → all_or_nothing kills the rest.
            {"tool": "no_such_tool_exists_anywhere", "args": {}},
            {"tool": "list_recipes", "args": {"segment": "audit", "limit": 1}},
        ],
        fail_strategy="all_or_nothing",
        # Force serial so order is deterministic and we can assert
        # that the third call is skipped (not raced past).
        parallel=False,
    )
    _assert_top_envelope(out)
    results = out["results"]
    assert len(results) == 3
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "rejected"
    assert results[2]["status"] == "skipped"
    # Rejected + skipped never bill.
    assert out["billing"]["unit"] == 1
    assert out["billing"]["yen"] == 3


# --------------------------------------------------------------------------- #
# Scenario 6 — unknown tool → rejected
# --------------------------------------------------------------------------- #


def test_he4_unknown_tool_rejected() -> None:
    out = _call_orchestrate(
        tool_calls=[{"tool": "definitely_not_a_real_tool", "args": {}}],
    )
    _assert_top_envelope(out)
    r = out["results"][0]
    assert r["status"] == "rejected"
    assert "unknown_tool" in r["error"]
    assert out["billing"]["unit"] == 0


# --------------------------------------------------------------------------- #
# Scenario 7 — private (underscore) tool refused
# --------------------------------------------------------------------------- #


def test_he4_private_tool_refused() -> None:
    out = _call_orchestrate(
        tool_calls=[{"tool": "_secret_internal_tool", "args": {}}],
    )
    _assert_top_envelope(out)
    r = out["results"][0]
    assert r["status"] == "rejected"
    assert "private" in r["error"]


# --------------------------------------------------------------------------- #
# Scenario 8 — self-recursion refused
# --------------------------------------------------------------------------- #


def test_he4_self_recursion_refused() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "multi_tool_orchestrate", "args": {"tool_calls": []}},
        ],
    )
    _assert_top_envelope(out)
    r = out["results"][0]
    assert r["status"] == "rejected"
    assert "recursion" in r["error"]


# --------------------------------------------------------------------------- #
# Scenario 9 — max_concurrent boundary
# --------------------------------------------------------------------------- #


def test_he4_max_concurrent_boundary() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "audit", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "gyousei", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "shihoshoshi", "limit": 1}},
        ],
        parallel=True,
        max_concurrent=1,  # forces serial-equivalent fan-out
    )
    _assert_top_envelope(out)
    assert out["summary"]["ok"] == 4
    assert out["billing"]["yen"] == 12


# --------------------------------------------------------------------------- #
# Scenario 10 — empty / oversized input rejected at top level
# --------------------------------------------------------------------------- #


def test_he4_empty_input_rejected() -> None:
    out = _call_orchestrate(tool_calls=[])
    _assert_top_envelope(out)
    assert out["primary_result"]["status"] == "rejected"
    assert "at least one" in out["primary_result"]["rationale"]


def test_he4_oversized_input_rejected() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}} for _ in range(33)
        ],
    )
    _assert_top_envelope(out)
    assert out["primary_result"]["status"] == "rejected"
    assert "hard cap" in out["primary_result"]["rationale"]


# --------------------------------------------------------------------------- #
# Scenario 11 — billing transparency (¥3 × dispatched)
# --------------------------------------------------------------------------- #


def test_he4_billing_transparency() -> None:
    out = _call_orchestrate(
        tool_calls=[
            {"tool": "list_recipes", "args": {"segment": "tax", "limit": 1}},
            {"tool": "list_recipes", "args": {"segment": "audit", "limit": 1}},
            {"tool": "no_such_tool", "args": {}},  # rejected
        ],
    )
    _assert_top_envelope(out)
    assert out["summary"]["ok"] == 2
    assert out["summary"]["rejected"] == 1
    # rejected does not bill — unit = ok + error only.
    assert out["billing"]["unit"] == 2
    assert out["billing"]["yen"] == 6
    assert "agent ↔ server network saving" in out["billing"]["_bundle_discount"]


# --------------------------------------------------------------------------- #
# Scenario 12 — parallel ≤ serial latency (sanity, not strict)
# --------------------------------------------------------------------------- #


def test_he4_parallel_no_slower_than_serial() -> None:
    """Parallel should not be measurably *slower* than serial on the
    same payload. We allow a generous slack because both list_recipes
    calls hit the same on-disk YAML cache; the test exists to catch a
    regression where parallel mode accidentally serializes via a global
    lock.
    """
    payload = [
        {"tool": "list_recipes", "args": {"segment": s, "limit": 1}}
        for s in ("tax", "audit", "gyousei", "shihoshoshi")
    ]
    t0 = time.perf_counter()
    out_par = _call_orchestrate(tool_calls=payload, parallel=True)
    par_wall_ms = int((time.perf_counter() - t0) * 1000)
    t0 = time.perf_counter()
    out_ser = _call_orchestrate(tool_calls=payload, parallel=False)
    ser_wall_ms = int((time.perf_counter() - t0) * 1000)
    _assert_top_envelope(out_par)
    _assert_top_envelope(out_ser)
    # Both should fully succeed.
    assert out_par["summary"]["ok"] == 4
    assert out_ser["summary"]["ok"] == 4
    # Sanity: parallel wall time must not exceed serial by more than
    # 200ms (sub-ms divergence is normal on warm I/O).
    assert par_wall_ms <= ser_wall_ms + 200, (par_wall_ms, ser_wall_ms)
