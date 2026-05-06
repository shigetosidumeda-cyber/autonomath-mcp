"""Schema for exclusion / prerequisite / combine rules in `exclusion_rules`.

Used by `tools/offline/run_extract_exclusion_rules_batch.py`. Mirrors the
JSONL contract documented at the top of that helper.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RuleKind = Literal["exclude", "prerequisite", "absolute", "combine_ok"]
Confidence = Literal["high", "med", "low"]


class ExclusionRule(BaseModel):
    kind: RuleKind
    target_program_id: int | None = None
    target_program_uid: str | None = None
    clause_quote: str = Field(
        ...,
        min_length=1,
        description="公募要領からの literal-quote (改変禁止、照合用)",
    )
    source_url: str = Field(..., description="一次資料 URL")
    confidence: Confidence


class ExclusionRulesBatchRow(BaseModel):
    """1 batch row = 1 program with N rules."""

    program_id: int = Field(..., description="programs.id (or 0 if not int-able)")
    program_uid: str = Field(..., description="programs.unified_id literal")
    rules: list[ExclusionRule] = Field(default_factory=list)
    subagent_run_id: str
    evaluated_at: str
