"""Premium response shapes for jpintel-mcp /v1/am/* endpoints.
Inspired by Autonomath's models/{adoption,client}.py + knowledge_base/provenance.py."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

QualityGrade = Literal["S", "A", "B", "C", "D"]
ProvenanceTier = Literal["canonical", "researched", "modeled", "mock"]
PostGrantTaskKind = Literal[
    "performance_report",
    "status_report",
    "asset_disposal_check",
    "tax_filing",
    "insurance_renewal",
    "training_attendance",
    "on_site_audit",
    "custom",
]


class ProvenanceBadge(BaseModel):
    """Quality + visibility badge for any data field."""

    tier: ProvenanceTier
    client_visible: bool = True
    annotation: str | None = None  # short caveat for client display

    @computed_field
    @property
    def color(self) -> str:
        return {
            "canonical": "green",
            "researched": "blue",
            "modeled": "yellow",
            "mock": "red",
        }[self.tier]


class AdoptionScore(BaseModel):
    """Likelihood signal for whether an applicant matches a program profile."""

    score: float = Field(ge=0.0, le=1.0)
    verdict: Literal["pass", "borderline", "fail"]
    matched_review_criteria: list[str] = Field(default_factory=list)
    matched_common_mistakes: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _verdict_consistent(self) -> AdoptionScore:
        # Pass score thresholds — empirical from Autonomath constants:
        # >= 0.70 pass, 0.50-0.70 borderline, < 0.50 fail
        if self.score >= 0.70:
            expected = "pass"
        elif self.score >= 0.50:
            expected = "borderline"
        else:
            expected = "fail"
        if self.verdict != expected:
            raise ValueError(
                f"verdict {self.verdict} inconsistent with score {self.score} (expected {expected})"
            )
        return self


class AuditLogEntry(BaseModel):
    """Tamper-evident append-only log entry (content_hash auto-computed, frozen)."""

    model_config = ConfigDict(frozen=True)

    entry_id: str
    timestamp_utc: datetime
    actor: str  # e.g. "api:anonymous" / "api:key:<hash>" / "system:cron"
    action: str  # e.g. "validate", "search", "annotation_added"
    payload: dict[str, object]
    content_hash: str = ""  # auto-set by validator; never accept user input

    @model_validator(mode="after")
    def _set_and_verify_hash(self) -> AuditLogEntry:
        canonical = (
            f"{self.entry_id}|{self.timestamp_utc.isoformat()}|{self.actor}|"
            f"{self.action}|{sorted(self.payload.items())}"
        )
        expected = sha256(canonical.encode("utf-8")).hexdigest()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash tampered or pre-set incorrectly")
        # frozen=True means we can't assign normally; bypass via object.__setattr__ (only safe in validator)
        object.__setattr__(self, "content_hash", expected)
        return self


class PremiumResponse(BaseModel):
    """Wrapper for ¥3/req endpoints adding quality grade + provenance + warnings + freshness."""

    data: object  # the actual result payload
    quality_grade: QualityGrade
    quality_score: float = Field(ge=0.0, le=1.0)
    provenance: ProvenanceBadge
    warnings: list[str] = Field(default_factory=list)
    data_freshness: datetime  # max(updated_at) of underlying source
    request_id: str  # propagated from middleware


__all__ = [
    "QualityGrade",
    "ProvenanceTier",
    "PostGrantTaskKind",
    "ProvenanceBadge",
    "AdoptionScore",
    "AuditLogEntry",
    "PremiumResponse",
]
