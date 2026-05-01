from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jpintel_mcp.models.premium_response import (
    AdoptionScore,
    AuditLogEntry,
    PostGrantTaskKind,
    PremiumResponse,
    ProvenanceBadge,
    ProvenanceTier,
    QualityGrade,
)

Tier = Literal["S", "A", "B", "C", "X"]

# Controls how much of each program row is returned.
# - "minimal": bare list fields (unified_id, primary_name, tier, prefecture,
#   authority_name, amount_max_man_yen, official_url). ~300 bytes/row.
# - "default": current Program shape (unchanged, backwards compatible).
# - "full": default + enriched (A-J dimensions) + source_mentions + lineage.
#   enriched/source_mentions are ALWAYS keyed even when null, so callers can
#   tell "we looked and it's empty" from "the server didn't ship this field".
FieldsLevel = Literal["minimal", "default", "full"]

# Whitelist of keys kept when fields=minimal. Applied as a dict filter.
# Conservative by design: prefer more fields if unsure. Do not slim without
# a concrete bandwidth win worth the coordination cost with callers.
MINIMAL_FIELD_WHITELIST: tuple[str, ...] = (
    "unified_id",
    "primary_name",
    "tier",
    "prefecture",
    "authority_name",
    "amount_max_man_yen",
    "official_url",
)


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
    # Actionable-row fields — surfaced on every search row so callers can
    # answer "when's the deadline / where do I apply" without a second
    # round-trip. Both are cheap (already-parsed JSON / column aliasing).
    next_deadline: str | None = Field(
        default=None,
        description=(
            "ISO date of the next open-window end_date from application_window, "
            "or null when the window is rolling / unknown / already past."
        ),
    )
    application_url: str | None = Field(
        default=None,
        description=(
            "URL the caller should send an applicant to. Currently aliases "
            "official_url; once enriched 申請方法 extraction stabilises this "
            "will prefer the dedicated apply page when one exists."
        ),
    )
    static_url: str | None = Field(
        default=None,
        description=(
            "Site-relative path to the per-program SEO page on "
            "jpcite.com (`/programs/{slug}-{sha1-6}.html`). "
            "Generated from `primary_name` + `unified_id`. Use this to "
            "deep-link result cards / share URLs / mailto bodies into "
            "the static site instead of constructing `/programs/{unified_id}.html` "
            "(no such file exists; that pattern returns 404)."
        ),
    )


class ProgramDetail(Program):
    enriched: dict[str, Any] | None = None
    source_mentions: dict[str, Any] | list[Any] = {}
    source_url: str | None = None
    source_fetched_at: str | None = None
    source_checksum: str | None = None
    # Heavier actionable-row field — only populated on the detail path
    # because it requires parsing enriched_json, which we avoid in the
    # search hot path (cache + lazy JSON policy). List of document *names*
    # only; format / template_url / pages stay inside `enriched`.
    required_documents: list[str] = Field(
        default_factory=list,
        description=(
            "Best-effort list of required document names extracted from the "
            "enriched procedure dimension. Empty list = we haven't extracted "
            "documents for this program yet (not 'none needed')."
        ),
    )


class SearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[Program]


class BatchGetProgramsRequest(BaseModel):
    """Body for POST /v1/programs/batch.

    `unified_ids` is capped at 50 — the 50-cap IS the pagination. Callers
    with more ids page the request themselves (request.py: chunk(ids, 50)).
    The cap lives here (pydantic) AND is also enforced inside the handler;
    exceeding it surfaces as HTTP 422 per the usual FastAPI validation path.
    """

    unified_ids: list[str] = Field(..., min_length=1, max_length=50)


class BatchGetProgramsResponse(BaseModel):
    """Response for POST /v1/programs/batch.

    `results[]` is in the same order as the deduped input `unified_ids`.
    Missing ids go to `not_found` (NOT a 404 — partial success is the point
    of batch-fetch). Use `not_found` length == 0 as the "everything resolved"
    signal.
    """

    results: list[ProgramDetail]
    not_found: list[str]


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


class ExclusionCheckRequest(BaseModel):
    program_ids: list[str] = Field(..., min_length=1)


class ExclusionHit(BaseModel):
    rule_id: str
    kind: str
    severity: str | None
    programs_involved: list[str]
    description: str | None
    source_urls: list[str] = []


class ExclusionCheckResponse(BaseModel):
    program_ids: list[str]
    hits: list[ExclusionHit]
    checked_rules: int


class DataLineage(BaseModel):
    last_fetched_at: str | None = None
    unique_checksums: int = 0


class Meta(BaseModel):
    total_programs: int
    tier_counts: dict[str, int]
    prefecture_counts: dict[str, int]
    exclusion_rules_count: int
    last_ingested_at: str | None
    data_as_of: str | None = None
    data_lineage: DataLineage = DataLineage()


