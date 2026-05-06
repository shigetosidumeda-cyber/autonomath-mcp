"""Schema for JSIC tagging output (programs.jsic_major / middle / minor).

Mirrors `scripts/migrations/wave24_113a_programs_jsic.sql`.
One JSONL row = one program with assigned JSIC code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


JsicMajor = Literal[
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
]
AssignedMethod = Literal["manual", "keyword", "classifier"]


class JsicTag(BaseModel):
    program_unified_id: str = Field(..., min_length=1)
    jsic_major: JsicMajor | None = None
    jsic_middle: str | None = Field(default=None, description="2-digit JSIC middle code")
    jsic_minor: str | None = Field(default=None, description="3-digit JSIC minor code")
    jsic_assigned_method: AssignedMethod = Field(
        default="classifier",
        description="manual / keyword / classifier — subagent uses 'classifier'",
    )
    rationale: str | None = Field(
        default=None,
        description="判定理由 (program 名 + 公募要領のキーワード等)",
    )
    confidence: Literal["high", "med", "low"] = "med"
    subagent_run_id: str
    assigned_at: str = Field(..., description="ISO8601 UTC")

    @field_validator("jsic_middle")
    @classmethod
    def _check_middle(cls, v: str | None) -> str | None:
        if v is not None and len(v) != 2:
            raise ValueError("jsic_middle must be exactly 2 chars")
        return v

    @field_validator("jsic_minor")
    @classmethod
    def _check_minor(cls, v: str | None) -> str | None:
        if v is not None and len(v) != 3:
            raise ValueError("jsic_minor must be exactly 3 chars")
        return v
