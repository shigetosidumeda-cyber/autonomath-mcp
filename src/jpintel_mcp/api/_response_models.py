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

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# Shared model_config — see module docstring for why every response model
# tolerates extra keys. Defined once so the rule is grep-able.
_ALLOW_EXTRA: ConfigDict = ConfigDict(extra="allow")

EVIDENCE_PACKET_EXAMPLE: dict[str, Any] = {
    "packet_id": "evp_example",
    "generated_at": "2026-05-02T12:00:00+09:00",
    "api_version": "v1",
    "corpus_snapshot_id": "snap_20260502",
    "query": {
        "user_intent": "Tokyo manufacturer subsidy evidence",
        "normalized_filters": {"prefecture": "Tokyo"},
    },
    "answer_not_included": True,
    "records": [
        {
            "entity_id": "program:example",
            "primary_name": "Example public program",
            "record_kind": "program",
            "source_url": "https://example.go.jp/program",
            "source_fetched_at": "2026-05-01T00:00:00+09:00",
            "source_checksum": "sha256:example",
            "license": "gov_standard_v2.0",
            "authority_name": "Example authority",
            "precomputed": {
                "basis": "am_program_summary",
                "summaries": {"200": "Short source-linked evidence summary."},
            },
        }
    ],
    "quality": {
        "freshness_bucket": "current",
        "coverage_score": 0.86,
        "known_gaps": [],
        "human_review_required": False,
    },
    "verification": {
        "replay_endpoint": "/v1/programs/search?q=...",
        "freshness_endpoint": "/v1/meta/freshness",
    },
    "compression": {
        "packet_tokens_estimate": 566,
        "source_tokens_estimate": 14000,
        "avoided_tokens_estimate": 13434,
        "compression_ratio": 0.0404,
        "input_context_reduction_rate": 0.9596,
        "source_tokens_basis": "pdf_pages",
        "source_pdf_pages": 20,
        "estimate_scope": "input_context_only",
        "savings_claim": "estimate_not_guarantee",
        "provider_billing_not_guaranteed": True,
        "cost_savings_estimate": {
            "currency": "JPY",
            "input_token_price_jpy_per_1m": 300,
            "gross_input_savings_jpy": 4.0,
            "jpcite_billable_units": 1,
            "jpcite_cost_jpy_ex_tax": 3,
            "net_savings_jpy_ex_tax": 1.0,
            "break_even_avoided_tokens": 10000,
            "break_even_source_tokens_estimate": 10566,
            "break_even_met": True,
            "input_context_only": True,
            "price_input_source": "caller_supplied",
            "billing_savings_claim": "estimate_not_guarantee",
            "provider_billing_not_guaranteed": True,
        },
    },
    "evidence_value": {
        "records_returned": 1,
        "source_linked_records": 1,
        "precomputed_records": 1,
        "pdf_fact_refs": 0,
        "known_gap_count": 0,
        "fact_provenance_coverage_pct_avg": 0.86,
        "web_search_performed_by_jpcite": False,
        "request_time_llm_call_performed": False,
    },
    "decision_insights": {
        "schema_version": "v1",
        "generated_from": [
            "records",
            "quality",
            "verification",
            "evidence_value",
            "corpus_snapshot_id",
        ],
        "why_review": [
            {
                "signal": "source_traceability",
                "message_ja": "一次資料URLと取得時点を確認できます。",
                "source_fields": ["records.source_url", "records.source_fetched_at"],
                "severity": "info",
            }
        ],
        "next_checks": [
            {
                "signal": "source_recheck",
                "message_ja": "最終判断前に一次資料を再確認してください。",
                "source_fields": ["records.source_url"],
                "severity": "review",
            }
        ],
        "evidence_gaps": [],
    },
}


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
            "One-line provenance hint, e.g. 'text search with fallback matching (3 rows from 285)'."
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
# Evidence Packet / LLM prefetch surfaces
# ---------------------------------------------------------------------------


