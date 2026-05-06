"""Tests for jpintel_mcp.models.premium_response."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from jpintel_mcp.models.premium_response import (
    AdoptionScore,
    AuditLogEntry,
    PremiumResponse,
    ProvenanceBadge,
)


# ──────────────────────────────────────────────────────────────
# ProvenanceBadge: 4 tiers all yield correct color
# ──────────────────────────────────────────────────────────────


def test_provenance_badge_canonical_is_green() -> None:
    badge = ProvenanceBadge(tier="canonical")
    assert badge.color == "green"


def test_provenance_badge_researched_is_blue() -> None:
    badge = ProvenanceBadge(tier="researched")
    assert badge.color == "blue"


def test_provenance_badge_modeled_is_yellow() -> None:
    badge = ProvenanceBadge(tier="modeled", client_visible=False)
    assert badge.color == "yellow"
    assert badge.client_visible is False


def test_provenance_badge_mock_is_red() -> None:
    badge = ProvenanceBadge(tier="mock", client_visible=False, annotation="DEMO ONLY")
    assert badge.color == "red"
    assert badge.annotation == "DEMO ONLY"


def test_provenance_badge_rejects_unknown_tier() -> None:
    with pytest.raises(ValidationError):
        ProvenanceBadge(tier="bogus")  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────
# AdoptionScore: verdict-score consistency
# ──────────────────────────────────────────────────────────────


def test_adoption_score_pass_threshold() -> None:
    score = AdoptionScore(score=0.8, verdict="pass")
    assert score.verdict == "pass"
    assert score.matched_review_criteria == []


def test_adoption_score_borderline_threshold() -> None:
    score = AdoptionScore(
        score=0.6,
        verdict="borderline",
        matched_common_mistakes=["budget breakdown vague"],
        suggested_fixes=["add line-item table"],
    )
    assert score.verdict == "borderline"
    assert "add line-item table" in score.suggested_fixes


def test_adoption_score_fail_threshold() -> None:
    score = AdoptionScore(score=0.3, verdict="fail")
    assert score.verdict == "fail"


def test_adoption_score_mismatch_pass_high_rejected() -> None:
    # 0.8 should map to pass, not fail
    with pytest.raises(ValidationError) as exc:
        AdoptionScore(score=0.8, verdict="fail")
    assert "inconsistent" in str(exc.value)


def test_adoption_score_mismatch_borderline_called_pass_rejected() -> None:
    # 0.6 should map to borderline, not pass
    with pytest.raises(ValidationError):
        AdoptionScore(score=0.6, verdict="pass")


def test_adoption_score_score_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        AdoptionScore(score=1.5, verdict="pass")


def test_adoption_score_boundary_exactly_0_70_is_pass() -> None:
    score = AdoptionScore(score=0.70, verdict="pass")
    assert score.verdict == "pass"


def test_adoption_score_boundary_exactly_0_50_is_borderline() -> None:
    score = AdoptionScore(score=0.50, verdict="borderline")
    assert score.verdict == "borderline"


# ──────────────────────────────────────────────────────────────
# AuditLogEntry: deterministic hash + frozen + tamper detection
# ──────────────────────────────────────────────────────────────


def _sample_entry(**overrides: object) -> AuditLogEntry:
    base = dict(
        entry_id="evt_001",
        timestamp_utc=datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc),
        actor="api:anonymous",
        action="validate",
        payload={"endpoint": "/v1/am/validate", "ok": True},
    )
    base.update(overrides)
    return AuditLogEntry(**base)  # type: ignore[arg-type]


def test_audit_log_content_hash_is_deterministic() -> None:
    e1 = _sample_entry()
    e2 = _sample_entry()
    assert e1.content_hash == e2.content_hash
    assert len(e1.content_hash) == 64  # sha256 hex


def test_audit_log_content_hash_changes_when_payload_differs() -> None:
    e1 = _sample_entry(payload={"a": 1})
    e2 = _sample_entry(payload={"a": 2})
    assert e1.content_hash != e2.content_hash


def test_audit_log_frozen_rejects_mutation() -> None:
    entry = _sample_entry()
    with pytest.raises(ValidationError):
        entry.actor = "evil"  # type: ignore[misc]


def test_audit_log_pre_set_wrong_hash_raises() -> None:
    with pytest.raises(ValidationError) as exc:
        AuditLogEntry(
            entry_id="evt_002",
            timestamp_utc=datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc),
            actor="api:anonymous",
            action="validate",
            payload={"endpoint": "/v1/am/validate"},
            content_hash="0" * 64,  # tampered / forged
        )
    assert "tampered" in str(exc.value)


def test_audit_log_pre_set_correct_hash_accepted() -> None:
    # Construct once to capture the legitimate hash, then re-construct with it
    e1 = _sample_entry()
    e2 = AuditLogEntry(
        entry_id="evt_001",
        timestamp_utc=datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc),
        actor="api:anonymous",
        action="validate",
        payload={"endpoint": "/v1/am/validate", "ok": True},
        content_hash=e1.content_hash,
    )
    assert e1.content_hash == e2.content_hash


# ──────────────────────────────────────────────────────────────
# PremiumResponse: full instance constructs without error
# ──────────────────────────────────────────────────────────────


def test_premium_response_full_construction() -> None:
    resp = PremiumResponse(
        data={"programs": [{"id": "P-001", "name": "経営革新計画"}]},
        quality_grade="A",
        quality_score=0.92,
        provenance=ProvenanceBadge(tier="canonical", annotation="METI 公式"),
        warnings=["募集期間外"],
        data_freshness=datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc),
        request_id="req_abc123",
    )
    assert resp.quality_grade == "A"
    assert resp.provenance.color == "green"
    assert resp.warnings == ["募集期間外"]
    assert resp.request_id == "req_abc123"


def test_premium_response_quality_score_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        PremiumResponse(
            data={},
            quality_grade="S",
            quality_score=1.5,
            provenance=ProvenanceBadge(tier="canonical"),
            data_freshness=datetime(2026, 4, 25, tzinfo=timezone.utc),
            request_id="req_x",
        )


def test_premium_response_invalid_grade_rejected() -> None:
    with pytest.raises(ValidationError):
        PremiumResponse(
            data={},
            quality_grade="Z",  # type: ignore[arg-type]
            quality_score=0.5,
            provenance=ProvenanceBadge(tier="canonical"),
            data_freshness=datetime(2026, 4, 25, tzinfo=timezone.utc),
            request_id="req_x",
        )
