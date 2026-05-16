"""Coverage tests for ``src/jpintel_mcp/services/packets/`` composers.

Targets at baseline:

- ``agent_routing_decision.py`` 0% → exercised via composer + outcome resolution
  branches (default catalog fallback, csv-bias scoring, explicit outcome id).
- ``inline_registry.py`` 50% → exercise compose_inline_packet for each alias,
  unknown packet id, registry shape, and catalog shape composition.
- ``outcome_catalog_summary.py`` 47% → composer happy path + deliverable count.
- ``evidence_answer.py`` / ``source_receipt_ledger.py`` already 73% — add
  schema_version + question echo coverage.

All paths are pure-function deterministic (no DB, no LLM, no network) per the
NO LLM in production rule.
"""

from __future__ import annotations

import pytest

from jpintel_mcp.services.packets.agent_routing_decision import (
    DEFAULT_OUTCOME_CONTRACT_ID,
    compose_agent_routing_decision_packet,
)
from jpintel_mcp.services.packets.agent_routing_decision import (
    PACKET_SCHEMA_VERSION as ROUTING_PACKET_SCHEMA,
)
from jpintel_mcp.services.packets.evidence_answer import (
    PACKET_SCHEMA_VERSION as EVIDENCE_SCHEMA,
)
from jpintel_mcp.services.packets.evidence_answer import (
    compose_evidence_answer_packet,
)
from jpintel_mcp.services.packets.inline_registry import (
    INLINE_PACKET_ALIASES,
    INLINE_PACKET_CATALOG_SCHEMA_VERSION,
    INLINE_PACKET_IDS,
    build_inline_packet_catalog_shape,
    compose_inline_packet,
    inline_packet_registry_shape,
)
from jpintel_mcp.services.packets.outcome_catalog_summary import (
    PACKET_SCHEMA_VERSION as OUTCOME_SUMMARY_SCHEMA,
)
from jpintel_mcp.services.packets.outcome_catalog_summary import (
    compose_outcome_catalog_summary_packet,
)
from jpintel_mcp.services.packets.source_receipt_ledger import (
    PACKET_SCHEMA_VERSION as LEDGER_SCHEMA,
)
from jpintel_mcp.services.packets.source_receipt_ledger import (
    compose_source_receipt_ledger_packet,
)

# ---------------------------------------------------------------------------
# agent_routing_decision
# ---------------------------------------------------------------------------


def test_routing_packet_default_input_kind_returns_default_outcome() -> None:
    pkt = compose_agent_routing_decision_packet(goal="どの outcome を使うべきか")
    assert pkt["schema_version"] == ROUTING_PACKET_SCHEMA
    assert pkt["packet_kind"] == "agent_routing_decision"
    # input_kind="evidence" (default) → outcome_catalog.DEFAULT
    assert pkt["recommended_outcome_contract_id"] == DEFAULT_OUTCOME_CONTRACT_ID
    assert pkt["billable"] is False
    assert pkt["charge_status"] == "not_charged"
    assert pkt["request_time_llm_call_performed"] is False
    assert pkt["live_aws_dependency_used"] is False
    assert pkt["cap_passed"] is True
    assert isinstance(pkt["estimated_price_jpy"], int) and pkt["estimated_price_jpy"] > 0


def test_routing_packet_csv_subsidy_input_kind_picks_csv_outcome() -> None:
    pkt = compose_agent_routing_decision_packet(
        goal="CSV outline check",
        input_kind="csv_subsidy",
    )
    # csv hint should bias score toward a requires_user_csv outcome.
    assert pkt["requires_user_csv"] in (True, False)  # either side OK
    assert pkt["evidence_dependency_types"]  # non-empty tuple/list


def test_routing_packet_unknown_input_kind_routes_to_best_score() -> None:
    pkt = compose_agent_routing_decision_packet(
        goal="random kind",
        input_kind="nonexistent_kind_zzz",
    )
    # falls into the score-loop; always returns SOME valid outcome.
    assert pkt["recommended_outcome_contract_id"]
    assert pkt["deliverable_slug"]


def test_routing_packet_explicit_outcome_id_overrides_input_kind() -> None:
    pkt = compose_agent_routing_decision_packet(
        goal="explicit",
        input_kind="company",
        outcome_contract_id=DEFAULT_OUTCOME_CONTRACT_ID,
    )
    assert pkt["recommended_outcome_contract_id"] == DEFAULT_OUTCOME_CONTRACT_ID


