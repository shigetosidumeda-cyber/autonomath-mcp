"""Group ε response_model annotations (L6 — OpenAPI empty/opaque schema fix).

Pydantic shells used as ``response_model=`` on the 35 endpoints flagged by J2
as carrying empty / opaque OpenAPI schemas (notably the ``/v1/am/*`` family,
``/v1/stats/*``, ``/v1/meta/freshness``, and a couple of advisors / health
surfaces). Each model is the smallest contract that lets an AI agent reason
about the response shape without re-fetching, parsing, or guessing.

Design notes
------------
- Generic ``BaseModel`` envelopes (``SearchResponse[T]`` etc.) declare the
  pagination contract once. Concrete ``response_model=`` declarations use
  them parameterised with ``dict[str, Any]`` because the underlying tool
  outputs are heterogeneous EAV rows (``am_entities`` carries 12 record
  kinds; pinning each to a strict pydantic row would explode the
  schema). The agent still sees ``total/limit/offset/results`` keyed and
  typed — that's the 87% reduction the J2 audit was after.
- ``meta: dict | None`` carries the L5 envelope (alternative_intents,
  next_cursor, retrieval_note, …). Keeping it as ``dict`` rather than a
  strict envelope class avoids coupling L6 to L5's exact field set.
- ``model_config = {"extra": "allow"}`` is set on every model so the L5
  envelope-v2 wrapper (``_apply_envelope`` in api/autonomath.py) can
  additively merge fields like ``status``, ``result_count``, ``explanation``,
  ``suggested_actions``, ``api_version``, ``tool_name``, ``query_echo``,
  and the ``meta.suggestions / meta.alternative_intents / meta.tips`` block
  onto the wire response without Pydantic stripping them. The OpenAPI
  schema therefore lists the *minimum guaranteed* contract; agents can rely
  on those keys being present but should not assume they're the only keys.
- ``runtime overhead minimal``: FastAPI runs Pydantic validation by default
  but every existing return value already conforms (verified runtime via
  ``tools.search_*`` etc.). No conversion cost — the dict pass-through
  is byte-identical.
- ``error: dict | None`` is included on every model that the underlying
  tool's ``_safe_tool`` envelope can populate. That's the same shape as
  ErrorEnvelope below — we don't make the field strict because callers
  already branch on ``"error" in response``.
"""
from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# Shared model_config — see module docstring for why every response model
# tolerates extra keys. Defined once so the rule is grep-able.
_ALLOW_EXTRA: ClassVar[ConfigDict] = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Generic envelopes
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseModel):
    """Error response shape used by ``_safe_tool`` and the launch-CLI L5 wrap."""

    model_config = _ALLOW_EXTRA

    error: dict[str, Any] = Field(
        ..., description="{code, user_message, request_id, hint?, retry_with?}."
    )


class SearchResponse(BaseModel, Generic[T]):
    """Paginated list envelope.

    Mirrors the existing ``tools.search_*`` return shape: ``{total, limit,
    offset, results, meta?, retrieval_note?}``. ``meta`` is ``dict`` rather
    than a strict envelope so L5 can extend it without breaking L6's wire
    contract. ``error`` is set when the tool short-circuited (DB locked,
    schema mismatch); callers must check it before reading ``results``.
    """

    model_config = _ALLOW_EXTRA

    total: int = Field(..., description="Total candidate rows before paging.")
    limit: int = Field(..., description="Page size echoed from the request.")
    offset: int = Field(..., description="Page offset echoed from the request.")
    results: list[T] = Field(default_factory=list)
    meta: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional envelope: alternative_intents, retrieval_note, "
            "next_cursor, advisory hints. Wired by L5."
        ),
    )
    retrieval_note: str | None = Field(
        default=None,
        description=(
            "One-line provenance hint, e.g. "
            "'fts5_trigram + LIKE fallback (3 rows from 285)'."
        ),
    )
    error: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Set when the tool failed (DB unavailable / invalid input). "
            "When present, ``results`` is empty and the caller should "
            "surface the error message rather than render an empty list."
        ),
    )


class ActionResponse(BaseModel):
    """POST/action response — single ack with optional payload.

    Used for endpoints whose primary output is "did it work?" rather than a
    list of rows (e.g. POST /v1/am/validate, /v1/session/logout).
    """

    model_config = _ALLOW_EXTRA

    ok: bool = True
    id: str | int | None = None
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# AutonoMath am_* family — concrete models
# ---------------------------------------------------------------------------