class EvidencePacketCompression(BaseModel):
    """Context-size estimate block for compact Evidence Packets."""

    model_config = _ALLOW_EXTRA

    packet_tokens_estimate: int = Field(
        ..., description="Estimated tokens in the returned Evidence Packet."
    )
    source_tokens_estimate: int | None = Field(
        default=None,
        description=(
            "Estimated tokens in the source context the caller would otherwise send to an LLM."
        ),
    )
    avoided_tokens_estimate: int | None = Field(
        default=None,
        description="Estimated input-context tokens avoided by using the packet.",
    )
    compression_ratio: float | None = Field(
        default=None,
        description="packet_tokens_estimate / source_tokens_estimate when known.",
    )
    input_context_reduction_rate: float | None = Field(
        default=None,
        description=(
            "max(0, source - packet) / source. Caller-supplied input-context estimate only."
        ),
    )
    estimate_method: str | None = None
    estimate_disclaimer: str | None = Field(
        default=None,
        description="Human-readable disclaimer for context/cost estimates.",
    )
    source_tokens_basis: Literal["unknown", "pdf_pages", "token_count"] = "unknown"
    source_tokens_input_source: str | None = None
    source_pdf_pages: int | None = None
    source_token_count: int | None = None
    estimate_scope: str = Field(
        default="input_context_only",
        description=(
            "The estimate compares input context size only from caller-supplied baselines."
        ),
    )
    savings_claim: str = Field(
        default="estimate_not_guarantee",
        description="Machine-readable reminder that savings are estimates.",
    )
    provider_billing_not_guaranteed: bool = Field(
        default=True,
        description=(
            "Always true. Output / reasoning / cache / search / provider tool tokens "
            "are NOT measured by the compression block."
        ),
    )
    cost_savings_estimate: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional caller-price input-context comparison, including "
            "break_even_met and break_even_source_tokens_estimate when the "
            "caller supplied an input token price. Fields such as "
            "gross_input_savings_jpy and net_savings_jpy_ex_tax are "
            "input-context-only estimates; they exclude output, reasoning, "
            "cache, search, provider tool costs, and provider billing effects."
        ),
    )


class EvidencePacketRecord(BaseModel):
    """One source-linked record inside an Evidence Packet."""

    model_config = _ALLOW_EXTRA

    entity_id: str = Field(..., description="Stable program/houjin/entity id.")
    primary_name: str | None = None
    record_kind: str | None = None
    source_url: str | None = Field(default=None, description="Primary source URL when known.")
    source_fetched_at: str | None = Field(
        default=None,
        description="Fetch timestamp for the primary source when known.",
    )
    source_health: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional source freshness/licensing metadata from the local "
            "source catalog. No live URL fetch is performed."
        ),
    )
    fact_provenance_coverage_pct: float | None = Field(
        default=None,
        description="Share of included facts that carry source provenance.",
    )
    authority_name: str | None = None
    prefecture: str | None = None
    tier: str | None = None
    aliases: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional user-facing aliases, abbreviations, and old names.",
    )
    pdf_fact_refs: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional compact references to high-value facts sourced from PDF "
            "documents, so agents can cite without reading entire PDFs first."
        ),
    )
    facts: list[dict[str, Any]] | None = Field(
        default=None, description="Optional source-linked fact rows."
    )
    rules: list[dict[str, Any]] | None = Field(
        default=None, description="Optional compatibility/exclusion rules."
    )
    short_summary: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional smallest deterministic precomputed summary lifted for LLM context prefetch."
        ),
    )
    precomputed: dict[str, Any] | None = Field(
        default=None,
        description="Optional deterministic precomputed summary payload.",
    )
    recent_changes: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Optional compact user-facing amendment changes for this record. "
            "Implementation-only diff fields are not exposed."
        ),
    )


class EvidencePacketQuality(BaseModel):
    """Quality and gap metadata callers should inspect before answering."""

    model_config = _ALLOW_EXTRA

    freshness_bucket: str | None = None
    coverage_score: float | None = None
    known_gaps: list[str] = Field(default_factory=list)
    human_review_required: bool | None = None


class EvidencePacketVerification(BaseModel):
    """Replay and freshness endpoints for evidence verification."""

    model_config = _ALLOW_EXTRA

    replay_endpoint: str | None = None
    provenance_endpoint: str | None = None
    freshness_endpoint: str | None = None


