"""Schema for `am_program_narrative` rows produced by Claude Code subagents.

Mirrors `scripts/migrations/wave24_136_am_program_narrative.sql`.
One JSONL row = one (program_id × lang × section) cell.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Section = Literal["overview", "eligibility", "application_flow", "pitfalls"]
Lang = Literal["ja", "en"]


class Narrative(BaseModel):
    program_id: int = Field(..., description="programs.id (jpintel) joining key")
    program_unified_id: str = Field(..., description="programs.unified_id literal")
    lang: Lang
    section: Section
    body_text: str = Field(..., min_length=1, description="解説本文")
    source_url_json: list[str] = Field(
        default_factory=list,
        description="一次資料 URL list (JSON-encoded on insert)",
    )
    model_id: str | None = Field(default=None, description="生成 subagent / model identifier")
    literal_quote_check_passed: int = Field(
        default=0, ge=0, le=1, description="ingest 側で literal-quote 検証後 1 に"
    )
    subagent_run_id: str = Field(..., description="trace id, batch_id-seq")
    generated_at: str = Field(..., description="ISO8601 UTC")
