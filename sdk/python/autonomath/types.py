"""Pydantic models mirroring the AutonoMath server models.

These are intentionally kept in sync by hand; when the server OpenAPI schema
stabilizes we will switch to generated models (see sdk/README.md).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["S", "A", "B", "C", "X"]
EvidencePacketProfile = Literal["full", "brief", "verified_only", "changes_only"]
EvidencePacketSourceTokensBasis = Literal["unknown", "pdf_pages", "token_count"]
EvidencePacketSubjectKind = Literal["program", "houjin"]
FundingStackVerdict = Literal["compatible", "incompatible", "requires_review", "unknown"]
IntelBundleObjective = Literal["max_amount", "max_count", "min_overlap"]


class Program(BaseModel):
    unified_id: str
    primary_name: str
    aliases: list[str] = []
    authority_level: str | None = None
    authority_name: str | None = None
    prefecture: str | None = None
    municipality: str | None = None
    program_kind: str | None = None
    official_url: str | None = None
    amount_max_man_yen: float | None = None
    amount_min_man_yen: float | None = None
    subsidy_rate: float | None = None
    trust_level: str | None = None
    tier: Tier | None = None
    coverage_score: float | None = None
    gap_to_tier_s: list[str] = []
    a_to_j_coverage: dict[str, Any] = {}
    excluded: bool = False
    exclusion_reason: str | None = None
    crop_categories: list[str] = []
    equipment_category: str | None = None
    target_types: list[str] = []
    funding_purpose: list[str] = []
    amount_band: str | None = None
    application_window: dict[str, Any] | None = None


class ProgramDetail(Program):
    enriched: dict[str, Any] | None = None
    source_mentions: list[dict[str, Any]] = []


class SearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[Program]


class ExclusionRule(BaseModel):
    rule_id: str
    kind: str
    severity: str | None = None
    program_a: str | None = None
    program_b: str | None = None
    program_b_group: list[str] = []
    description: str | None = None
    source_notes: str | None = None
    source_urls: list[str] = []
    extra: dict[str, Any] = {}


class ExclusionHit(BaseModel):
    rule_id: str
    kind: str
    severity: str | None = None
    programs_involved: list[str]
    description: str | None = None
    source_urls: list[str] = []


class ExclusionCheckResponse(BaseModel):
    program_ids: list[str]
    hits: list[ExclusionHit]
    checked_rules: int


class Meta(BaseModel):
    total_programs: int
    tier_counts: dict[str, int]
    prefecture_counts: dict[str, int]
    exclusion_rules_count: int
    last_ingested_at: str | None = None
    data_as_of: str | None = None


# kept for callers who want to build the request body explicitly
class ExclusionCheckRequest(BaseModel):
    program_ids: list[str] = Field(..., min_length=1)


class EvidencePacketCompression(BaseModel):
    model_config = ConfigDict(extra="allow")

    packet_tokens_estimate: int
    source_tokens_estimate: int | None = None
    avoided_tokens_estimate: int | None = None
    compression_ratio: float | None = None
    input_context_reduction_rate: float | None = None
    estimate_method: str | None = None
    estimate_disclaimer: str | None = None
    source_tokens_basis: EvidencePacketSourceTokensBasis = "unknown"
    source_tokens_input_source: str | None = None
    source_pdf_pages: int | None = None
    source_token_count: int | None = None
    estimate_scope: str = "input_context_only"
    savings_claim: str = "estimate_not_guarantee"
    provider_billing_not_guaranteed: bool = True
    cost_savings_estimate: dict[str, Any] | None = None


class EvidencePacketRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity_id: str
    primary_name: str | None = None
    record_kind: str | None = None
    source_url: str | None = None
    source_fetched_at: str | None = None
    source_health: dict[str, Any] | None = None
    fact_provenance_coverage_pct: float | None = None
    authority_name: str | None = None
    prefecture: str | None = None
    tier: str | None = None
    aliases: list[dict[str, Any]] | None = None
    pdf_fact_refs: list[dict[str, Any]] | None = None
    facts: list[dict[str, Any]] | None = None
    rules: list[dict[str, Any]] | None = None
    short_summary: dict[str, Any] | None = None
    precomputed: dict[str, Any] | None = None
    recent_changes: list[dict[str, Any]] | None = None


class EvidencePacketQuality(BaseModel):
    model_config = ConfigDict(extra="allow")

    freshness_bucket: str | None = None
    coverage_score: float | None = None
    known_gaps: list[str] = Field(default_factory=list)
    human_review_required: bool | None = None


class EvidencePacketVerification(BaseModel):
    model_config = ConfigDict(extra="allow")

    replay_endpoint: str | None = None
    provenance_endpoint: str | None = None
    freshness_endpoint: str | None = None


class EvidencePacketEvidenceValue(BaseModel):
    model_config = ConfigDict(extra="allow")

    records_returned: int
    source_linked_records: int
    precomputed_records: int
    pdf_fact_refs: int
    known_gap_count: int
    fact_provenance_coverage_pct_avg: float | None = None
    web_search_performed_by_jpcite: bool = False
    request_time_llm_call_performed: bool = False


class EvidencePacketInsightItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    signal: str
    message_ja: str
    source_fields: list[str] = Field(default_factory=list)
    severity: str | None = None


class EvidencePacketDecisionInsights(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "v1"
    generated_from: list[str] = Field(default_factory=list)
    why_review: list[EvidencePacketInsightItem] = Field(default_factory=list)
    next_checks: list[EvidencePacketInsightItem] = Field(default_factory=list)
    evidence_gaps: list[EvidencePacketInsightItem] = Field(default_factory=list)


class EvidencePacketEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    packet_id: str
    generated_at: str
    api_version: str
    corpus_snapshot_id: str
    query: dict[str, Any]
    answer_not_included: bool = True
    records: list[EvidencePacketRecord]
    quality: EvidencePacketQuality
    verification: EvidencePacketVerification
    compression: EvidencePacketCompression | None = None
    evidence_value: EvidencePacketEvidenceValue | None = None
    agent_recommendation: dict[str, Any] | None = None
    decision_insights: EvidencePacketDecisionInsights | None = None


class EvidencePacketQueryBody(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=500)
    filters: dict[str, Any] | None = None
    limit: int = Field(default=10, ge=1)
    include_facts: bool = True
    include_rules: bool = False
    include_compression: bool = False
    fields: str = "default"
    packet_profile: EvidencePacketProfile = "full"
    input_token_price_jpy_per_1m: float | None = None
    source_tokens_basis: EvidencePacketSourceTokensBasis = "unknown"
    source_pdf_pages: int | None = None
    source_token_count: int | None = None


class IntelEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    disclaimer: str = Field(default="", alias="_disclaimer")
    billing_unit: int | None = Field(default=None, alias="_billing_unit")
    corpus_snapshot_id: str | None = None


class IntelMatchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    industry_jsic_major: str
    prefecture_code: str
    capital_jpy: int | None = None
    employee_count: int | None = None
    keyword: str | None = None
    limit: int = 5


class IntelQuestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    field: str | None = None
    question: str | None = None
    reason: str | None = None
    kind: str | None = None
    impact: str | None = None
    blocking: bool | None = None


class IntelEligibilityGap(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str | None = None
    gap_type: str | None = None
    reason: str | None = None
    required_by: str | None = None
    impact: str | None = None
    blocking: bool | None = None
    expected: Any | None = None


class IntelDocumentReadiness(BaseModel):
    model_config = ConfigDict(extra="allow")

    required_document_count: int = 0
    forms_with_url_count: int = 0
    signature_required_count: int = 0
    signature_unknown_count: int = 0
    needs_user_confirmation: bool = False


class IntelMatchedProgram(BaseModel):
    model_config = ConfigDict(extra="allow")

    program_id: str | None = None
    primary_name: str | None = None
    tier: str | None = None
    match_score: float | None = None
    score_components: dict[str, Any] = Field(default_factory=dict)
    authority_name: str | None = None
    prefecture: str | None = None
    program_kind: str | None = None
    source_url: str | None = None
    eligibility_predicate: dict[str, Any] = Field(default_factory=dict)
    required_documents: list[dict[str, Any]] = Field(default_factory=list)
    next_questions: list[IntelQuestion] = Field(default_factory=list)
    eligibility_gaps: list[IntelEligibilityGap] = Field(default_factory=list)
    document_readiness: IntelDocumentReadiness = Field(default_factory=IntelDocumentReadiness)
    similar_adopted_companies: list[dict[str, Any]] = Field(default_factory=list)
    applicable_laws: list[dict[str, Any]] = Field(default_factory=list)
    applicable_tsutatsu: list[dict[str, Any]] = Field(default_factory=list)
    audit_proof: dict[str, Any] | None = None


class IntelMatchResponse(IntelEnvelope):
    matched_programs: list[IntelMatchedProgram] = Field(default_factory=list)
    total_candidates: int = 0
    applied_filters: list[str] = Field(default_factory=list)


class IntelDecisionSupportItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    signal: str | None = None
    insight_id: str | None = None
    action: str | None = None
    section: str | None = None
    message: str | None = None
    message_ja: str | None = None
    basis: list[str] = Field(default_factory=list)
    source_fields: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    priority: str | None = None
    reason: str | None = None


class IntelBundleOptimalRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    houjin_id: str | dict[str, Any]
    bundle_size: int = 5
    objective: IntelBundleObjective = "max_amount"
    exclude_program_ids: list[str] = Field(default_factory=list)
    prefer_categories: list[str] = Field(default_factory=list)


class IntelBundleDecisionSupport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "v1"
    generated_from: list[str] = Field(default_factory=list)
    why_this_matters: list[IntelDecisionSupportItem] = Field(default_factory=list)
    decision_insights: list[IntelDecisionSupportItem] = Field(default_factory=list)
    next_actions: list[IntelDecisionSupportItem] = Field(default_factory=list)


class IntelBundleOptimalResponse(IntelEnvelope):
    houjin_id: str | None = None
    bundle: list[dict[str, Any]] = Field(default_factory=list)
    bundle_total: dict[str, Any] = Field(default_factory=dict)
    conflict_avoidance: dict[str, Any] = Field(default_factory=dict)
    optimization_log: dict[str, Any] = Field(default_factory=dict)
    runner_up_bundles: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    decision_support: IntelBundleDecisionSupport = Field(default_factory=IntelBundleDecisionSupport)


class IntelHoujinDecisionSupport(BaseModel):
    model_config = ConfigDict(extra="allow")

    risk_summary: dict[str, Any] = Field(default_factory=dict)
    decision_insights: list[IntelDecisionSupportItem] = Field(default_factory=list)
    next_actions: list[IntelDecisionSupportItem] = Field(default_factory=list)
    known_gaps: list[dict[str, Any]] = Field(default_factory=list)


class IntelHoujinFullResponse(IntelEnvelope):
    houjin_bangou: str | None = None
    sections_returned: list[str] = Field(default_factory=list)
    max_per_section: int | None = None
    houjin_meta: dict[str, Any] | None = None
    adoption_history: list[dict[str, Any]] = Field(default_factory=list)
    enforcement_records: list[dict[str, Any]] = Field(default_factory=list)
    invoice_status: dict[str, Any] = Field(default_factory=dict)
    peer_summary: dict[str, Any] = Field(default_factory=dict)
    jurisdiction_breakdown: dict[str, Any] = Field(default_factory=dict)
    watch_status: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    decision_support: IntelHoujinDecisionSupport = Field(default_factory=IntelHoujinDecisionSupport)


class FundingStackCheckRequest(BaseModel):
    program_ids: list[str] = Field(..., min_length=2)


class FundingStackNextAction(BaseModel):
    model_config = ConfigDict(extra="allow")

    action_id: str
    label_ja: str
    detail_ja: str
    reason: str
    source_fields: list[str] = Field(default_factory=list)


class FundingStackPair(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    program_a: str
    program_b: str
    verdict: FundingStackVerdict
    confidence: float
    rule_chain: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[FundingStackNextAction] = Field(default_factory=list)
    disclaimer: str = Field(default="", alias="_disclaimer")


class FundingStackCheckResponse(IntelEnvelope):
    program_ids: list[str]
    all_pairs_status: FundingStackVerdict
    pairs: list[FundingStackPair] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[FundingStackNextAction] = Field(default_factory=list)
    total_pairs: int
