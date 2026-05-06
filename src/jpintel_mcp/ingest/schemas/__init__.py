"""Pydantic v2 schemas for offline subagent JSONL output validation.

Each module here mirrors one offline batch helper under
`tools/offline/run_*_batch.py`. The helper imports the schema to render
the JSON-Schema for the subagent prompt, and `scripts/cron/ingest_offline_inbox.py`
re-imports it to validate inbox JSONL rows before INSERT.

NO LLM SDK imports here. NO production runtime path imports these modules
either — they are dataclass-shaped DTOs only.

The 8 (+ legacy amount_conditions wrapper) tool keys recognized by
`ingest_offline_inbox`:

    exclusion_rules                -> ExclusionRulesBatchRow  (jpintel.exclusion_rules)
    enforcement_amount             -> EnforcementAmountRow    (autonomath.am_enforcement_detail UPDATE)
    jsic_classification            -> JsicTag                 (autonomath.programs.jsic_*)
    program_narrative              -> Narrative               (autonomath.am_program_narrative)
    houjin_360_narrative           -> Houjin360Narrative      (autonomath.am_houjin_360_narrative)
    enforcement_summary            -> EnforcementSummary      (autonomath.am_enforcement_summary)
    program_application_documents  -> ProgramDocumentsRow     (autonomath.am_program_documents)
    edinet_relations               -> BuyerSellerEdge         (autonomath.am_invoice_buyer_seller_graph)
    eligibility_predicates         -> EligibilityPredicateBatchRow (autonomath.am_program_eligibility_predicate)
    amount_conditions              -> AmountConditionRow      (autonomath.am_amount_condition UPDATE)
    public_source_foundation       -> SourceProfileRow        (autonomath.source_document)

Use ``resolve_schema(tool)`` to fetch the model class, or import directly
when you know the tool name at import time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .eligibility_predicate import (
    EligibilityPredicate,
    EligibilityPredicateBatchRow,
)
from .enforcement_summary import EnforcementSummary
from .exclusion_rule import ExclusionRule, ExclusionRulesBatchRow
from .houjin_360_narrative import Houjin360Narrative
from .invoice_buyer_seller import BuyerSellerEdge
from .jsic_tag import JsicTag
from .program_documents import ApplicationDocument, ProgramDocumentsRow
from .program_narrative import Narrative
from .public_source_foundation import SourceProfileRow


class EnforcementAmountRow(BaseModel):
    """UPDATE row for `am_enforcement_detail.amount_yen`.

    Mirrors the inline model previously embedded in
    `scripts/cron/ingest_offline_inbox.py::_models`. Lifting it here
    centralizes the schema so future tooling (subagent prompt
    generation, JSON-Schema export) imports from one place.
    """

    model_config = ConfigDict(extra="ignore")
    enforcement_id: int
    amount_yen: int | None = None
    amount_kind: (
        Literal[
            "fine",
            "grant_refund",
            "subsidy_exclude",
            "contract_suspend",
            "business_improvement",
            "license_revoke",
            "investigation",
            "other",
        ]
        | None
    ) = None
    currency: Literal["JPY"] = "JPY"
    clause_quote: str = Field(min_length=1)
    source_url: str = Field(min_length=4)
    source_fetched_at: str | None = None
    confidence: Literal["high", "med", "low"]
    subagent_run_id: str
    evaluated_at: str

    @field_validator("amount_yen")
    @classmethod
    def _non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("amount_yen must be >= 0")
        return v

    @field_validator("clause_quote")
    @classmethod
    def _non_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("clause_quote must contain non-whitespace")
        return v


class AmountConditionRow(BaseModel):
    """Backfill row for `am_amount_condition` (entity-keyed amount facts).

    Mirrors the columns added by Wave 24 § amount_condition
    re-validation: `is_authoritative=1` flips a row from the broken
    template-default ETL pass to a literal-quote-backed value.
    """

    model_config = ConfigDict(extra="ignore")
    entity_id: str = Field(min_length=1)
    condition_label: str = Field(min_length=1)
    condition_kind: str | None = None
    numeric_value: float | None = None
    numeric_value_max: float | None = None
    unit: str | None = None
    currency: str | None = None
    qualifier: str | None = None
    confidence: Literal["high", "med", "low"]
    extracted_text: str = Field(min_length=1)
    source_url: str = Field(min_length=4)
    subagent_run_id: str
    evaluated_at: str

    @field_validator("numeric_value")
    @classmethod
    def _non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("numeric_value must be >= 0")
        return v


# ---------------------------------------------------------------------------
# Public registry — tool key → top-level row schema class.
# Top-level here means "one JSONL line maps to exactly one instance of
# this class". Nested per-rule / per-doc / per-predicate sub-models are
# enforced as `list[...]` on the wrapper model.
# ---------------------------------------------------------------------------

SCHEMAS: dict[str, type[BaseModel]] = {
    "exclusion_rules": ExclusionRulesBatchRow,
    "enforcement_amount": EnforcementAmountRow,
    "jsic_classification": JsicTag,
    "jsic_tags": JsicTag,
    "program_narrative": Narrative,
    "houjin_360_narrative": Houjin360Narrative,
    "enforcement_summary": EnforcementSummary,
    "program_application_documents": ProgramDocumentsRow,
    "edinet_relations": BuyerSellerEdge,
    "eligibility_predicates": EligibilityPredicateBatchRow,
    "amount_conditions": AmountConditionRow,
    "public_source_foundation": SourceProfileRow,
}


def resolve_schema(tool: str) -> type[BaseModel]:
    """Resolve a tool key to its Pydantic v2 row schema.

    Raises ``KeyError`` on unknown tool — the cron uses this to refuse
    to ingest a directory whose schema we don't recognize.
    """
    return SCHEMAS[tool]


# ---------------------------------------------------------------------------
# Canonical aliases — the 8 tool schemas under their `*Row` brand names.
# These are the names used by the spec / external docs. Each is a no-op
# alias to the underlying class so `from jpintel_mcp.ingest.schemas import
# JsicTagsRow` works without a second class definition.
# ---------------------------------------------------------------------------
JsicTagsRow = JsicTag
NarrativeRow = Narrative
Houjin360NarrativeRow = Houjin360Narrative
EnforcementSummaryRow = EnforcementSummary
AppDocsRow = ProgramDocumentsRow
EdinetRelationRow = BuyerSellerEdge
EligibilityPredicateRow = EligibilityPredicateBatchRow
ExclusionRulesRow = ExclusionRulesBatchRow


__all__ = [
    "AmountConditionRow",
    "ApplicationDocument",
    "AppDocsRow",
    "BuyerSellerEdge",
    "EdinetRelationRow",
    "EligibilityPredicate",
    "EligibilityPredicateBatchRow",
    "EligibilityPredicateRow",
    "EnforcementAmountRow",
    "EnforcementSummary",
    "EnforcementSummaryRow",
    "ExclusionRule",
    "ExclusionRulesBatchRow",
    "ExclusionRulesRow",
    "Houjin360Narrative",
    "Houjin360NarrativeRow",
    "JsicTag",
    "JsicTagsRow",
    "Narrative",
    "NarrativeRow",
    "ProgramDocumentsRow",
    "SCHEMAS",
    "SourceProfileRow",
    "resolve_schema",
]
