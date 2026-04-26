"""Pydantic models mirroring the AutonoMath server models.

These are intentionally kept in sync by hand; when the server OpenAPI schema
stabilizes we will switch to generated models (see sdk/README.md).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["S", "A", "B", "C", "X"]


class Program(BaseModel):
    unified_id: str
    primary_name: str
    aliases: list[str] = []
    authority_level: str | None = None
    authority_name: str | None = None
    prefecture: str | None = None
    municipality: str | None = None
    program_kind: str | None = None
    official_url: str | None = None
    amount_max_man_yen: float | None = None
    amount_min_man_yen: float | None = None
    subsidy_rate: float | None = None
    trust_level: str | None = None
    tier: Tier | None = None
    coverage_score: float | None = None
    gap_to_tier_s: list[str] = []
    a_to_j_coverage: dict[str, Any] = {}
    excluded: bool = False
    exclusion_reason: str | None = None
    crop_categories: list[str] = []
    equipment_category: str | None = None
    target_types: list[str] = []
    funding_purpose: list[str] = []
    amount_band: str | None = None
    application_window: dict[str, Any] | None = None


class ProgramDetail(Program):
    enriched: dict[str, Any] | None = None
    source_mentions: list[dict[str, Any]] = []


class SearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[Program]


class ExclusionRule(BaseModel):
    rule_id: str
    kind: str
    severity: str | None = None
    program_a: str | None = None
    program_b: str | None = None
    program_b_group: list[str] = []
    description: str | None = None
    source_notes: str | None = None
    source_urls: list[str] = []
    extra: dict[str, Any] = {}


class ExclusionHit(BaseModel):
    rule_id: str
    kind: str
    severity: str | None = None
    programs_involved: list[str]
    description: str | None = None
    source_urls: list[str] = []


class ExclusionCheckResponse(BaseModel):
    program_ids: list[str]
    hits: list[ExclusionHit]
    checked_rules: int


class Meta(BaseModel):
    total_programs: int
    tier_counts: dict[str, int]
    prefecture_counts: dict[str, int]
    exclusion_rules_count: int
    last_ingested_at: str | None = None
    data_as_of: str | None = None


# kept for callers who want to build the request body explicitly
class ExclusionCheckRequest(BaseModel):
    program_ids: list[str] = Field(..., min_length=1)
