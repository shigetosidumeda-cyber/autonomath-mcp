"""Performance regression tests for the jpcite P0 facade hot path.

These are lightweight, deterministic timing checks intended to hang off the
production deploy readiness gate. They guard against accidental regressions
where a refactor turns a pure in-memory call into something that touches the
database, the network, or an LLM.

Design constraints:
- No LLM, no DB, no AWS, no network, no clock-dependent state.
- Pure ``time.perf_counter()`` measurement, no ``pytest-benchmark`` dependency.
- Thresholds are deliberately generous so that slow CI runners do not flake
  the gate. The numbers are sized to detect order-of-magnitude regressions,
  not micro-optimization slips.
- Each test is wrapped in ``pytest.mark.benchmark`` so the suite can be
  skipped on resource-constrained CI runners via
  ``pytest -m 'not benchmark'`` if needed; by default the marker is a no-op
  and the tests run as part of the standard suite.

This file is test-only. It must not import or mutate any production logic.
"""

from __future__ import annotations

import time

import pytest

from jpintel_mcp.agent_runtime.contracts import PolicyDecision, SpendSimulation
from jpintel_mcp.agent_runtime.outcome_routing import (
    outcome_contract_ids,
    preview_for_outcome,
    resolve_outcome_entry,
)
from jpintel_mcp.mcp.autonomath_tools.jpcite_facade import (
    _impl_jpcite_get_packet,
    _impl_jpcite_preview_cost,
    _impl_jpcite_route,
)
from jpintel_mcp.services.packets.inline_registry import (
    inline_packet_registry_shape,
)

# Module-level cold timing budgets (milliseconds). Thresholds are generous so
# that slow shared CI runners do not flake on momentary system load. They are
# sized to catch order-of-magnitude regressions (e.g. accidental DB call).
_THRESHOLD_MS_JPCITE_ROUTE = 50.0
_THRESHOLD_MS_JPCITE_PREVIEW_COST = 50.0
_THRESHOLD_MS_JPCITE_GET_PACKET_INLINE = 30.0
_THRESHOLD_MS_RESOLVE_OUTCOME_ENTRY = 5.0
_THRESHOLD_MS_PREVIEW_FOR_OUTCOME = 10.0
_THRESHOLD_MS_ALL_OUTCOMES_PREVIEW = 50.0
_THRESHOLD_MS_INLINE_PACKET_REGISTRY = 1.0
_THRESHOLD_MS_NORMALIZE_TOKEN_BATCH = 10.0  # 100 calls
_THRESHOLD_MS_POLICY_DECISION_VALIDATE = 1.0
_THRESHOLD_MS_SPEND_SIM_ROUNDTRIP = 5.0