class EvidencePacketEvidenceValue(BaseModel):
    """`evidence_value` block — AI-readable evidence counters.

    Always populated. Values are pure record/quality counts; jpcite does not
    perform a request-time LLM call or a live web search to produce them.
    """

    model_config = _ALLOW_EXTRA

    records_returned: int = Field(..., description="Total records[] entries.")
    source_linked_records: int = Field(
        ..., description="Records whose source_url is non-empty (or whose facts cite a source)."
    )
    precomputed_records: int = Field(
        ..., description="Records carrying a deterministic precomputed summary."
    )
    pdf_fact_refs: int = Field(..., description="Sum of pdf_fact_refs[] entries across records.")
    known_gap_count: int = Field(..., description="Length of quality.known_gaps for this packet.")
    fact_provenance_coverage_pct_avg: float | None = Field(
        default=None,
        description=(
            "Mean per-record fact_provenance_coverage_pct; null when no record "
            "carries a coverage figure."
        ),
    )
    web_search_performed_by_jpcite: bool = Field(
        default=False,
        description="Always false. The composer is read-only against local SQLite.",
    )
    request_time_llm_call_performed: bool = Field(
        default=False,
        description="Always false. The composer never calls an LLM at request time.",
    )


class EvidencePacketInsightItem(BaseModel):
    """One AI-facing decision insight derived from packet evidence."""

    model_config = _ALLOW_EXTRA

    signal: str = Field(..., description="Stable machine-readable insight id.")
    message_ja: str = Field(..., description="Short Japanese guidance for agents to quote.")
    source_fields: list[str] = Field(
        default_factory=list,
        description="Envelope fields used to derive this insight.",
    )
    severity: str | None = Field(
        default=None,
        description="Permissive severity label such as info, review, or warning.",
    )


class EvidencePacketDecisionInsights(BaseModel):
    """AI-facing guidance emitted on JSON Evidence Packet responses."""

    model_config = _ALLOW_EXTRA

    schema_version: str = Field(default="v1")
    generated_from: list[str] = Field(
        default_factory=list,
        description="Envelope sections used to derive the insight block.",
    )
    why_review: list[EvidencePacketInsightItem] = Field(
        default_factory=list,
        description="Reasons this packet is useful or needs review before answering.",
    )
    next_checks: list[EvidencePacketInsightItem] = Field(
        default_factory=list,
        description="Human or agent follow-up checks before relying on the packet.",
    )
    evidence_gaps: list[EvidencePacketInsightItem] = Field(
        default_factory=list,
        description="Known evidence gaps that should be surfaced to the user.",
    )