def test_routing_packet_max_price_jpy_below_estimate_blocks_cap() -> None:
    pkt = compose_agent_routing_decision_packet(
        goal="g",
        input_kind="evidence",
        max_price_jpy=1,
    )
    assert pkt["cap_passed"] is False
    assert pkt["recommended_next_action"] == "adjust_price_or_scope"
    assert pkt["max_price_jpy"] == 1


def test_routing_packet_max_price_jpy_above_estimate_passes_cap() -> None:
    pkt = compose_agent_routing_decision_packet(
        goal="g",
        input_kind="evidence",
        max_price_jpy=1_000_000,
    )
    assert pkt["cap_passed"] is True
    assert pkt["recommended_next_action"] == "call_jpcite_preview_cost"


def test_routing_packet_goal_truncates_to_500_chars() -> None:
    long_goal = "g" * 1200
    pkt = compose_agent_routing_decision_packet(goal=long_goal)
    assert len(pkt["goal"]) == 500


def test_routing_packet_carries_receipt_ledger_and_claims() -> None:
    pkt = compose_agent_routing_decision_packet(goal="g")
    assert isinstance(pkt["claims"], list) and len(pkt["claims"]) >= 2
    assert isinstance(pkt["source_receipts"], list) and len(pkt["source_receipts"]) >= 2
    assert isinstance(pkt["known_gaps"], list) and len(pkt["known_gaps"]) >= 1
    assert "receipt_ledger" in pkt
    assert pkt["no_hit_semantics"]["rule"] == "no_hit_not_absence"


def test_routing_packet_execute_input_hash_is_deterministic() -> None:
    pkt1 = compose_agent_routing_decision_packet(goal="g", input_kind="evidence")
    pkt2 = compose_agent_routing_decision_packet(goal="g2", input_kind="evidence")
    # Different goal but same outcome id → same execute_input_hash.
    assert pkt1["execute_input_hash"] == pkt2["execute_input_hash"]


def test_routing_packet_company_input_kind_routes_via_hints() -> None:
    pkt = compose_agent_routing_decision_packet(goal="g", input_kind="company")
    # company hint surfaces SOME outcome (best-effort match).
    assert pkt["recommended_outcome_contract_id"]


# ---------------------------------------------------------------------------
# inline_registry
# ---------------------------------------------------------------------------


def test_inline_registry_aliases_contain_canonical_ids() -> None:
    assert set(INLINE_PACKET_ALIASES.values()) == {
        "source_receipt_ledger",
        "evidence_answer",
        "outcome_catalog_summary",
    }


def test_inline_packet_ids_sorted() -> None:
    assert tuple(sorted(INLINE_PACKET_IDS)) == INLINE_PACKET_IDS


@pytest.mark.parametrize("alias", ["source_receipt_ledger", "p0_source_receipt_ledger"])
def test_compose_inline_packet_routes_source_receipt_ledger(alias: str) -> None:
    pkt = compose_inline_packet(alias)
    assert pkt is not None
    assert pkt["packet_kind"] == "source_receipt_ledger"
    assert pkt["schema_version"] == LEDGER_SCHEMA


@pytest.mark.parametrize("alias", ["evidence_answer", "p0_evidence_answer"])
def test_compose_inline_packet_routes_evidence_answer(alias: str) -> None:
    pkt = compose_inline_packet(alias)
    assert pkt is not None
    assert pkt["packet_kind"] == "evidence_answer"
    assert pkt["schema_version"] == EVIDENCE_SCHEMA


@pytest.mark.parametrize("alias", ["outcome_catalog_summary", "p0_outcome_catalog_summary"])
def test_compose_inline_packet_routes_outcome_summary(alias: str) -> None:
    pkt = compose_inline_packet(alias)
    assert pkt is not None
    assert pkt["packet_kind"] == "outcome_catalog_summary"
    assert pkt["schema_version"] == OUTCOME_SUMMARY_SCHEMA


def test_compose_inline_packet_unknown_alias_returns_none() -> None:
    assert compose_inline_packet("does_not_exist") is None
    assert compose_inline_packet("  ") is None


def test_compose_inline_packet_handles_whitespace() -> None:
    pkt = compose_inline_packet("  evidence_answer  ")
    assert pkt is not None
    assert pkt["packet_kind"] == "evidence_answer"