class AMSearchResponse(SearchResponse[dict[str, Any]]):
    """Concrete `SearchResponse[Any]` used by ``/v1/am/*`` paginated tools.

    The underlying ``am_entities`` table is heterogeneous (12 record_kinds:
    program / tax_measure / certification / loan / adoption / …), so the
    row contract is left at ``dict`` rather than enumerated. The pagination
    + meta + error contract — which is what an agent needs to drive a loop
    — is fully typed.
    """


class AMOpenProgramsResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/open_programs`` — adds ``pivot_date`` (the date the snapshot
    was taken on, defaulting to today)."""

    pivot_date: str | None = Field(
        default=None, description="ISO YYYY-MM-DD of the snapshot date."
    )


class AMActiveAtResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/active_at`` — paginated list with the snapshot date."""

    pivot_date: str | None = None


class AMByLawResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/by_law`` — adds the alias-resolution debug field."""

    law_aliases_tried: list[str] = Field(
        default_factory=list,
        description="Fuzzy-match alias attempts tried before settling on a hit.",
    )


class AMEnumValuesResponse(BaseModel):
    """``GET /v1/am/enums/{enum_name}`` — distinct values + counts for an enum."""

    model_config = _ALLOW_EXTRA

    enum_name: str
    values: list[str] = Field(default_factory=list)
    frequency_map: dict[str, int] = Field(default_factory=dict)
    last_updated: str | None = None
    description: str | None = None
    error: dict[str, Any] | None = None


class AMRelatedResponse(BaseModel):
    """``GET /v1/am/related/{program_id}`` — graph walk over am_relation."""

    model_config = _ALLOW_EXTRA

    seed_id: str
    seed_kind: str | None = None
    relations: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    total_edges: int = 0
    depth: int = 1
    hint: str | None = None
    retry_with: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class AMIntentResponse(BaseModel):
    """``GET /v1/am/intent`` — natural-language → tool routing."""

    model_config = _ALLOW_EXTRA

    intent_id: str | None = None
    intent_name_ja: str | None = None
    confidence: float | None = None
    all_scores: list[dict[str, Any]] = Field(default_factory=list)
    sample_queries: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class AMReasonResponse(BaseModel):
    """``GET /v1/am/reason`` — citation-backed narrative answer."""

    model_config = _ALLOW_EXTRA

    intent: str | None = None
    intent_name_ja: str | None = None
    filters_extracted: dict[str, Any] = Field(default_factory=dict)
    answer_skeleton: str | None = None
    confidence: float | None = None
    missing_data: list[str] = Field(default_factory=list)
    precompute_gaps: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    db_bind_ok: bool | None = None
    db_bind_notes: list[str] | str | None = None
    persona_hint: str | None = None
    retry_with: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class AMTaxRuleResponse(BaseModel):
    """``GET /v1/am/tax_rule`` — single-measure tax rule lookup."""

    model_config = _ALLOW_EXTRA

    total: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class AMSimpleSearchResponse(BaseModel):
    """Lighter SearchResponse variant for tools that omit ``offset``.

    Used by ``search_gx_programs_am`` and the like that return ``{total,
    results}`` only. Listed separately so the OpenAPI schema is honest —
    we don't claim ``offset`` when the underlying tool doesn't ship it.
    """

    model_config = _ALLOW_EXTRA

    total: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class AMLoanSearchResponse(BaseModel):
    """``GET /v1/am/loans`` / ``mutual_plans`` — three-axis loan/共済 search."""

    model_config = _ALLOW_EXTRA

    total: int = 0
    limit: int = 10
    offset: int = 0
    result_count: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class AMEnforcementCheckResponse(BaseModel):
    """``GET /v1/am/enforcement`` — 排除期間チェック result."""

    model_config = _ALLOW_EXTRA

    queried: dict[str, Any] = Field(default_factory=dict)
    found: bool = False
    currently_excluded: bool = False
    active_exclusions: list[dict[str, Any]] = Field(default_factory=list)
    recent_history: list[dict[str, Any]] = Field(default_factory=list)
    all_count: int = 0
    error: dict[str, Any] | None = None


class AMLawArticleResponse(BaseModel):
    """``GET /v1/am/law_article`` — 条文 lookup."""

    model_config = _ALLOW_EXTRA

    found: bool = False
    law: dict[str, Any] | None = None
    article_id: str | None = None
    article_number: str | None = None
    article_number_sort: int | None = None
    title: str | None = None
    text_summary: str | None = None
    text_full: str | None = None
    effective_from: str | None = None
    effective_until: str | None = None
    last_amended: str | None = None
    source_url: str | None = None
    source_fetched_at: str | None = None
    error: dict[str, Any] | None = None


class AMAnnotationsResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/annotations/{entity_id}`` — examiner / quality / ML notes."""

    entity_id: str
    filters: dict[str, Any] = Field(default_factory=dict)


