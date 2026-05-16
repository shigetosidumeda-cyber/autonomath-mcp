from __future__ import annotations

import json

import pytest

from jpintel_mcp.agent_runtime.defaults import CAPSULE_ID, P0_FACADE_TOOLS
from jpintel_mcp.agent_runtime.outcome_catalog import build_outcome_catalog
from jpintel_mcp.mcp.autonomath_tools.jpcite_facade import (
    _execute_input_hash,
    _impl_jpcite_execute_packet,
    _impl_jpcite_get_packet,
    _impl_jpcite_preview_cost,
    _impl_jpcite_route,
)
from jpintel_mcp.mcp.server import mcp


def _scoped_cap_token_for(
    outcome_contract_id: str,
    *,
    max_price_jpy: int = 600,
    token_outcome_contract_id: str | None = None,
    input_hash: str | None = None,
) -> str:
    token = {
        "token_kind": "scoped_cap_token",
        "input_hash": input_hash or _execute_input_hash(outcome_contract_id, max_price_jpy),
        "outcome_contract_id": token_outcome_contract_id or outcome_contract_id,
        "max_price_jpy": max_price_jpy,
        "idempotency_key_required": True,
        "amount_only_token": False,
    }
    return json.dumps(token, separators=(",", ":"))


def _json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_json_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_json_keys(child))
        return keys
    return set()


def test_jpcite_route_returns_free_preview_next_action() -> None:
    result = _impl_jpcite_route(
        goal="会社の公的情報から根拠付きの確認資料を作りたい",
        input_kind="company",
        max_price_jpy=600,
    )

    assert result["billable"] is False
    assert result["charge_status"] == "not_charged"
    assert result["recommended_tool"] == "jpcite_preview_cost"
    assert result["recommended_outcome_contract_id"] == "company_public_baseline"
    assert result["preview"]["estimated_price_jpy"] == 600
    assert result["preview"]["deliverable_slug"] == "company-public-baseline"
    assert result["preview"]["requires_user_csv"] is False
    assert "official_public_registry" in result["preview"]["evidence_dependency_types"]
    assert result["free_inline_packets"]["billable"] is False
    assert "outcome_catalog_summary" in result["free_inline_packets"]["packet_ids"]
    assert "source_receipt_ledger" in result["free_inline_packets"]["packet_ids"]
    assert result["no_hit_caveat"] == "no_hit_not_absence"


def test_jpcite_preview_cost_is_free_and_respects_price_cap() -> None:
    result = _impl_jpcite_preview_cost(
        outcome_contract_id="evidence_answer",
        max_price_jpy=300,
    )

    assert result["status"] == "blocked_price_cap"
    assert result["billable"] is False
    assert result["charge_status"] == "not_charged"
    assert result["estimated_price_jpy"] == 600
    assert result["cap_passed"] is False
    assert result["accepted_artifact_required_for_charge"] is True
    assert result["no_hit_charge_requires_explicit_consent"] is True
    assert result["requires_user_csv"] is False
    assert "official_law_regulation" in result["evidence_dependency_types"]
    assert result["free_inline_packets"]["charge_status"] == "not_charged"


def test_jpcite_preview_cost_treats_zero_cap_as_zero_yen_cap() -> None:
    result = _impl_jpcite_preview_cost(
        outcome_contract_id="company_public_baseline",
        max_price_jpy=0,
    )

    assert result["status"] == "blocked_price_cap"
    assert result["estimated_price_jpy"] == 600
    assert result["max_price_jpy"] == 0
    assert result["cap_passed"] is False
    assert result["billable"] is False


@pytest.mark.parametrize(
    ("input_kind", "expected_outcome_contract_id", "requires_user_csv", "dependency_type"),
    [
        ("invoice", "invoice_registrant_public_check", False, "official_public_registry"),
        ("subsidy", "application_strategy", False, "official_program_guideline"),
        (
            "local_government",
            "local_government_permit_obligation_map",
            False,
            "official_public_notice",
        ),
        ("court", "court_enforcement_citation_pack", False, "official_court_record"),
        ("statistics", "public_statistics_market_context", False, "official_public_statistics"),
        ("monthly_review", "client_monthly_review", False, "official_public_registry"),
        ("csv_counterparty", "csv_overlay_public_check", True, "tenant_private_csv_overlay"),
        (
            "csv_subsidy",
            "cashbook_csv_subsidy_fit_screen",
            True,
            "tenant_private_csv_overlay",
        ),
        (
            "foreign_investor",
            "foreign_investor_japan_public_entry_brief",
            False,
            "official_disclosure",
        ),
        ("healthcare", "healthcare_regulatory_public_check", False, "official_public_notice"),
    ],
)
def test_jpcite_route_uses_outcome_catalog_for_input_kind_aliases(
    input_kind: str,
    expected_outcome_contract_id: str,
    requires_user_csv: bool,
    dependency_type: str,
) -> None:
    result = _impl_jpcite_route(
        goal="公開情報から利用可能な成果物を選びたい",
        input_kind=input_kind,
    )

    known_outcome_ids = {entry.outcome_contract_id for entry in build_outcome_catalog()}
    assert expected_outcome_contract_id in known_outcome_ids
    assert result["recommended_tool"] == "jpcite_preview_cost"
    assert result["recommended_outcome_contract_id"] == expected_outcome_contract_id
    assert result["preview"]["outcome_contract_id"] == expected_outcome_contract_id
    assert result["preview"]["requires_user_csv"] is requires_user_csv
    assert dependency_type in result["preview"]["evidence_dependency_types"]


