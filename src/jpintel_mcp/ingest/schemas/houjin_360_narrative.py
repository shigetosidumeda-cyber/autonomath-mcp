"""Schema for `am_houjin_360_narrative` rows.

Mirrors stub from `scripts/migrations/wave24_141_am_narrative_quarantine.sql`.
One JSONL row = one (houjin_bangou × lang) cell.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["ja", "en"]


class Houjin360Narrative(BaseModel):
    houjin_bangou: str = Field(..., min_length=13, max_length=13)
    lang: Lang
    body_text: str = Field(..., min_length=1, description="法人 360° 解説本文")
    source_url_json: list[str] = Field(default_factory=list, description="一次資料 URL list")
    model_id: str | None = None
    subagent_run_id: str
    generated_at: str = Field(..., description="ISO8601 UTC")