class EvidencePacketEnvelope(BaseModel):
    """Compact source-linked packet for LLM evidence prefetch."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"example": EVIDENCE_PACKET_EXAMPLE},
    )

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
    evidence_value: EvidencePacketEvidenceValue | None = Field(
        default=None,
        description=(
            "Evidence-value counters for source-linked records. Always populated "
            "by the composer; null only on older fixtures."
        ),
    )
    agent_recommendation: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Machine-readable guidance for LLM/tool agents deciding whether "
            "to recommend or skip this jpcite route."
        ),
    )
    decision_insights: EvidencePacketDecisionInsights | None = Field(
        default=None,
        description=(
            "JSON-only AI-facing guidance derived from records, quality, "
            "verification, evidence_value, and corpus_snapshot_id."
        ),
    )


FUNDING_STACK_CHECK_EXAMPLE: dict[str, Any] = {
    "program_ids": [
        "program:it-introduction-subsidy",
        "program:business-restructuring-subsidy",
    ],
    "all_pairs_status": "requires_review",
    "pairs": [
        {
            "program_a": "program:it-introduction-subsidy",
            "program_b": "program:business-restructuring-subsidy",
            "verdict": "requires_review",
            "confidence": 0.72,
            "rule_chain": [
                {
                    "source": "am_compat_matrix",
                    "rule_id": "compat_requires_cost_separation",
                    "reason": "Cost items and project scopes must be separated before stacking.",
                }
            ],
            "next_actions": [
                {
                    "action_id": "contact_program_office",
                    "label_ja": "制度事務局へ併用条件を照会する",
                    "detail_ja": (
                        "対象経費、申請年度、採択・交付決定の順序、他制度併用の有無を"
                        "具体的に示して、事務局へ確認してください。"
                    ),
                    "reason": (
                        "requires_review 判定は条件付き併用や前提認定の解釈が残っており、"
                        "機械判定だけで許可扱いにできないためです。"
                    ),
                    "source_fields": [
                        "verdict",
                        "confidence",
                        "warnings[].rule_chain",
                        "rule_chain[].note",
                    ],
                },
                {
                    "action_id": "separate_expense_categories",
                    "label_ja": "対象経費区分と事業範囲を分ける",
                    "detail_ja": (
                        "設備費、外注費、ソフトウェア費などの区分ごとに、どちらの制度で"
                        "申請するかを明確化してください。"
                    ),
                    "reason": (
                        "条件付き併用では、経費区分と事業範囲が分離できるかが"
                        "事務局確認の中心になるためです。"
                    ),
                    "source_fields": [
                        "program_a",
                        "program_b",
                        "rule_chain[].rule_text",
                    ],
                },
            ],
            "_disclaimer": "Verify current public guidelines and application-round rules.",
        }
    ],
    "blockers": [],
    "warnings": [
        {
            "code": "round_specific_rules",
            "message": "Application-round details may change the stackability decision.",
        }
    ],
    "next_actions": [
        {
            "action_id": "contact_program_office",
            "label_ja": "制度事務局へ併用条件を照会する",
            "detail_ja": (
                "対象経費、申請年度、採択・交付決定の順序、他制度併用の有無を"
                "具体的に示して、事務局へ確認してください。"
            ),
            "reason": (
                "requires_review 判定は条件付き併用や前提認定の解釈が残っており、"
                "機械判定だけで許可扱いにできないためです。"
            ),
            "source_fields": [
                "verdict",
                "confidence",
                "warnings[].rule_chain",
                "rule_chain[].note",
            ],
        },
        {
            "action_id": "separate_expense_categories",
            "label_ja": "対象経費区分と事業範囲を分ける",
            "detail_ja": (
                "設備費、外注費、ソフトウェア費などの区分ごとに、どちらの制度で"
                "申請するかを明確化してください。"
            ),
            "reason": (
                "条件付き併用では、経費区分と事業範囲が分離できるかが"
                "事務局確認の中心になるためです。"
            ),
            "source_fields": [
                "program_a",
                "program_b",
                "rule_chain[].rule_text",
            ],
        },
    ],
    "_disclaimer": "Rule-engine result only; final decisions require primary-source review.",
    "total_pairs": 1,
}


class FundingStackNextAction(BaseModel):
    """Human-readable follow-up action emitted by funding-stack verdicts."""

    model_config = _ALLOW_EXTRA

    action_id: str = Field(..., description="Stable machine-readable action id.")
    label_ja: str = Field(..., description="Short Japanese action label.")
    detail_ja: str = Field(..., description="Concrete human-readable instruction for the action.")
    reason: str = Field(..., description="Why this action follows from the verdict.")
    source_fields: list[str] = Field(
        default_factory=list,
        description="Response fields used to derive or verify this action.",
    )


class FundingStackPair(BaseModel):
    """Per-pair funding-stack compatibility verdict."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    program_a: str
    program_b: str
    verdict: Literal["compatible", "incompatible", "requires_review", "unknown"]
    confidence: float
    rule_chain: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Rules that contributed to the verdict, in evaluation order.",
    )
    next_actions: list[FundingStackNextAction] = Field(
        default_factory=list,
        description="Human-readable follow-up checklist items for this pair.",
    )
    disclaimer: str = Field(
        default="",
        alias="_disclaimer",
        description="Pair-level disclaimer; verify primary sources before decisions.",
    )


