"""Schema for `am_invoice_buyer_seller_graph` edges from EDINET XBRL.

Mirrors `scripts/migrations/wave24_133_am_invoice_buyer_seller_graph.sql`.
One JSONL row = one inferred trade edge.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConfidenceBand = Literal["high", "medium", "low"]
EvidenceKind = Literal[
    "public_disclosure", "joint_adoption", "supplier_list", "co_filing", "press_release"
]


class BuyerSellerEdge(BaseModel):
    seller_houjin_bangou: str = Field(..., min_length=13, max_length=13)
    buyer_houjin_bangou: str = Field(..., min_length=13, max_length=13)
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    inferred_industry: str | None = Field(default=None, description="買い手側 industry 推測 (任意)")
    evidence_kind: EvidenceKind
    evidence_count: int = Field(default=1, ge=1)
    source_url_json: list[str] = Field(default_factory=list)
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    subagent_run_id: str
    computed_at: str = Field(..., description="ISO8601 UTC")