class AMValidateResponse(BaseModel):
    """``POST /v1/am/validate`` — generic intake validator output."""

    model_config = _ALLOW_EXTRA

    total: int = 0
    applicant_hash: str | None = None
    scope: str = "intake"
    entity_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class AMProvenanceResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/provenance/{entity_id}`` and the per-fact variant."""


# ---------------------------------------------------------------------------
# Stats / freshness / meta
# ---------------------------------------------------------------------------


class CoverageResponse(BaseModel):
    """``GET /v1/stats/coverage`` — dataset row counts."""

    model_config = _ALLOW_EXTRA  # tolerate future tables + envelope hints

    programs: int = 0
    case_studies: int = 0
    loan_programs: int = 0
    enforcement_cases: int = 0
    exclusion_rules: int = 0
    laws_jpintel: int = 0
    tax_rulesets: int = 0
    court_decisions: int = 0
    bids: int = 0
    invoice_registrants: int = 0
    generated_at: str


class FreshnessSourceStat(BaseModel):
    """Per-source freshness stats inside ``FreshnessResponse.sources``."""

    model_config = _ALLOW_EXTRA

    min: str | None = None
    max: str | None = None
    count: int = 0
    avg_interval_days: float | None = None


class FreshnessResponse(BaseModel):
    """``GET /v1/stats/freshness`` — per-source min/max/avg fetched_at."""

    model_config = _ALLOW_EXTRA

    sources: dict[str, FreshnessSourceStat] = Field(default_factory=dict)
    generated_at: str


class UsageDayBucket(BaseModel):
    model_config = _ALLOW_EXTRA

    date: str
    count: int = 0
    cumulative: int = 0


class UsageResponse(BaseModel):
    """``GET /v1/stats/usage`` — past-30d anonymous request counts."""

    model_config = _ALLOW_EXTRA

    window_days: int = 30
    since: str
    until: str
    daily: list[UsageDayBucket] = Field(default_factory=list)
    total: int = 0
    generated_at: str


class DataQualityResponse(BaseModel):
    """``GET /v1/stats/data_quality`` — per-fact uncertainty rollup (O8).

    Aggregates the `am_uncertainty_view` view into a transparency-grade
    summary: average per-record_kind score, license breakdown, freshness
    distribution, and a count of cross-source-agreed facts. Emitted via
    the same 5-min L4 cache as the other ``/v1/stats/*`` endpoints.
    """

    model_config = _ALLOW_EXTRA

    fact_count_total: int = 0
    mean_score: float | None = None
    label_histogram: dict[str, int] = Field(default_factory=dict)
    license_breakdown: dict[str, int] = Field(default_factory=dict)
    freshness_buckets: dict[str, int] = Field(default_factory=dict)
    field_kind_breakdown: dict[str, dict[str, Any]] = Field(default_factory=dict)
    cross_source_agreement: dict[str, Any] = Field(default_factory=dict)
    model: str = "beta_posterior_v1"
    generated_at: str


class ConfidencePerToolRow(BaseModel):
    model_config = _ALLOW_EXTRA

    tool: str
    discovery: float | None = None
    discovery_ci95: list[float] | None = None
    discovery_hits: int = 0
    discovery_trials: int = 0
    use: float | None = None
    use_ci95: list[float] | None = None
    use_hits: int = 0
    use_trials: int = 0
    by_cohort: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ConfidenceResponse(BaseModel):
    """``GET /v1/stats/confidence`` — Bayesian Discovery+Use posteriors."""

    model_config = _ALLOW_EXTRA

    window_days: int
    since: str
    until: str
    overall: dict[str, Any] = Field(default_factory=dict)
    per_tool: list[ConfidencePerToolRow] = Field(default_factory=list)
    generated_at: str


class MetaFreshnessRow(BaseModel):
    model_config = _ALLOW_EXTRA

    canonical_id: str
    name: str
    tier: str | None = None
    source_fetched_at: str | None = None
    days_ago: int = 0


class MetaFreshnessResponse(BaseModel):
    """``GET /v1/meta/freshness`` — public anti-staleness feed."""

    model_config = _ALLOW_EXTRA

    total: int = 0
    median_fetched_at: str | None = None
    pct_within_30d: float = 0.0
    pct_over_180d: float = 0.0
    top_rows: list[MetaFreshnessRow] = Field(default_factory=list)
    generated_at: str


# ---------------------------------------------------------------------------
# Static resources / 36協定 / health
# ---------------------------------------------------------------------------


class StaticResourceItem(BaseModel):
    model_config = _ALLOW_EXTRA

    id: str
    filename: str | None = None
    path_relative: str | None = None
    size_bytes: int | None = None


class StaticResourceList(BaseModel):
    model_config = _ALLOW_EXTRA

    total: int
    results: list[StaticResourceItem] = Field(default_factory=list)


class StaticResourceDetail(BaseModel):
    model_config = _ALLOW_EXTRA

    id: str
    license: str | None = None
    content: dict[str, Any] | list[Any] | str | None = None


class ExampleProfileItem(BaseModel):
    model_config = _ALLOW_EXTRA

    id: str
    filename: str | None = None
    size_bytes: int | None = None


class ExampleProfileList(BaseModel):
    model_config = _ALLOW_EXTRA

    total: int
    results: list[ExampleProfileItem] = Field(default_factory=list)


class ExampleProfileDetail(BaseModel):
    model_config = _ALLOW_EXTRA

    id: str
    profile: dict[str, Any] | None = None


class TemplateMetadataResponse(BaseModel):
    model_config = _ALLOW_EXTRA

    template_id: str
    obligation: str | None = None
    authority: str | None = None
    license: str | None = None
    quality_grade: str | None = None
    method: str | None = None
    uses_llm: bool = False
    required_fields: dict[str, list[str]] = Field(default_factory=dict)


class TemplateRenderResponse(BaseModel):
    model_config = _ALLOW_EXTRA

    template_id: str
    obligation: str | None = None
    authority: str | None = None
    license: str | None = None
    quality_grade: str | None = None
    method: str | None = None
    uses_llm: bool = False
    rendered_text: str


class DeepHealthResponse(BaseModel):
    """``GET /v1/am/health/deep`` — 10-check aggregate."""

    model_config = _ALLOW_EXTRA

    status: str = Field(..., description="ok | degraded | unhealthy")
    checks: dict[str, Any] = Field(default_factory=dict)
    generated_at: str | None = None


# ---------------------------------------------------------------------------
# Advisors / misc
# ---------------------------------------------------------------------------


class AdvisorDashboardSummary(BaseModel):
    model_config = _ALLOW_EXTRA

    clicks: int = 0
    conversions: int = 0
    unpaid_yen: int = 0
    paid_yen: int = 0


class AdvisorDashboardReferral(BaseModel):
    model_config = _ALLOW_EXTRA

    id: int
    token_prefix: str
    source_program_id: str | None = None
    clicked_at: str | None = None
    converted_at: str | None = None
    conversion_value_yen: int | None = None
    commission_yen: int | None = None
    commission_paid_at: str | None = None


class AdvisorDashboardResponse(BaseModel):
    model_config = _ALLOW_EXTRA

    advisor: dict[str, Any]
    summary: AdvisorDashboardSummary
    referrals: list[AdvisorDashboardReferral] = Field(default_factory=list)


__all__ = [
    "ErrorEnvelope",
    "SearchResponse",
    "ActionResponse",
    "AMSearchResponse",
    "AMOpenProgramsResponse",
    "AMActiveAtResponse",
    "AMByLawResponse",
    "AMEnumValuesResponse",
    "AMRelatedResponse",
    "AMIntentResponse",
    "AMReasonResponse",
    "AMTaxRuleResponse",
    "AMSimpleSearchResponse",
    "AMLoanSearchResponse",
    "AMEnforcementCheckResponse",
    "AMLawArticleResponse",
    "AMAnnotationsResponse",
    "AMValidateResponse",
    "AMProvenanceResponse",
    "CoverageResponse",
    "FreshnessSourceStat",
    "FreshnessResponse",
    "UsageDayBucket",
    "UsageResponse",
    "ConfidencePerToolRow",
    "ConfidenceResponse",
    "MetaFreshnessRow",
    "MetaFreshnessResponse",
    "StaticResourceItem",
    "StaticResourceList",
    "StaticResourceDetail",
    "ExampleProfileItem",
    "ExampleProfileList",
    "ExampleProfileDetail",
    "TemplateMetadataResponse",
    "TemplateRenderResponse",
    "DeepHealthResponse",
    "AdvisorDashboardSummary",
    "AdvisorDashboardReferral",
    "AdvisorDashboardResponse",
]