class EnforcementCase(BaseModel):
    """A single 会計検査院 (Board of Audit) finding.

    Backs /v1/enforcement-cases/*. These are historical records of improper
    subsidy handling (over-payment, diversion, documentation failure, etc.)
    used for compliance / due-diligence checks before advising a client on a
    program with prior clawback history.
    """

    case_id: str
    event_type: str | None = None
    program_name_hint: str | None = None
    recipient_name: str | None = None
    recipient_kind: str | None = None
    recipient_houjin_bangou: str | None = None
    is_sole_proprietor: bool | None = None
    bureau: str | None = None
    intermediate_recipient: str | None = None
    prefecture: str | None = None
    ministry: str | None = None
    occurred_fiscal_years: list[int] = []
    amount_yen: int | None = None
    amount_project_cost_yen: int | None = None
    amount_grant_paid_yen: int | None = None
    amount_improper_grant_yen: int | None = None
    amount_improper_project_cost_yen: int | None = None
    reason_excerpt: str | None = None
    legal_basis: str | None = None
    source_url: str | None = None
    source_section: str | None = None
    source_title: str | None = None
    disclosed_date: str | None = None
    disclosed_until: str | None = None
    fetched_at: str | None = None
    confidence: float | None = None


class EnforcementCaseSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[EnforcementCase]


class CaseStudy(BaseModel):
    """A 採択事例 / success-story record.

    Backs /v1/case-studies/*. Collected from Jグランツ 採択結果 pages,
    mirasapo 事業事例, local prefectural 事例集, etc. Used as evidence
    ("program X has actually paid out to a similar business") and as a
    lookup for due-diligence on named recipients.
    """

    case_id: str
    company_name: str | None = None
    houjin_bangou: str | None = None
    is_sole_proprietor: bool | None = None
    prefecture: str | None = None
    municipality: str | None = None
    industry_jsic: str | None = None
    industry_name: str | None = None
    employees: int | None = None
    founded_year: int | None = None
    capital_yen: int | None = None
    case_title: str | None = None
    case_summary: str | None = None
    programs_used: list[str] = []
    total_subsidy_received_yen: int | None = None
    outcomes: list[Any] | dict[str, Any] | None = None
    patterns: list[Any] | dict[str, Any] | None = None
    publication_date: str | None = None
    source_url: str | None = None
    source_excerpt: str | None = None
    fetched_at: str | None = None
    confidence: float | None = None


class CaseStudySearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[CaseStudy]


# Three-axis loan risk enum — see project_autonomath_loan_risk_axes.
# Single free-text `security_required` is deprecated for filter surfaces;
# callers should filter on the three axes individually.
LoanRiskAxis = Literal["required", "not_required", "negotiable", "unknown"]


class LoanProgram(BaseModel):
    """A 融資プログラム row — 日本政策金融公庫 / 地方自治体 / 信金 etc.

    Backs /v1/loan-programs/*. Post-2026-04-23 the `security_required` free
    text has been normalised into three independent axes (collateral,
    personal guarantor, third-party guarantor) so callers can filter
    "無担保・無保証 only" vs. "担保あり＋代表者保証あり" without parsing JP prose.
    """

    id: int
    program_name: str
    provider: str | None = None
    loan_type: str | None = None
    amount_max_yen: int | None = None
    loan_period_years_max: int | None = None
    grace_period_years_max: int | None = None
    interest_rate_base_annual: float | None = None
    interest_rate_special_annual: float | None = None
    rate_names: str | None = None
    # Legacy free-text — kept for audit / migration inspection but not
    # recommended for machine filtering. Use the three axes below.
    security_required: str | None = None
    target_conditions: str | None = None
    official_url: str | None = None
    source_excerpt: str | None = None
    fetched_at: str | None = None
    confidence: float | None = None
    # 013_loan_risk_structure: independent, machine-filterable axes.
    collateral_required: LoanRiskAxis | None = None
    personal_guarantor_required: LoanRiskAxis | None = None
    third_party_guarantor_required: LoanRiskAxis | None = None
    security_notes: str | None = None


class LoanProgramSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[LoanProgram]


# ---------------------------------------------------------------------------
# 法令 (laws) — backs /v1/laws/*
#
# Canonical catalog of 憲法 / 法律 / 政令 / 勅令 / 府省令 / 規則 / 告示 /
# ガイドライン harvested from e-Gov 法令 API V2 (CC-BY 4.0). Every row
# carries source_url + fetched_at per the non-negotiable lineage rule.
# ---------------------------------------------------------------------------

LawType = Literal[
    "constitution",
    "act",
    "cabinet_order",
    "imperial_order",
    "ministerial_ordinance",
    "rule",
    "notice",
    "guideline",
]

LawRevisionStatus = Literal["current", "superseded", "repealed"]


