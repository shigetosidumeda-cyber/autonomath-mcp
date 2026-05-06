"""Schema for `am_enforcement_summary` rows.

Mirrors stub from `scripts/migrations/wave24_141_am_narrative_quarantine.sql`.
One JSONL row = one (enforcement_id × lang) cell.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Lang = Literal["ja", "en"]


class EnforcementSummary(BaseModel):
    enforcement_id: int = Field(..., description="am_enforcement_detail.enforcement_id")
    lang: Lang
    body_text: str = Field(..., min_length=1, description="行政処分の経緯・原因・結果サマリ")
    source_url_json: list[str] = Field(default_factory=list, description="一次資料 URL list")
    model_id: str | None = None
    subagent_run_id: str
    generated_at: str = Field(..., description="ISO8601 UTC")
