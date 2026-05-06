"""Schema for `am_program_eligibility_predicate` rows.

Mirrors `scripts/migrations/wave24_137_am_program_eligibility_predicate.sql`.
One JSONL row = one (program × predicate_kind × operator × value) tuple.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PredicateKind = Literal[
    "capital_max",
    "capital_min",
    "employee_max",
    "employee_min",
    "fy_revenue_max",
    "fy_revenue_min",
    "jsic_in",
    "jsic_not_in",
    "region_in",
    "region_not_in",
    "invoice_required",
    "tax_compliance_required",
    "no_enforcement_within_years",
    "business_age_min_years",
    "capital_band_in",
    "other",
]
Operator = Literal["=", "!=", "<", "<=", ">", ">=", "IN", "NOT_IN", "CONTAINS", "EXISTS"]


class EligibilityPredicate(BaseModel):
    program_unified_id: str = Field(..., min_length=1)
    predicate_kind: PredicateKind
    operator: Operator
    value_text: str | None = None
    value_num: float | None = None
    value_json: str | None = Field(default=None, description="JSON-encoded list for IN / NOT_IN")
    is_required: int = Field(default=1, ge=0, le=1)
    source_url: str | None = None
    source_clause_quote: str | None = Field(default=None, description="literal substring (照合用)")
    subagent_run_id: str
    extracted_at: str = Field(..., description="ISO8601 UTC")


class EligibilityPredicateBatchRow(BaseModel):
    """1 batch row = 1 program with N predicates."""

    program_unified_id: str
    predicates: list[EligibilityPredicate] = Field(default_factory=list)
    subagent_run_id: str
    evaluated_at: str
