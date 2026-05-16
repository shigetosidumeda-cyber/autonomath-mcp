from __future__ import annotations

import json
from pathlib import Path

import pytest

from jpintel_mcp.agent_runtime.algorithm_blueprints import (
    ALGORITHM_BLUEPRINT_IDS,
    CATALOG_VERSION,
    FORBIDDEN_ADVICE_ASSERTIONS,
    NO_HIT_SEMANTICS,
    NUMERICAL_METHOD_ALGORITHM_IDS,
    AlgorithmBlueprint,
    build_algorithm_blueprint_catalog_shape,
    build_algorithm_blueprints,
    get_algorithm_blueprint,
)


def test_algorithm_blueprint_catalog_contains_required_algorithms_in_order() -> None:
    blueprints = build_algorithm_blueprints()

    assert tuple(blueprint.algorithm_id for blueprint in blueprints) == ALGORITHM_BLUEPRINT_IDS
    assert set(ALGORITHM_BLUEPRINT_IDS) == {
        "evidence_join",
        "time_window_coverage_scoring",
        "source_freshness_scoring",
        "csv_to_public_counterparty_matching",
        "subsidy_regulation_eligibility_triage_without_verdict",
        "deadline_risk_ranking",
        "no_hit_semantics",
    }


@pytest.mark.parametrize("blueprint", build_algorithm_blueprints())
def test_every_algorithm_declares_contract_surface(blueprint: AlgorithmBlueprint) -> None:
    assert blueprint.algorithm_id
    assert blueprint.display_name
    assert blueprint.purpose
    assert blueprint.inputs
    assert blueprint.outputs
    assert blueprint.deterministic_steps

    assert all(input_item.name and input_item.description for input_item in blueprint.inputs)
    assert all(output.name and output.description for output in blueprint.outputs)

    assert blueprint.proof_handling.support_states
    assert blueprint.proof_handling.required_reference_fields
    assert blueprint.proof_handling.rules
    assert blueprint.proof_handling.private_csv_can_support_public_claims is False

    assert blueprint.gap_handling.gap_outputs
    assert blueprint.gap_handling.rules
    assert blueprint.gap_handling.no_hit_semantics == NO_HIT_SEMANTICS
    assert blueprint.gap_handling.absence_claim_enabled is False

    assert blueprint.llm_allowed is False
    assert blueprint.network_allowed is False


@pytest.mark.parametrize("blueprint", build_algorithm_blueprints())
def test_numerical_methods_are_declared_where_applicable(blueprint: AlgorithmBlueprint) -> None:
    numerical_method = blueprint.numerical_method

    assert numerical_method.method_id
    assert numerical_method.rounding

    if blueprint.algorithm_id in NUMERICAL_METHOD_ALGORITHM_IDS:
        assert numerical_method.applies is True
        assert numerical_method.formula != "not_applicable"
        assert numerical_method.score_range is not None
        lower, upper = numerical_method.score_range
        assert lower < upper
        assert numerical_method.tie_breakers
    else:
        assert numerical_method.applies is False
        assert numerical_method.formula == "not_applicable"
        assert numerical_method.score_range is None


@pytest.mark.parametrize("blueprint", build_algorithm_blueprints())
def test_blueprints_do_not_assert_legal_or_accounting_advice(
    blueprint: AlgorithmBlueprint,
) -> None:
    boundary = blueprint.advice_boundary

    assert boundary.asserts_legal_or_accounting_advice is False
    assert set(FORBIDDEN_ADVICE_ASSERTIONS) <= set(boundary.forbidden_assertions)
    assert "legal_advice" in boundary.forbidden_assertions
    assert "accounting_advice" in boundary.forbidden_assertions
    assert "application_eligibility_verdict" in boundary.forbidden_assertions
    assert all("verdict" not in output.name for output in blueprint.outputs)
    assert all("verdict" not in state for state in boundary.allowed_conclusion_states)


def test_evidence_join_is_exact_receipt_backed_and_gap_first() -> None:
    blueprint = get_algorithm_blueprint("evidence_join")

    assert blueprint.numerical_method.applies is False
    assert blueprint.numerical_method.method_id == "exact_key_join_no_score"
    assert "source_receipts" in {input_item.name for input_item in blueprint.inputs}
    assert "joined_claim_refs" in {output.name for output in blueprint.outputs}
    assert "candidate_claims_without_required_receipts_are_not_public_claims" in (
        blueprint.proof_handling.rules
    )
    assert "ambiguous_subject_join_emits_gap_instead_of_best_guess" in blueprint.gap_handling.rules