class FundingStackCheckResponse(BaseModel):
    """Response for POST /v1/funding_stack/check."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        json_schema_extra={"example": FUNDING_STACK_CHECK_EXAMPLE},
    )

    program_ids: list[str]
    all_pairs_status: Literal[
        "compatible",
        "incompatible",
        "requires_review",
        "unknown",
    ]
    pairs: list[FundingStackPair] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[FundingStackNextAction] = Field(
        default_factory=list,
        description="Aggregated human-readable follow-up checklist items across pairs.",
    )
    disclaimer: str = Field(
        default="",
        alias="_disclaimer",
        description="Stack-level disclaimer; not legal or tax advice.",
    )
    total_pairs: int = Field(..., description="Number of evaluated pairs.")


class IntelQuestion(BaseModel):
    """Customer question generated from eligibility or document gaps."""

    model_config = _ALLOW_EXTRA

    id: str | None = None
    field: str | None = None
    question: str | None = None
    reason: str | None = None
    kind: str | None = None
    impact: str | None = None
    blocking: bool | None = None


class IntelEligibilityGap(BaseModel):
    """Missing or uncertain applicant input for a matched program."""

    model_config = _ALLOW_EXTRA

    field: str | None = None
    gap_type: str | None = None
    reason: str | None = None
    required_by: str | None = None
    impact: str | None = None
    blocking: bool | None = None
    expected: Any | None = None


class IntelDocumentReadiness(BaseModel):
    """Document-preparation counters for one matched program."""

    model_config = _ALLOW_EXTRA

    required_document_count: int = 0
    forms_with_url_count: int = 0
    signature_required_count: int = 0
    signature_unknown_count: int = 0
    needs_user_confirmation: bool = False


class IntelMatchedProgram(BaseModel):
    """One program returned by POST /v1/intel/match."""

    model_config = _ALLOW_EXTRA

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
    next_questions: list[IntelQuestion] = Field(
        default_factory=list,
        description="AI-facing customer questions needed before application work.",
    )
    eligibility_gaps: list[IntelEligibilityGap] = Field(
        default_factory=list,
        description="Missing or uncertain eligibility inputs for this match.",
    )
    document_readiness: IntelDocumentReadiness = Field(
        default_factory=IntelDocumentReadiness,
        description=("Required-document readiness counters derived from program documents."),
    )
    similar_adopted_companies: list[dict[str, Any]] = Field(default_factory=list)
    applicable_laws: list[dict[str, Any]] = Field(default_factory=list)
    applicable_tsutatsu: list[dict[str, Any]] = Field(default_factory=list)
    audit_proof: dict[str, Any] | None = None


class IntelMatchResponse(BaseModel):
    """Response for POST /v1/intel/match."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    matched_programs: list[IntelMatchedProgram] = Field(default_factory=list)
    total_candidates: int = 0
    applied_filters: list[str] = Field(default_factory=list)
    disclaimer: str = Field(default="", alias="_disclaimer")
    billing_unit: int = Field(default=1, alias="_billing_unit")


class IntelDecisionSupportItem(BaseModel):
    """One AI-facing decision-support item."""

    model_config = _ALLOW_EXTRA

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


class IntelBundleDecisionSupport(BaseModel):
    """AI-facing support block for /v1/intel/bundle/optimal."""

    model_config = _ALLOW_EXTRA

    schema_version: str = "v1"
    generated_from: list[str] = Field(default_factory=list)
    why_this_matters: list[IntelDecisionSupportItem] = Field(default_factory=list)
    decision_insights: list[IntelDecisionSupportItem] = Field(default_factory=list)
    next_actions: list[IntelDecisionSupportItem] = Field(default_factory=list)


class IntelBundleOptimalResponse(BaseModel):
    """Response for POST /v1/intel/bundle/optimal."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    houjin_id: str | None = None
    bundle: list[dict[str, Any]] = Field(default_factory=list)
    bundle_total: dict[str, Any] = Field(default_factory=dict)
    conflict_avoidance: dict[str, Any] = Field(default_factory=dict)
    optimization_log: dict[str, Any] = Field(default_factory=dict)
    runner_up_bundles: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    decision_support: IntelBundleDecisionSupport = Field(
        default_factory=IntelBundleDecisionSupport,
        description="AI-facing rationale, tradeoffs, and follow-up actions.",
    )
    disclaimer: str = Field(default="", alias="_disclaimer")
    billing_unit: int = Field(default=1, alias="_billing_unit")


class IntelHoujinDecisionSupport(BaseModel):
    """AI-facing support block for /v1/intel/houjin/{houjin_id}/full."""

    model_config = _ALLOW_EXTRA

    risk_summary: dict[str, Any] = Field(default_factory=dict)
    decision_insights: list[IntelDecisionSupportItem] = Field(default_factory=list)
    next_actions: list[IntelDecisionSupportItem] = Field(default_factory=list)
    known_gaps: list[dict[str, Any]] = Field(default_factory=list)


class IntelHoujinFullResponse(BaseModel):
    """Response for GET /v1/intel/houjin/{houjin_id}/full."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

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
    decision_support: IntelHoujinDecisionSupport = Field(
        default_factory=IntelHoujinDecisionSupport,
        description=("Corporate DD risk summary, insights, next actions, and known gaps."),
    )
    disclaimer: str = Field(default="", alias="_disclaimer")
    billing_unit: int = Field(default=1, alias="_billing_unit")


