"""Schema for `am_program_documents` rows.

Mirrors `scripts/migrations/wave24_138_am_program_documents.sql`.
One JSONL row = one (program × document) requirement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocKind = Literal[
    "申請書",
    "計画書",
    "見積書",
    "登記簿",
    "納税証明",
    "財務諸表",
    "同意書",
    "その他",
]


class ApplicationDocument(BaseModel):
    program_unified_id: str = Field(..., description="programs.unified_id literal")
    doc_name: str = Field(..., min_length=1)
    doc_kind: DocKind | None = None
    yoshiki_no: str | None = Field(default=None, description="様式番号 (e.g. 様式第1号)")
    is_required: int = Field(default=1, ge=0, le=1)
    url: str | None = Field(default=None, description="直接 download URL")
    source_clause_quote: str | None = Field(
        default=None, description="公募要領からの literal substring"
    )
    notes: str | None = None
    subagent_run_id: str
    extracted_at: str = Field(..., description="ISO8601 UTC")


class ProgramDocumentsRow(BaseModel):
    """1 batch row = 1 program with N documents."""

    program_unified_id: str
    documents: list[ApplicationDocument] = Field(default_factory=list)
    subagent_run_id: str
    evaluated_at: str