def test_scoring_and_ranking_blueprints_expose_expected_formulas() -> None:
    coverage = get_algorithm_blueprint("time_window_coverage_scoring")
    freshness = get_algorithm_blueprint("source_freshness_scoring")
    deadline = get_algorithm_blueprint("deadline_risk_ranking")

    assert coverage.numerical_method.method_id == "weighted_interval_coverage_ratio_v1"
    assert coverage.numerical_method.score_range == (0.0, 1.0)
    assert "covered_days_i" in coverage.numerical_method.formula

    assert freshness.numerical_method.method_id == "linear_age_decay_weighted_mean_v1"
    assert freshness.numerical_method.score_range == (0.0, 1.0)
    assert "age_days" in freshness.numerical_method.formula

    assert deadline.numerical_method.method_id == "deadline_urgency_buffer_freshness_score_v1"
    assert deadline.numerical_method.score_range == (0.0, 100.0)
    assert "risk_score" in deadline.numerical_method.formula


def test_csv_to_public_counterparty_matching_keeps_csv_facts_private() -> None:
    blueprint = get_algorithm_blueprint("csv_to_public_counterparty_matching")

    assert any(
        input_item.source_scope == "tenant_private_csv_fact" for input_item in blueprint.inputs
    )
    assert "private_counterparty_fingerprints" in {
        input_item.name for input_item in blueprint.inputs
    }
    assert "public_record_checks" in {output.name for output in blueprint.outputs}
    assert "private_csv_facts_may_rank_or_filter_but_never_support_public_claim_text" in (
        blueprint.proof_handling.rules
    )
    assert "match_candidates_must_include_private_fingerprint_not_raw_value" in (
        blueprint.proof_handling.rules
    )
    assert blueprint.proof_handling.private_csv_can_support_public_claims is False
    assert blueprint.numerical_method.method_id == "deterministic_counterparty_match_score_v1"

    public_outputs = {output.name for output in blueprint.outputs if output.visibility == "public"}
    assert public_outputs == {"public_record_checks"}


def test_subsidy_regulation_triage_is_candidate_only_without_verdict() -> None:
    blueprint = get_algorithm_blueprint("subsidy_regulation_eligibility_triage_without_verdict")

    assert "candidate_for_review" in {output.name for output in blueprint.outputs}
    assert "questions_for_professional" in {output.name for output in blueprint.outputs}
    assert "candidate_for_review" in blueprint.advice_boundary.allowed_conclusion_states
    assert blueprint.advice_boundary.professional_review_required is True
    assert "candidate_for_review_must_include_do_not_claim_verdict_boundary" in (
        blueprint.proof_handling.rules
    )
    assert "missing_applicant_fact_emits_question_not_negative_verdict" in (
        blueprint.gap_handling.rules
    )
    assert blueprint.numerical_method.method_id == "known_signal_triage_ratio_v1"


def test_no_hit_semantics_never_becomes_absence_claim() -> None:
    blueprint = get_algorithm_blueprint("no_hit_semantics")
    serialized = json.dumps(blueprint.to_dict(), sort_keys=True)

    assert blueprint.gap_handling.no_hit_semantics == NO_HIT_SEMANTICS
    assert blueprint.gap_handling.absence_claim_enabled is False
    assert blueprint.numerical_method.applies is False
    assert "no_hit_lease" in {output.name for output in blueprint.outputs}
    assert "unchecked_scope_gaps" in {output.name for output in blueprint.outputs}
    assert "no_hit_wording_must_say_observed_search_result_only" in (blueprint.proof_handling.rules)
    assert "no_hit_not_absence" in blueprint.gap_handling.rules
    assert '"absence_claim_enabled": false' in serialized


def test_catalog_shape_is_deterministic_and_local_only() -> None:
    first = build_algorithm_blueprint_catalog_shape()
    second = build_algorithm_blueprint_catalog_shape()

    assert first == second
    assert first["schema_version"] == CATALOG_VERSION
    assert first["llm_allowed"] is False
    assert first["network_allowed"] is False
    assert first["no_hit_semantics"] == NO_HIT_SEMANTICS
    assert first["absence_claim_enabled"] is False
    assert first["algorithm_ids"] == list(ALGORITHM_BLUEPRINT_IDS)


def test_unknown_algorithm_blueprint_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown algorithm blueprint"):
        get_algorithm_blueprint("not_a_blueprint")


def test_algorithm_blueprints_have_no_llm_network_or_io_dependencies() -> None:
    module_source = Path("src/jpintel_mcp/agent_runtime/algorithm_blueprints.py").read_text()
    forbidden_tokens = (
        "openai",
        "anthropic",
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "sqlite3",
        "import csv",
        "open(",
    )

    assert not any(token in module_source.lower() for token in forbidden_tokens)