class PrecomputedMetadata(BaseModel):
    """Metadata describing deterministic precomputed corpus artifacts."""

    model_config = _ALLOW_EXTRA

    available: bool
    basis_tables: list[str] = Field(default_factory=list)
    record_count: int
    note: str | None = None


class PrecomputedUsage(BaseModel):
    """How agents should use a precomputed-intelligence bundle."""

    model_config = _ALLOW_EXTRA

    intended_for: str = "llm_context_prefetch"
    web_search_required: bool = False
    jpcite_requests: int = 1
    billing_units: int = 1


class PrecomputedAgentRecommendation(BaseModel):
    """Machine-readable guidance for LLM agents deciding whether to use jpcite."""

    model_config = _ALLOW_EXTRA

    recommendation: Literal[
        "use_jpcite_prefetch",
        "use_evidence_packet",
        "broaden_query_or_skip",
    ]
    recommend_to_user: bool = Field(
        ...,
        description=(
            "True when the response contains enough source-linked value for "
            "an agent to recommend jpcite in this turn."
        ),
    )
    recommend_for_evidence: bool = Field(
        default=False,
        description=(
            "True when at least one record is source-linked. "
            "Independent of caller-supplied price baseline."
        ),
    )
    evidence_decision: Literal[
        "supported_by_source_linked_records",
        "no_records_returned",
        "records_returned_without_source_links",
    ] = Field(
        default="no_records_returned",
        description=("Machine-readable basis for the `recommend_for_evidence` boolean."),
    )
    recommend_for_cost_savings: bool = Field(
        ...,
        description=(
            "True only when caller-supplied baseline tokens and price make "
            "the input-context break-even comparison pass."
        ),
    )
    cost_savings_decision: Literal[
        "needs_caller_baseline",
        "needs_input_token_price",
        "supported_by_caller_baseline",
        "not_supported_by_caller_baseline",
    ] = Field(
        ...,
        description=(
            "Machine-readable guardrail for cost-savings claims. Agents "
            "should not present jpcite as cost-saving unless this is "
            "`supported_by_caller_baseline`."
        ),
    )
    missing_for_cost_claim: list[str] = Field(default_factory=list)
    route: str = Field(
        ...,
        description="Best next jpcite API route for the agent to call.",
    )
    reason_codes: list[str] = Field(default_factory=list)
    value_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Positive signals an agent may quote when justifying "
            "a jpcite recommendation. Always derived from the same evidence "
            "as `reason_codes`."
        ),
    )
    message: str = Field(
        ...,
        description="Short human-readable explanation for the recommendation.",
    )
    context_savings: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Break-even and avoided-token estimate when the caller supplied "
            "a comparable source-token baseline. Includes "
            "`break_even_source_tokens_estimate` "
            "(packet + break-even avoided)."
        ),
    )