def test_jpcite_preview_cost_supports_new_catalog_outcomes_without_keyerror() -> None:
    csv_result = _impl_jpcite_preview_cost(
        outcome_contract_id="cashbook_csv_subsidy_fit_screen",
        max_price_jpy=900,
    )
    healthcare_result = _impl_jpcite_preview_cost(
        outcome_contract_id="healthcare_regulatory_public_check",
        max_price_jpy=600,
    )

    assert csv_result["status"] == "preview_ready"
    assert csv_result["estimated_price_jpy"] == 900
    assert csv_result["requires_user_csv"] is True
    assert "tenant_private_csv_overlay" in csv_result["evidence_dependency_types"]

    assert healthcare_result["status"] == "preview_ready"
    assert healthcare_result["requires_user_csv"] is False
    assert "official_law_regulation" in healthcare_result["evidence_dependency_types"]


def test_jpcite_preview_cost_unknown_outcome_fails_closed_with_available_catalog() -> None:
    result = _impl_jpcite_preview_cost("missing_outcome")

    assert result["status"] == "blocked_unknown_outcome_contract"
    assert result["billable"] is False
    assert result["charge_status"] == "not_charged"
    assert "company_public_baseline" in result["available_outcome_contract_ids"]


def test_free_mcp_facade_does_not_inline_heavy_release_catalogs() -> None:
    route = _impl_jpcite_route(
        goal="会社の公的情報から根拠付きの確認資料を作りたい",
        input_kind="company",
    )
    preview = _impl_jpcite_preview_cost("company_public_baseline", max_price_jpy=600)

    response_keys = _json_keys([route, preview])
    blocked_public_facade_keys = (
        "outcome_source_crosswalk",
        "aws_execution_templates",
        "packet_skeletons",
        "private_overlay",
        "claims",
    )
    for key in blocked_public_facade_keys:
        assert key not in response_keys


def test_jpcite_execute_packet_fails_closed_without_and_with_guards() -> None:
    missing = _impl_jpcite_execute_packet("company_public_baseline")

    assert missing["status"] == "blocked_missing_purchase_guard"
    assert missing["billable"] is False
    assert missing["charge_status"] == "not_charged"
    assert set(missing["missing"]) == {"scoped_cap_token", "idempotency_key"}

    blank = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token=" ",
        idempotency_key=" ",
    )

    assert blank["status"] == "blocked_missing_purchase_guard"
    assert set(blank["missing"]) == {"scoped_cap_token", "idempotency_key"}

    guarded = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token=_scoped_cap_token_for("company_public_baseline"),
        idempotency_key="idem_example",
        max_price_jpy=600,
    )

    assert guarded["status"] == "blocked_accepted_artifact_billing_not_wired"
    assert guarded["accepted_artifact_created"] is False
    assert guarded["billable"] is False
    assert guarded["charge_status"] == "not_charged"
    assert guarded["billing_authorization"]["action"] == "authorize_execute"
    assert guarded["billing_authorization"]["charge_allowed"] is False
    gate = guarded["live_billing_readiness_gate"]
    assert gate["target_tool"] == "jpcite_execute_packet"
    assert gate["status"] == "blocked"
    assert gate["gate_passed"] is False
    assert gate["live_billing_wired"] is False


def test_jpcite_execute_packet_rejects_invalid_scoped_cap_token() -> None:
    result = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token="sct_example",
        idempotency_key="idem_example",
        max_price_jpy=600,
    )

    assert result["status"] == "blocked_invalid_scoped_cap_token"
    assert result["error"] == "invalid_scoped_cap_token"
    assert result["accepted_artifact_created"] is False
    assert result["charge_status"] == "not_charged"


def test_jpcite_execute_packet_rejects_scoped_cap_token_mismatches() -> None:
    input_mismatch = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token=_scoped_cap_token_for(
            "company_public_baseline",
            input_hash="sha256:other-request",
        ),
        idempotency_key="idem_example",
        max_price_jpy=600,
    )
    outcome_mismatch = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token=_scoped_cap_token_for(
            "company_public_baseline",
            token_outcome_contract_id="source_receipt_ledger",
        ),
        idempotency_key="idem_example",
        max_price_jpy=600,
    )

    assert input_mismatch["status"] == "blocked_purchase_guard_rejected"
    assert input_mismatch["error"] == "token_input_scope_mismatch"
    assert input_mismatch["billing_authorization"]["action"] == "reject"
    assert input_mismatch["accepted_artifact_created"] is False
    assert outcome_mismatch["status"] == "blocked_purchase_guard_rejected"
    assert outcome_mismatch["error"] == "token_outcome_scope_mismatch"
    assert outcome_mismatch["billing_authorization"]["charge_allowed"] is False