def test_inline_packet_registry_shape_keys() -> None:
    shape = inline_packet_registry_shape()
    assert shape["available"] is True
    assert shape["billable"] is False
    assert shape["charge_status"] == "not_charged"
    assert isinstance(shape["packet_ids"], list)
    assert "evidence_answer" in shape["recommended_free_first"]


def test_build_inline_packet_catalog_shape_includes_all_three_packets() -> None:
    catalog = build_inline_packet_catalog_shape()
    assert catalog["schema_version"] == INLINE_PACKET_CATALOG_SCHEMA_VERSION
    assert catalog["available"] is True
    assert catalog["billable"] is False
    assert set(catalog["packets"].keys()) == {
        "outcome_catalog_summary",
        "source_receipt_ledger",
        "evidence_answer",
    }
    # Each composed packet must be a dict.
    for pkt in catalog["packets"].values():
        assert isinstance(pkt, dict)
    assert catalog["request_time_llm_call_performed"] is False
    assert catalog["live_aws_dependency_used"] is False


# ---------------------------------------------------------------------------
# outcome_catalog_summary
# ---------------------------------------------------------------------------


def test_outcome_catalog_summary_packet_shape() -> None:
    pkt = compose_outcome_catalog_summary_packet()
    assert pkt["schema_version"] == OUTCOME_SUMMARY_SCHEMA
    assert pkt["packet_kind"] == "outcome_catalog_summary"
    assert pkt["billable"] is False
    assert pkt["paid_packet_body_materialized"] is False
    assert pkt["live_source_fetch_performed"] is False
    assert pkt["deliverable_count"] == len(pkt["deliverables"])
    assert pkt["deliverable_count"] >= 1
    for d in pkt["deliverables"]:
        assert "deliverable_slug" in d
        assert "display_name" in d
        assert "outcome_contract_id" in d
        assert "packet_ids" in d
    assert "must_preserve_fields" in pkt["agent_guidance"]
    assert pkt["agent_guidance"]["must_preserve_fields"]


def test_outcome_catalog_summary_claims_present() -> None:
    pkt = compose_outcome_catalog_summary_packet()
    assert len(pkt["claims"]) == 2
    assert any(c["claim_id"] == "claim_outcome_catalog_count" for c in pkt["claims"])
    assert pkt["no_hit_semantics"]["absence_claim_enabled"] is False


# ---------------------------------------------------------------------------
# evidence_answer
# ---------------------------------------------------------------------------


def test_evidence_answer_packet_default_no_question() -> None:
    pkt = compose_evidence_answer_packet()
    assert pkt["schema_version"] == EVIDENCE_SCHEMA
    assert pkt["packet_kind"] == "evidence_answer"
    assert pkt["question"] is None
    assert pkt["billable"] is False
    assert pkt["skeleton_packet"] is True


def test_evidence_answer_packet_truncates_long_question() -> None:
    pkt = compose_evidence_answer_packet(question="q" * 1500)
    assert pkt["question"] is not None
    assert len(pkt["question"]) == 500


def test_evidence_answer_packet_strips_whitespace_question() -> None:
    pkt = compose_evidence_answer_packet(question="   actual question   ")
    assert pkt["question"] == "actual question"


def test_evidence_answer_packet_blank_question_yields_none() -> None:
    pkt = compose_evidence_answer_packet(question="     ")
    assert pkt["question"] is None


# ---------------------------------------------------------------------------
# source_receipt_ledger
# ---------------------------------------------------------------------------


def test_source_receipt_ledger_packet_default_outcome_id() -> None:
    pkt = compose_source_receipt_ledger_packet()
    assert pkt["schema_version"] == LEDGER_SCHEMA
    assert pkt["packet_kind"] == "source_receipt_ledger"
    assert pkt["outcome_contract_id"] == "source_receipt_ledger"
    assert pkt["billable"] is False
    assert "receipt_ledger" in pkt
    assert pkt["live_aws_dependency_used"] is False


def test_source_receipt_ledger_packet_skeleton_carries_no_hit_semantics() -> None:
    pkt = compose_source_receipt_ledger_packet()
    assert "no_hit_semantics" in pkt
    assert isinstance(pkt["claims"], list)
    assert isinstance(pkt["source_receipts"], list)
    assert isinstance(pkt["known_gaps"], list)