PRECOMPUTED_INTELLIGENCE_EXAMPLE: dict[str, Any] = {
    **EVIDENCE_PACKET_EXAMPLE,
    "bundle_kind": "precomputed_intelligence",
    "bundle_id": "pci_example",
    "answer_basis": "precomputed",
    "records_returned": 1,
    "precomputed_record_count": 1,
    "precomputed": {
        "available": True,
        "basis_tables": ["am_program_summary"],
        "record_count": 1,
        "note": (
            "Precomputed summaries are deterministic corpus artifacts. "
            "They are not generated by a request-time LLM."
        ),
    },
    "usage": {
        "intended_for": "llm_context_prefetch",
        "web_search_required": False,
        "jpcite_requests": 1,
        "billing_units": 1,
    },
    "compression": {
        "packet_tokens_estimate": 566,
        "source_tokens_basis": "unknown",
        "source_tokens_estimate": None,
        "avoided_tokens_estimate": None,
        "compression_ratio": None,
        "input_context_reduction_rate": None,
        "estimate_method": "none",
        "estimate_disclaimer": (
            "Compression estimates compare input context size only. "
            "Provider billing can differ because of output, reasoning, cache, "
            "search, and tool charges."
        ),
        "source_tokens_input_source": None,
        "estimate_scope": "input_context_only",
        "savings_claim": "estimate_not_guarantee",
        "provider_billing_not_guaranteed": True,
    },
    "agent_recommendation": {
        "recommendation": "use_jpcite_prefetch",
        "recommend_to_user": True,
        "recommend_for_evidence": True,
        "evidence_decision": "supported_by_source_linked_records",
        "recommend_for_cost_savings": False,
        "cost_savings_decision": "needs_caller_baseline",
        "missing_for_cost_claim": [
            "source_tokens_basis",
            "source_pdf_pages_or_source_token_count",
            "input_token_price_jpy_per_1m",
        ],
        "route": "/v1/intelligence/precomputed/query",
        "reason_codes": [
            "precomputed_summary_available",
            "source_linked_records_returned",
            "no_request_time_llm",
            "no_live_web_search",
        ],
        "value_reasons": [
            "source_linked_records_returned",
            "precomputed_summary_available",
            "no_request_time_llm",
            "no_live_web_search",
        ],
        "message": (
            "Use this bundle before sending long Japanese public-program "
            "sources to an LLM; it provides compact, source-linked context."
        ),
        "context_savings": {
            "evaluated": False,
            "break_even_met": None,
            "break_even_source_tokens_estimate": None,
            "source_tokens_basis": "unknown",
            "avoided_tokens_estimate": None,
            "input_context_reduction_rate": None,
            "provider_billing_not_guaranteed": True,
            "savings_claim": "estimate_not_guarantee",
        },
    },
}


class PrecomputedIntelligenceBundle(EvidencePacketEnvelope):
    """Evidence Packet envelope annotated with precomputed-intelligence usage."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"example": PRECOMPUTED_INTELLIGENCE_EXAMPLE},
    )

    bundle_kind: Literal["precomputed_intelligence"]
    bundle_id: str
    answer_basis: str
    records_returned: int
    precomputed_record_count: int
    precomputed: PrecomputedMetadata
    usage: PrecomputedUsage
    agent_recommendation: PrecomputedAgentRecommendation  # type: ignore[assignment]


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

    pivot_date: str | None = Field(default=None, description="ISO YYYY-MM-DD of the snapshot date.")


class AMActiveAtResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/active_at`` — paginated list with the snapshot date."""

    pivot_date: str | None = None


class AMByLawResponse(SearchResponse[dict[str, Any]]):
    """``GET /v1/am/by_law`` — returns law-linked records with alias metadata."""

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
    """``GET /v1/am/reason`` — citation-backed answer skeleton."""

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
    """``GET /v1/am/annotations/{entity_id}`` — public annotation signals."""

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
    laws: int = Field(
        0,
        title="Laws",
        description="Law metadata records in the public jpcite corpus.",
    )
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
    """``GET /v1/am/health/deep`` — 10-check aggregate + Sentry probe.

    ``sentry_active`` (read-only) reflects whether ``_init_sentry`` succeeded
    at lifespan startup. False when Sentry is not configured or the production
    runtime gate was not satisfied. Aggregate ``status`` is
    intentionally unaffected — Sentry being dark is a meta-signal for the
    operator, not a fail/warn for the API itself.
    """

    model_config = _ALLOW_EXTRA

    status: str = Field(..., description="ok | degraded | unhealthy")
    checks: dict[str, Any] = Field(default_factory=dict)
    sentry_active: bool | None = Field(
        default=None,
        description="True iff Sentry SDK initialised at API lifespan startup.",
    )
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