class Law(BaseModel):
    # `extra="allow"` so the get-by-id handler can inject `corpus_snapshot_id`
    # + `corpus_checksum` (会計士 work-paper reproducibility, 2026-04-29) onto
    # the wire payload without violating the model. Search responses ship the
    # snapshot pair on the LawSearchResponse envelope (see below).
    model_config = ConfigDict(extra="allow")

    unified_id: str = Field(..., description="LAW-<10 lowercase hex>")
    law_number: str
    law_title: str
    law_short_title: str | None = None
    law_type: LawType
    ministry: str | None = None
    promulgated_date: str | None = None
    enforced_date: str | None = None
    last_amended_date: str | None = None
    revision_status: LawRevisionStatus = "current"
    superseded_by_law_id: str | None = None
    article_count: int | None = None
    full_text_url: str | None = None
    summary: str | None = None
    subject_areas: list[str] = []
    source_url: str
    source_checksum: str | None = None
    confidence: float = 0.95
    fetched_at: str
    updated_at: str | None = None


class LawSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[Law]


class RelatedProgramRef(BaseModel):
    """A program citing a given law (reverse lookup via program_law_refs)."""

    program_unified_id: str
    ref_kind: str = Field(
        ...,
        description=(
            "One of: authority | eligibility | exclusion | reference | penalty"
        ),
    )
    article_citation: str | None = None
    program_name: str | None = None
    source_url: str
    fetched_at: str
    confidence: float = 0.9


class RelatedProgramsResponse(BaseModel):
    law_unified_id: str
    total: int
    limit: int
    offset: int
    results: list[RelatedProgramRef]


# ---------------------------------------------------------------------------
# 判例 (court_decisions) — backs /v1/court-decisions/*
#
# Supersets the legacy 012 case_law catalog. Primary source is courts.go.jp
# hanrei_jp (裁判所判例検索). D1 Law / Westlaw / LEX/DB redistribution
# is banned at ingest.
# ---------------------------------------------------------------------------

CourtLevel = Literal["supreme", "high", "district", "summary", "family"]
DecisionType = Literal["判決", "決定", "命令"]
PrecedentWeight = Literal["binding", "persuasive", "informational"]


class CourtDecision(BaseModel):
    # `extra="allow"` for the same audit-trail injection rationale as Law:
    # the get-by-id handler attaches `corpus_snapshot_id` + `corpus_checksum`
    # so 会計士 work-papers can reproduce the evaluation later.
    model_config = ConfigDict(extra="allow")

    unified_id: str = Field(..., description="HAN-<10 lowercase hex>")
    case_name: str
    case_number: str | None = None
    court: str | None = None
    court_level: CourtLevel
    decision_date: str | None = None
    decision_type: DecisionType
    subject_area: str | None = None
    related_law_ids: list[str] = []
    key_ruling: str | None = None
    parties_involved: str | None = None
    impact_on_business: str | None = None
    precedent_weight: PrecedentWeight = "informational"
    full_text_url: str | None = None
    pdf_url: str | None = None
    source_url: str
    source_excerpt: str | None = None
    source_checksum: str | None = None
    confidence: float = 0.9
    fetched_at: str
    updated_at: str | None = None


class CourtDecisionSearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[CourtDecision]


class CourtDecisionByStatuteRequest(BaseModel):
    """Body for POST /v1/court-decisions/by-statute.

    Resolves decisions that cite a given law (and optionally a specific
    article). Matches against `related_law_ids_json` on court_decisions.
    When `article_citation` is supplied, the match is tightened via
    LIKE on `key_ruling` / `source_excerpt` — the 判例 ingest does not
    yet store a structured citation map, so a fuzzy contains-check is
    the honest signal.
    """

    law_id: str = Field(..., description="LAW-<10 hex> unified_id")
    article_citation: str | None = Field(
        default=None,
        description="e.g. '第5条第2項'. Optional — omit for whole-law matches.",
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


__all__ = [
    # Premium response (re-exported from models/premium_response.py).
    "QualityGrade",
    "ProvenanceTier",
    "PostGrantTaskKind",
    "ProvenanceBadge",
    "AdoptionScore",
    "AuditLogEntry",
    "PremiumResponse",
    # Core program shapes.
    "Tier",
    "FieldsLevel",
    "MINIMAL_FIELD_WHITELIST",
    "Program",
    "ProgramDetail",
    "SearchResponse",
    "BatchGetProgramsRequest",
    "BatchGetProgramsResponse",
    "ExclusionRule",
    "ExclusionCheckRequest",
    "ExclusionHit",
    "ExclusionCheckResponse",
    "DataLineage",
    "Meta",
    "EnforcementCase",
    "EnforcementCaseSearchResponse",
    "CaseStudy",
    "CaseStudySearchResponse",
    "LoanRiskAxis",
    "LoanProgram",
    "LoanProgramSearchResponse",
    "LawType",
    "LawRevisionStatus",
    "Law",
    "LawSearchResponse",
    "RelatedProgramRef",
    "RelatedProgramsResponse",
    "CourtLevel",
    "DecisionType",
    "PrecedentWeight",
    "CourtDecision",
    "CourtDecisionSearchResponse",
    "CourtDecisionByStatuteRequest",
]
