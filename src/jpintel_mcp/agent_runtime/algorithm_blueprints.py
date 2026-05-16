"""Deterministic algorithm blueprints for evidence-grounded artifacts.

The catalog in this module is static metadata. It describes local-only
algorithms that compile artifacts from first-party evidence receipts and, when
present, minimized accounting CSV-derived facts. It does not fetch sources, run
LLM inference, or turn private CSV facts into public-source proof.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CATALOG_VERSION = "jpcite.algorithm_blueprints.p0.v1"
NO_HIT_SEMANTICS: Literal["no_hit_not_absence"] = "no_hit_not_absence"

AlgorithmSourceScope = Literal[
    "first_party_evidence",
    "tenant_private_csv_fact",
    "derived_public_fact",
    "configuration",
    "clock_parameter",
]
OutputVisibility = Literal["public", "tenant_private", "internal"]
PrivacyHandling = Literal["public", "tenant_private_minimized", "none"]

ALGORITHM_BLUEPRINT_IDS = (
    "evidence_join",
    "time_window_coverage_scoring",
    "source_freshness_scoring",
    "csv_to_public_counterparty_matching",
    "subsidy_regulation_eligibility_triage_without_verdict",
    "deadline_risk_ranking",
    "no_hit_semantics",
)

NUMERICAL_METHOD_ALGORITHM_IDS = frozenset(
    {
        "time_window_coverage_scoring",
        "source_freshness_scoring",
        "csv_to_public_counterparty_matching",
        "subsidy_regulation_eligibility_triage_without_verdict",
        "deadline_risk_ranking",
    }
)

FORBIDDEN_ADVICE_ASSERTIONS = (
    "legal_advice",
    "accounting_advice",
    "tax_advice",
    "application_eligibility_verdict",
    "regulatory_compliance_verdict",
    "grant_award_prediction",
    "audit_opinion",
)


@dataclass(frozen=True)
class BlueprintInput:
    """Declared input to a deterministic algorithm blueprint."""

    name: str
    description: str
    source_scope: AlgorithmSourceScope
    privacy_handling: PrivacyHandling
    required: bool = True

    def __post_init__(self) -> None:
        if not self.name or not self.description:
            raise ValueError("blueprint inputs must declare name and description")


@dataclass(frozen=True)
class BlueprintOutput:
    """Declared output from a deterministic algorithm blueprint."""

    name: str
    description: str
    visibility: OutputVisibility
    proof_required: bool

    def __post_init__(self) -> None:
        if not self.name or not self.description:
            raise ValueError("blueprint outputs must declare name and description")


@dataclass(frozen=True)
class ProofHandling:
    """Rules for evidence references and candidate/gap support states."""

    support_states: tuple[str, ...]
    required_reference_fields: tuple[str, ...]
    rules: tuple[str, ...]
    private_csv_can_support_public_claims: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.support_states or not self.required_reference_fields or not self.rules:
            raise ValueError("proof handling must declare states, references, and rules")


@dataclass(frozen=True)
class GapHandling:
    """Rules for known gaps, stale evidence, and no-hit caveats."""

    gap_outputs: tuple[str, ...]
    rules: tuple[str, ...]
    no_hit_semantics: Literal["no_hit_not_absence"] = NO_HIT_SEMANTICS
    absence_claim_enabled: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.gap_outputs or not self.rules:
            raise ValueError("gap handling must declare gap outputs and rules")


@dataclass(frozen=True)
class NumericalMethod:
    """Deterministic formula metadata for scoring, matching, and ranking."""

    method_id: str
    applies: bool
    formula: str
    score_range: tuple[float, float] | None
    rounding: str
    tie_breakers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.method_id or not self.rounding:
            raise ValueError("numerical method must declare method_id and rounding")
        if self.applies:
            if self.formula == "not_applicable" or self.score_range is None:
                raise ValueError("applicable numerical methods need formula and range")
            lower, upper = self.score_range
            if lower >= upper:
                raise ValueError("score range lower bound must be below upper bound")
        elif self.formula != "not_applicable" or self.score_range is not None:
            raise ValueError("non-applicable numerical methods must be explicit")


@dataclass(frozen=True)
class AdviceBoundary:
    """Boundary that prevents algorithm metadata from becoming professional advice."""

    allowed_conclusion_states: tuple[str, ...]
    professional_review_required: bool
    forbidden_assertions: tuple[str, ...] = FORBIDDEN_ADVICE_ASSERTIONS
    asserts_legal_or_accounting_advice: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.allowed_conclusion_states or not self.forbidden_assertions:
            raise ValueError("advice boundary must declare allowed and forbidden states")


@dataclass(frozen=True)
class AlgorithmBlueprint:
    """Complete deterministic algorithm contract."""

    algorithm_id: str
    display_name: str
    purpose: str
    inputs: tuple[BlueprintInput, ...]
    outputs: tuple[BlueprintOutput, ...]
    deterministic_steps: tuple[str, ...]
    proof_handling: ProofHandling
    gap_handling: GapHandling
    numerical_method: NumericalMethod
    advice_boundary: AdviceBoundary
    llm_allowed: Literal[False] = False
    network_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if not self.algorithm_id or not self.display_name or not self.purpose:
            raise ValueError("algorithm blueprint must declare identity and purpose")
        if not self.inputs or not self.outputs or not self.deterministic_steps:
            raise ValueError("algorithm blueprint must declare inputs, outputs, and steps")
        if (
            self.algorithm_id in NUMERICAL_METHOD_ALGORITHM_IDS
            and not self.numerical_method.applies
        ):
            raise ValueError(f"{self.algorithm_id} must declare an applicable numerical method")
        if (
            self.algorithm_id not in NUMERICAL_METHOD_ALGORITHM_IDS
            and self.numerical_method.applies
        ):
            raise ValueError(f"{self.algorithm_id} must not declare an applicable numerical method")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_algorithm_blueprints() -> tuple[AlgorithmBlueprint, ...]:
    """Return algorithm blueprints in stable dependency order."""

    return (
        _evidence_join(),
        _time_window_coverage_scoring(),
        _source_freshness_scoring(),
        _csv_to_public_counterparty_matching(),
        _subsidy_regulation_triage(),
        _deadline_risk_ranking(),
        _no_hit_semantics(),
    )


def build_algorithm_blueprint_catalog_shape() -> dict[str, object]:
    """Return a JSON-ready deterministic catalog shape."""

    blueprints = build_algorithm_blueprints()
    return {
        "schema_version": CATALOG_VERSION,
        "llm_allowed": False,
        "network_allowed": False,
        "no_hit_semantics": NO_HIT_SEMANTICS,
        "absence_claim_enabled": False,
        "algorithm_ids": list(ALGORITHM_BLUEPRINT_IDS),
        "blueprints": [blueprint.to_dict() for blueprint in blueprints],
    }


def get_algorithm_blueprint(algorithm_id: str) -> AlgorithmBlueprint:
    """Return one deterministic algorithm blueprint by ID."""

    for blueprint in build_algorithm_blueprints():
        if blueprint.algorithm_id == algorithm_id:
            return blueprint
    raise ValueError(f"unknown algorithm blueprint: {algorithm_id}")


def _common_advice_boundary(
    *allowed_conclusion_states: str,
    professional_review_required: bool = True,
) -> AdviceBoundary:
    return AdviceBoundary(
        allowed_conclusion_states=allowed_conclusion_states,
        professional_review_required=professional_review_required,
    )


def _proof_handling(*rules: str) -> ProofHandling:
    return ProofHandling(
        support_states=("supported", "candidate", "gap", "blocked"),
        required_reference_fields=("receipt_ids", "claim_ref_ids", "gap_ids"),
        rules=rules,
    )


def _gap_handling(*rules: str) -> GapHandling:
    return GapHandling(
        gap_outputs=("known_gaps", "blocked_items", "no_hit_lease"),
        rules=rules,
    )


def _no_numeric(method_id: str) -> NumericalMethod:
    return NumericalMethod(
        method_id=method_id,
        applies=False,
        formula="not_applicable",
        score_range=None,
        rounding="not_applicable",
        tie_breakers=(),
    )


def _evidence_join() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="evidence_join",
        display_name="Evidence Join",
        purpose=(
            "Join artifact claim candidates to first-party evidence fragments using explicit "
            "receipt and subject keys before any public claim can be emitted."
        ),
        inputs=(
            BlueprintInput(
                "source_receipts",
                "First-party source receipts with receipt_id, source_family_id, observed_at, and support_state.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "evidence_fragments",
                "Extracted text or metadata fragments already tied to source_receipt IDs and stable section keys.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "claim_candidates",
                "Structured candidate claims generated from deterministic packet templates, not free-form inference.",
                "derived_public_fact",
                "public",
            ),
        ),
        outputs=(
            BlueprintOutput(
                "joined_claim_refs",
                "Claim references that carry the exact receipt IDs and fragment IDs used as proof.",
                "public",
                True,
            ),
            BlueprintOutput(
                "rejected_claim_candidates",
                "Candidates that could not be joined to proof and therefore cannot become public claims.",
                "internal",
                False,
            ),
            BlueprintOutput(
                "coverage_gaps",
                "Known gaps for missing receipts, missing sections, ambiguous subjects, or blocked sources.",
                "public",
                True,
            ),
        ),
        deterministic_steps=(
            "Sort receipts by source_family_id, canonical_subject_id, observed_at, and receipt_id.",
            "Join by explicit receipt_id and fragment_id first; fall back only to exact canonical subject and section keys.",
            "Emit supported claim refs only when every required claim field has a receipt-backed fragment.",
            "Emit candidate or gap states for partial joins; never synthesize missing claim text.",
        ),
        proof_handling=_proof_handling(
            "public_claims_must_reference_source_receipt_ids",
            "joined_claim_refs_must_include_fragment_ids",
            "candidate_claims_without_required_receipts_are_not_public_claims",
        ),
        gap_handling=_gap_handling(
            "unjoined_claim_candidates_emit_known_gap",
            "ambiguous_subject_join_emits_gap_instead_of_best_guess",
            "blocked_source_receipts_emit_blocked_item",
        ),
        numerical_method=_no_numeric("exact_key_join_no_score"),
        advice_boundary=_common_advice_boundary(
            "supported_claim_ref",
            "candidate_claim_ref",
            "known_gap",
            professional_review_required=False,
        ),
    )


def _time_window_coverage_scoring() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="time_window_coverage_scoring",
        display_name="Time-Window Coverage Scoring",
        purpose=(
            "Score how much of a requested period is covered by first-party evidence without "
            "treating uncovered time as proof that no event occurred."
        ),
        inputs=(
            BlueprintInput(
                "required_windows",
                "Requested half-open date windows with source_family_id and required coverage weight.",
                "configuration",
                "none",
            ),
            BlueprintInput(
                "observed_windows",
                "Receipt-backed half-open date windows with valid_from, valid_to, and receipt IDs.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "as_of_date",
                "Deterministic evaluation date supplied by the caller or release capsule.",
                "clock_parameter",
                "none",
            ),
        ),
        outputs=(
            BlueprintOutput(
                "coverage_score",
                "Weighted coverage ratio from 0.0 to 1.0 with formula ID and input window IDs.",
                "public",
                True,
            ),
            BlueprintOutput(
                "covered_segments",
                "Receipt-backed covered date segments after deterministic interval union.",
                "public",
                True,
            ),
            BlueprintOutput(
                "missing_or_stale_segments",
                "Known gaps for uncovered, stale, or blocked date segments.",
                "public",
                True,
            ),
        ),
        deterministic_steps=(
            "Normalize dates to local calendar days and half-open intervals [start, end).",
            "Union overlapping observed windows per source family after sorting by start date, end date, and receipt_id.",
            "Intersect observed windows with required windows and sum covered weighted days.",
            "Emit missing or stale intervals as known gaps; no uncovered interval becomes an absence claim.",
        ),
        proof_handling=_proof_handling(
            "each_covered_segment_must_reference_receipt_ids",
            "coverage_score_must_include_window_ids_and_formula_id",
            "score_inputs_are_date_ranges_not_free_text",
        ),
        gap_handling=_gap_handling(
            "uncovered_required_windows_emit_known_gap",
            "stale_observed_windows_emit_stale_gap",
            "coverage_below_threshold_blocks_final_artifact_or_marks_gap",
        ),
        numerical_method=NumericalMethod(
            method_id="weighted_interval_coverage_ratio_v1",
            applies=True,
            formula="score = sum(covered_days_i * weight_i) / sum(required_days_i * weight_i)",
            score_range=(0.0, 1.0),
            rounding="round_half_up_to_4_decimal_places_after_clamp_0_1",
            tie_breakers=("earlier_required_window_start", "source_family_id", "receipt_id"),
        ),
        advice_boundary=_common_advice_boundary(
            "coverage_score",
            "covered_segment",
            "known_gap",
            professional_review_required=False,
        ),
    )


def _source_freshness_scoring() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="source_freshness_scoring",
        display_name="Source Freshness Scoring",
        purpose=(
            "Score receipt freshness against configured source-family service windows using only "
            "supplied observed_at metadata."
        ),
        inputs=(
            BlueprintInput(
                "source_receipts",
                "First-party receipts with observed_at timestamps and source family IDs.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "freshness_sla_days",
                "Configured maximum age per source family before a receipt is stale.",
                "configuration",
                "none",
            ),
            BlueprintInput(
                "as_of_date",
                "Deterministic evaluation timestamp supplied by the caller or release capsule.",
                "clock_parameter",
                "none",
            ),
        ),
        outputs=(
            BlueprintOutput(
                "freshness_score",
                "Weighted score from 0.0 to 1.0 with age days, SLA days, and receipt IDs.",
                "public",
                True,
            ),
            BlueprintOutput(
                "fresh_receipts",
                "Receipts inside the configured freshness window.",
                "public",
                True,
            ),
            BlueprintOutput(
                "stale_receipts",
                "Receipts outside the configured freshness window, emitted as gaps before final use.",
                "public",
                True,
            ),
        ),
        deterministic_steps=(
            "Compute non-negative age_days from as_of_date minus observed_at date.",
            "Look up source_family freshness_sla_days; unknown SLA emits a freshness gap.",
            "Score each receipt by linear decay and weighted mean by source family.",
            "Sort stale receipts by oldest observed_at, source_family_id, and receipt_id.",
        ),
        proof_handling=_proof_handling(
            "freshness_scores_must_reference_receipt_ids",
            "stale_receipt_findings_must_keep_original_observed_at",
            "unknown_observed_at_is_gap_not_estimate",
        ),
        gap_handling=_gap_handling(
            "unknown_sla_emits_known_gap",
            "missing_observed_at_emits_known_gap",
            "stale_receipt_blocks_fresh_claim_wording",
        ),
        numerical_method=NumericalMethod(
            method_id="linear_age_decay_weighted_mean_v1",
            applies=True,
            formula="receipt_score = max(0, 1 - age_days / freshness_sla_days); score = weighted_mean(receipt_score)",
            score_range=(0.0, 1.0),
            rounding="round_half_up_to_4_decimal_places_after_clamp_0_1",
            tie_breakers=("older_observed_at_first", "source_family_id", "receipt_id"),
        ),
        advice_boundary=_common_advice_boundary(
            "freshness_score",
            "fresh_receipt",
            "stale_gap",
            professional_review_required=False,
        ),
    )


def _csv_to_public_counterparty_matching() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="csv_to_public_counterparty_matching",
        display_name="CSV-To-Public Counterparty Matching",
        purpose=(
            "Match minimized tenant-private accounting CSV-derived counterparty facts to supplied "
            "public records as candidate checks, while preventing private facts from becoming public proof."
        ),
        inputs=(
            BlueprintInput(
                "private_counterparty_fingerprints",
                "Minimized tenant-private facts such as hashed counterparty keys, amount buckets, and provider family.",
                "tenant_private_csv_fact",
                "tenant_private_minimized",
            ),
            BlueprintInput(
                "public_counterparty_records",
                "Receipt-backed public records such as invoice registry or company profile rows already supplied.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "allowed_alias_table",
                "Deterministic alias keys from first-party or tenant-approved configuration.",
                "configuration",
                "tenant_private_minimized",
                required=False,
            ),
        ),
        outputs=(
            BlueprintOutput(
                "counterparty_match_candidates",
                "Candidate public-record matches with score, reason code, receipt IDs, and private value fingerprints only.",
                "tenant_private",
                True,
            ),
            BlueprintOutput(
                "unmatched_private_facts",
                "Private fact fingerprints that did not reach candidate threshold.",
                "tenant_private",
                False,
            ),
            BlueprintOutput(
                "public_record_checks",
                "Public source checks that can be cited independently of private CSV content.",
                "public",
                True,
            ),
        ),
        deterministic_steps=(
            "Normalize supplied public names and identifiers with configured exact rules before scoring.",
            "Score exact registration-number matches above corporate-number matches, name matches, and alias matches.",
            "Emit candidate matches only when public record receipts exist and private raw values remain absent.",
            "Keep unmatched CSV-derived facts tenant-private and hash-only; never export raw rows.",
        ),
        proof_handling=_proof_handling(
            "public_record_checks_must_reference_public_receipt_ids",
            "private_csv_facts_may_rank_or_filter_but_never_support_public_claim_text",
            "match_candidates_must_include_private_fingerprint_not_raw_value",
        ),
        gap_handling=_gap_handling(
            "missing_public_receipt_emits_gap_not_match",
            "below_threshold_match_emits_unmatched_private_fact",
            "conflicting_public_records_emit_ambiguous_counterparty_gap",
        ),
        numerical_method=NumericalMethod(
            method_id="deterministic_counterparty_match_score_v1",
            applies=True,
            formula=(
                "score = max(exact_invoice_number*1.0, exact_corporate_number*0.95, "
                "exact_normalized_name*0.85, configured_alias*0.75)"
            ),
            score_range=(0.0, 1.0),
            rounding="round_half_up_to_4_decimal_places_after_clamp_0_1",
            tie_breakers=(
                "higher_score",
                "public_receipt_observed_at_desc",
                "source_family_id",
                "receipt_id",
            ),
        ),
        advice_boundary=_common_advice_boundary(
            "candidate_match",
            "unmatched_private_fact",
            "public_record_check",
        ),
    )


def _subsidy_regulation_triage() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="subsidy_regulation_eligibility_triage_without_verdict",
        display_name="Subsidy/Regulation Eligibility Triage Without Verdict",
        purpose=(
            "Rank source-backed requirement signals for professional review without asserting "
            "subsidy eligibility, regulatory compliance, or accounting treatment."
        ),
        inputs=(
            BlueprintInput(
                "applicant_profile_facts",
                "Minimized applicant facts supplied by the user or derived from tenant-private CSV buckets.",
                "tenant_private_csv_fact",
                "tenant_private_minimized",
                required=False,
            ),
            BlueprintInput(
                "program_or_regulation_requirements",
                "Receipt-backed requirement, exclusion, deadline, and document rules from first-party evidence.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "triage_policy",
                "Configured signal weights and mandatory review gates for candidate ranking.",
                "configuration",
                "none",
            ),
        ),
        outputs=(
            BlueprintOutput(
                "triage_signals",
                "Requirement signals marked matched, missing, unknown, conflict, or professional_review_required.",
                "tenant_private",
                True,
            ),
            BlueprintOutput(
                "candidate_for_review",
                "Ranked candidate item for human review; explicitly not an eligibility or compliance verdict.",
                "tenant_private",
                True,
            ),
            BlueprintOutput(
                "questions_for_professional",
                "Deterministic questions generated from missing, unknown, or conflicting source-backed signals.",
                "tenant_private",
                True,
            ),
        ),
        deterministic_steps=(
            "Map applicant facts to requirement keys only when both sides have explicit normalized keys.",
            "Classify each requirement signal as matched, missing, unknown, conflict, or professional_review_required.",
            "Unknown and conflict signals reduce triage confidence but never become negative verdicts.",
            "Emit candidate_for_review and questions_for_professional instead of eligibility or compliance conclusions.",
        ),
        proof_handling=_proof_handling(
            "every_requirement_signal_must_reference_requirement_receipt_ids",
            "private_applicant_facts_must_remain_minimized_and_tenant_private",
            "candidate_for_review_must_include_do_not_claim_verdict_boundary",
        ),
        gap_handling=_gap_handling(
            "unknown_requirement_signal_emits_known_gap",
            "missing_applicant_fact_emits_question_not_negative_verdict",
            "conflicting_source_requirements_emit_professional_review_gap",
        ),
        numerical_method=NumericalMethod(
            method_id="known_signal_triage_ratio_v1",
            applies=True,
            formula=(
                "score = sum(matched_signal_weight) / sum(known_required_signal_weight); "
                "unknown and conflict signals are reported separately"
            ),
            score_range=(0.0, 1.0),
            rounding="round_half_up_to_4_decimal_places_after_clamp_0_1",
            tie_breakers=(
                "higher_score",
                "earlier_deadline",
                "fresher_requirement_receipt",
                "program_id",
            ),
        ),
        advice_boundary=_common_advice_boundary(
            "candidate_for_review",
            "triage_signal",
            "question_for_professional",
        ),
    )


def _deadline_risk_ranking() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="deadline_risk_ranking",
        display_name="Deadline Risk Ranking",
        purpose=(
            "Rank receipt-backed deadlines by deterministic urgency, preparation buffer, and source freshness "
            "so artifacts can prioritize review work without promising outcomes."
        ),
        inputs=(
            BlueprintInput(
                "deadline_records",
                "Receipt-backed deadlines with due_at, source_family_id, and required action labels.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "preparation_days_by_action",
                "Configured minimum preparation days per action type.",
                "configuration",
                "none",
            ),
            BlueprintInput(
                "as_of_date",
                "Deterministic evaluation date supplied by the caller or release capsule.",
                "clock_parameter",
                "none",
            ),
        ),
        outputs=(
            BlueprintOutput(
                "ranked_deadline_risks",
                "Deadline records sorted by risk score with formula ID, receipt IDs, and tie-break trace.",
                "public",
                True,
            ),
            BlueprintOutput(
                "overdue_or_imminent_gaps",
                "Known gaps or warnings when a due date is missing, stale, overdue, or inside prep buffer.",
                "public",
                True,
            ),
            BlueprintOutput(
                "calendar_hold_suggestions",
                "Non-advisory internal scheduling suggestions keyed to source-backed due dates.",
                "internal",
                True,
            ),
        ),
        deterministic_steps=(
            "Compute days_until_due from as_of_date and due_at using local calendar days.",
            "Compute buffer_ratio from preparation_days_by_action divided by max(days_until_due, 1).",
            "Add freshness penalty from source freshness state and missing-date penalty from gap state.",
            "Sort by descending risk score, then earliest due_at, then source_family_id and receipt_id.",
        ),
        proof_handling=_proof_handling(
            "ranked_deadlines_must_reference_deadline_receipt_ids",
            "calendar_suggestions_must_reference_same_due_at_source",
            "missing_due_at_cannot_be_ranked_as_if_known",
        ),
        gap_handling=_gap_handling(
            "missing_due_at_emits_known_gap",
            "overdue_deadline_emits_overdue_gap_not_outcome_statement",
            "stale_deadline_source_emits_refresh_required_gap",
        ),
        numerical_method=NumericalMethod(
            method_id="deadline_urgency_buffer_freshness_score_v1",
            applies=True,
            formula=(
                "risk_score = clamp(0, 100, urgency_points + buffer_pressure_points "
                "+ freshness_penalty_points + missing_data_penalty_points)"
            ),
            score_range=(0.0, 100.0),
            rounding="round_half_up_to_2_decimal_places_after_clamp_0_100",
            tie_breakers=("higher_risk_score", "earlier_due_at", "source_family_id", "receipt_id"),
        ),
        advice_boundary=_common_advice_boundary(
            "deadline_risk_rank",
            "review_priority",
            "known_gap",
        ),
    )


def _no_hit_semantics() -> AlgorithmBlueprint:
    return AlgorithmBlueprint(
        algorithm_id="no_hit_semantics",
        display_name="No-Hit Semantics",
        purpose=(
            "Represent no-hit observations as scoped search results with leases and gaps, never as proof "
            "that a record, program, obligation, or event does not exist."
        ),
        inputs=(
            BlueprintInput(
                "checked_scope",
                "Exact query scope, source families, filters, and observed_at timestamp that produced no hit.",
                "first_party_evidence",
                "public",
            ),
            BlueprintInput(
                "required_scope",
                "Configured source families and filters expected for the requested artifact.",
                "configuration",
                "none",
            ),
            BlueprintInput(
                "lease_policy",
                "Configured expiry duration for reusing a no-hit observation.",
                "configuration",
                "none",
            ),
        ),
        outputs=(
            BlueprintOutput(
                "no_hit_lease",
                "Scoped lease stating what was checked, when it expires, and that absence claims are disabled.",
                "public",
                True,
            ),
            BlueprintOutput(
                "unchecked_scope_gaps",
                "Known gaps for source families, filters, or periods outside the checked scope.",
                "public",
                True,
            ),
            BlueprintOutput(
                "next_checks",
                "Deterministic follow-up source families or filters needed before artifact completion.",
                "internal",
                True,
            ),
        ),
        deterministic_steps=(
            "Compare checked_scope to required_scope by exact source family, filter, and time-window keys.",
            "Emit a no_hit_lease only for the checked scope and configured expiry window.",
            "Emit unchecked_scope_gaps for any required scope outside the observed no-hit query.",
            "Disable absence claims in every public and internal no-hit output.",
        ),
        proof_handling=_proof_handling(
            "no_hit_lease_must_reference_checked_scope_and_observed_at",
            "no_hit_wording_must_say_observed_search_result_only",
            "unchecked_scope_gaps_must_list_missing_source_families_or_filters",
        ),
        gap_handling=_gap_handling(
            "no_hit_not_absence",
            "unchecked_scope_emits_known_gap",
            "expired_no_hit_lease_emits_refresh_required_gap",
        ),
        numerical_method=_no_numeric("scope_contract_no_score"),
        advice_boundary=_common_advice_boundary(
            "no_hit_observed",
            "unchecked_scope_gap",
            "refresh_required",
            professional_review_required=False,
        ),
    )