def test_jpcite_execute_packet_rejects_price_above_scoped_cap() -> None:
    result = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token=_scoped_cap_token_for(
            "company_public_baseline",
            max_price_jpy=300,
            input_hash=_execute_input_hash("company_public_baseline", 600),
        ),
        idempotency_key="idem_example",
        max_price_jpy=600,
    )

    assert result["status"] == "blocked_purchase_guard_rejected"
    assert result["error"] == "token_price_cap_exceeded"
    assert result["billing_authorization"]["action"] == "reject"
    assert result["billable"] is False
    assert result["accepted_artifact_created"] is False


def test_jpcite_execute_packet_rejects_unknown_outcome_before_authorization() -> None:
    result = _impl_jpcite_execute_packet(
        "missing_outcome",
        scoped_cap_token=_scoped_cap_token_for("missing_outcome", max_price_jpy=600),
        idempotency_key="idem_example",
        max_price_jpy=600,
    )

    assert result["status"] == "blocked_preview_not_ready"
    assert result["error"] == "blocked_unknown_outcome_contract"
    assert "billing_authorization" not in result
    assert result["accepted_artifact_created"] is False
    assert result["charge_status"] == "not_charged"


def test_jpcite_execute_packet_rejects_zero_requested_cap_before_authorization() -> None:
    result = _impl_jpcite_execute_packet(
        "company_public_baseline",
        scoped_cap_token=_scoped_cap_token_for(
            "company_public_baseline",
            max_price_jpy=600,
            input_hash=_execute_input_hash("company_public_baseline", 0),
        ),
        idempotency_key="idem_example",
        max_price_jpy=0,
    )

    assert result["status"] == "blocked_preview_not_ready"
    assert result["error"] == "blocked_price_cap"
    assert "billing_authorization" not in result
    assert result["accepted_artifact_created"] is False


def test_jpcite_get_packet_can_return_bootstrap_capsule_contract() -> None:
    result = _impl_jpcite_get_packet(CAPSULE_ID)

    assert result["status"] == "capsule_contract_packet"
    assert result["billable"] is False
    assert result["packet"]["preflight_scorecard"]["state"] == "AWS_BLOCKED_PRE_FLIGHT"


def test_jpcite_get_packet_can_return_inline_static_packets() -> None:
    outcome_catalog = _impl_jpcite_get_packet("outcome_catalog_summary")
    source_ledger = _impl_jpcite_get_packet("source_receipt_ledger")
    evidence_answer = _impl_jpcite_get_packet("evidence_answer")

    assert outcome_catalog["status"] == "inline_static_packet"
    assert outcome_catalog["packet"]["packet_kind"] == "outcome_catalog_summary"
    assert outcome_catalog["packet"]["deliverable_count"] == len(build_outcome_catalog())
    assert outcome_catalog["packet"]["receipt_ledger"]["public_claims_release_allowed"] is True

    assert source_ledger["status"] == "inline_static_packet"
    assert source_ledger["billable"] is False
    assert source_ledger["charge_status"] == "not_charged"
    assert source_ledger["accepted_artifact_created"] is False
    assert source_ledger["paid_packet_body_materialized"] is False
    assert source_ledger["packet"]["packet_kind"] == "source_receipt_ledger"
    assert source_ledger["packet"]["receipt_ledger"]["public_claims_release_allowed"] is True

    assert evidence_answer["status"] == "inline_static_packet"
    assert evidence_answer["packet"]["packet_kind"] == "evidence_answer"
    assert evidence_answer["packet"]["request_time_llm_call_performed"] is False
    assert evidence_answer["packet"]["live_source_fetch_performed"] is False
    assert evidence_answer["packet"]["billable"] is False


def test_jpcite_get_packet_can_return_static_skeleton_by_outcome_id_or_slug() -> None:
    by_id = _impl_jpcite_get_packet("company_public_baseline")
    by_slug = _impl_jpcite_get_packet("company-public-baseline")

    for result in (by_id, by_slug):
        assert result["status"] == "static_packet_skeleton"
        assert result["billable"] is False
        assert result["charge_status"] == "not_charged"
        assert result["accepted_artifact_created"] is False
        assert result["paid_packet_body_materialized"] is False
        assert result["outcome_contract_id"] == "company_public_baseline"
        assert result["deliverable_slug"] == "company-public-baseline"
        assert result["packet"]["schema_version"] == "jpcite.packet_skeleton.p0.v1"
        assert result["packet"]["claims"]
        assert result["known_gaps"] == ("paid_artifact_body_not_materialized",)


@pytest.mark.asyncio
async def test_mcp_registry_includes_p0_facade_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert set(P0_FACADE_TOOLS) <= names
    assert "jpcite_cost_preview" not in names