def _measure_ms(func, *args, **kwargs) -> tuple[float, object]:
    """Return ``(elapsed_ms, return_value)`` for a single function call."""

    start = time.perf_counter()
    value = func(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return elapsed_ms, value


@pytest.mark.benchmark
def test_perf_jpcite_route_cold_call_under_50ms() -> None:
    """``jpcite_route`` must not regress into a DB / network call path."""

    elapsed_ms, result = _measure_ms(
        _impl_jpcite_route,
        goal="会社の公的情報から根拠付きの確認資料を作りたい",
        input_kind="company",
        max_price_jpy=600,
    )
    assert result["billable"] is False
    assert elapsed_ms < _THRESHOLD_MS_JPCITE_ROUTE, (
        f"jpcite_route cold call took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_JPCITE_ROUTE}ms)"
    )


@pytest.mark.benchmark
def test_perf_jpcite_preview_cost_cold_call_under_50ms() -> None:
    """``jpcite_preview_cost`` is pure dict assembly — must stay under 50ms."""

    elapsed_ms, result = _measure_ms(
        _impl_jpcite_preview_cost,
        outcome_contract_id="evidence_answer",
        max_price_jpy=600,
    )
    assert result["billable"] is False
    assert elapsed_ms < _THRESHOLD_MS_JPCITE_PREVIEW_COST, (
        f"jpcite_preview_cost cold call took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_JPCITE_PREVIEW_COST}ms)"
    )


@pytest.mark.benchmark
def test_perf_jpcite_get_packet_inline_cold_call_under_30ms() -> None:
    """``jpcite_get_packet`` for an inline static packet — no DB, no AWS."""

    elapsed_ms, result = _measure_ms(
        _impl_jpcite_get_packet,
        packet_id="source_receipt_ledger",
    )
    assert result["billable"] is False
    assert result["status"] == "inline_static_packet"
    assert elapsed_ms < _THRESHOLD_MS_JPCITE_GET_PACKET_INLINE, (
        f"jpcite_get_packet (inline) cold call took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_JPCITE_GET_PACKET_INLINE}ms)"
    )


@pytest.mark.benchmark
def test_perf_resolve_outcome_entry_cold_call_under_5ms() -> None:
    """``resolve_outcome_entry`` is a pure in-memory catalog lookup."""

    elapsed_ms, entry = _measure_ms(
        resolve_outcome_entry,
        outcome_contract_id="evidence_answer",
    )
    assert entry is not None
    assert elapsed_ms < _THRESHOLD_MS_RESOLVE_OUTCOME_ENTRY, (
        f"resolve_outcome_entry cold call took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_RESOLVE_OUTCOME_ENTRY}ms)"
    )


@pytest.mark.benchmark
def test_perf_preview_for_outcome_cold_call_under_10ms() -> None:
    """``preview_for_outcome`` deterministic preview assembly under 10ms."""

    elapsed_ms, preview = _measure_ms(
        preview_for_outcome,
        "company_public_baseline",
        600,
    )
    assert preview["billable"] is False
    assert elapsed_ms < _THRESHOLD_MS_PREVIEW_FOR_OUTCOME, (
        f"preview_for_outcome cold call took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_PREVIEW_FOR_OUTCOME}ms)"
    )


@pytest.mark.benchmark
def test_perf_all_outcome_previews_under_50ms_total() -> None:
    """Every outcome in the catalog must preview in aggregate under 50ms."""

    ids = outcome_contract_ids()
    # The catalog is the live source of truth; we expect at least 14 entries.
    assert len(ids) >= 14, f"expected >=14 outcomes, got {len(ids)}"

    start = time.perf_counter()
    for contract_id in ids:
        preview = preview_for_outcome(contract_id, 600)
        assert preview["billable"] is False
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < _THRESHOLD_MS_ALL_OUTCOMES_PREVIEW, (
        f"all {len(ids)} outcome previews took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_ALL_OUTCOMES_PREVIEW}ms)"
    )


@pytest.mark.benchmark
def test_perf_inline_packet_registry_shape_under_1ms() -> None:
    """``inline_packet_registry_shape`` is a tiny constant — must be <1ms."""

    elapsed_ms, shape = _measure_ms(inline_packet_registry_shape)
    assert shape["billable"] is False
    assert elapsed_ms < _THRESHOLD_MS_INLINE_PACKET_REGISTRY, (
        f"inline_packet_registry_shape call took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_INLINE_PACKET_REGISTRY}ms)"
    )


@pytest.mark.benchmark
def test_perf_normalize_route_token_100_calls_under_10ms() -> None:
    """``normalize_route_token`` must average <0.1ms / call across 100 calls."""

    from jpintel_mcp.agent_runtime.outcome_routing import normalize_route_token

    tokens = [
        "company",
        "invoice",
        "subsidy",
        "law",
        "court",
        "statistics",
        "monthly_review",
        "csv_subsidy",
        "会社",
        "補助金",
    ]
    start = time.perf_counter()
    for _ in range(10):  # 10 * 10 = 100 calls
        for token in tokens:
            normalize_route_token(token)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < _THRESHOLD_MS_NORMALIZE_TOKEN_BATCH, (
        f"normalize_route_token x100 took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_NORMALIZE_TOKEN_BATCH}ms, "
        f"~{elapsed_ms / 100:.4f}ms/call)"
    )


@pytest.mark.benchmark
def test_perf_policy_decision_pydantic_validation_under_1ms() -> None:
    """``PolicyDecision`` Pydantic validation for a typical row under 1ms."""

    elapsed_ms, pd = _measure_ms(
        PolicyDecision,
        policy_decision_id="pd-perf-1",
        policy_state="allow",
        source_terms_contract_id="src-perf",
        administrative_info_class="C",
        privacy_taint_level="none",
        public_compile_allowed=True,
    )
    assert pd.public_compile_allowed is True
    assert elapsed_ms < _THRESHOLD_MS_POLICY_DECISION_VALIDATE, (
        f"PolicyDecision validation took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_POLICY_DECISION_VALIDATE}ms)"
    )


@pytest.mark.benchmark
def test_perf_spend_simulation_roundtrip_under_5ms() -> None:
    """``SpendSimulation`` construction + ``model_dump`` round-trip under 5ms."""

    start = time.perf_counter()
    sim = SpendSimulation(
        simulation_id="sim-perf-1",
        control_spend_usd=100.0,
        queue_exposure_usd=10.0,
        service_tail_risk_usd=10.0,
        teardown_debt_usd=10.0,
        ineligible_charge_uncertainty_reserve_usd=10.0,
        pass_state=False,
    )
    dumped = sim.model_dump(mode="json")
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert dumped["simulation_id"] == "sim-perf-1"
    assert dumped["pass_state"] is False
    assert elapsed_ms < _THRESHOLD_MS_SPEND_SIM_ROUNDTRIP, (
        f"SpendSimulation roundtrip took {elapsed_ms:.3f}ms "
        f"(threshold {_THRESHOLD_MS_SPEND_SIM_ROUNDTRIP}ms)"
    )
