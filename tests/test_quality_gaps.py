from __future__ import annotations

from jpintel_mcp.services.quality_gaps import build_known_gaps


def _codes(gaps: list[dict]) -> set[str]:
    return {gap["code"] for gap in gaps}


def test_known_gaps_reports_missing_source_id_license_and_unverified_source() -> None:
    gaps = build_known_gaps(
        evidence=[
            {
                "source_url": "https://example.go.jp/program",
                "license": "unknown",
                "last_verified_at": None,
            }
        ],
        facts={
            "application_deadline": "2026-06-30",
            "amount_max_yen": 1_000_000,
            "contact_email": "desk@example.go.jp",
        },
        as_of="2026-05-01",
    )

    assert _codes(gaps) == {
        "missing_source_id",
        "license_unknown",
        "source_unverified",
    }
    assert gaps[0]["subject"] == "source"
    assert gaps[0]["source_url"] == "https://example.go.jp/program"


def test_known_gaps_reports_stale_and_blocked_license() -> None:
    gaps = build_known_gaps(
        evidence=[
            {
                "source_id": 10,
                "source_url": "https://example.go.jp/old",
                "license": "proprietary",
                "last_verified_at": "2025-01-01T10:00:00+09:00",
            }
        ],
        facts={
            "deadline": "2026-06-30",
            "amount": "100万円",
            "contact": "産業振興課",
        },
        as_of="2026-05-01",
        stale_after_days=180,
    )

    assert _codes(gaps) == {"license_blocked", "source_stale"}
    stale_gap = next(gap for gap in gaps if gap["code"] == "source_stale")
    assert stale_gap["source_id"] == 10
    assert stale_gap["last_verified_at"] == "2025-01-01"
    assert stale_gap["age_days"] == 485


def test_known_gaps_reports_fact_source_id_and_missing_required_fields() -> None:
    gaps = build_known_gaps(
        facts=[
            {
                "fact_id": 1,
                "field_name": "primary_name",
                "field_value_text": "Program A",
                "source_id": None,
            },
            {
                "fact_id": 2,
                "field_name": "amount_max_yen",
                "field_value_numeric": 500_000,
                "source_id": 7,
            },
        ],
        as_of="2026-05-01",
    )

    assert _codes(gaps) == {
        "missing_source_id",
        "missing_deadline",
        "missing_contact",
    }
    assert "missing_amount" not in _codes(gaps)
    source_gap = next(gap for gap in gaps if gap["code"] == "missing_source_id")
    assert source_gap["subject"] == "fact"
    assert source_gap["field_name"] == "primary_name"
    assert source_gap["record_ref"] == 1


def test_known_gaps_converts_conflict_metadata() -> None:
    gaps = build_known_gaps(
        facts={
            "application_deadline": "2026-06-30",
            "amount_max_yen": 1_000_000,
            "contact_email": "desk@example.go.jp",
        },
        conflict_metadata={
            "fields": [
                {
                    "field_name": "amount_max_yen",
                    "status": "conflict",
                    "distinct_value_count": 2,
                    "source_count": 2,
                    "values": [{"display_value": 100}, {"display_value": 200}],
                },
                {
                    "field_name": "target_industry",
                    "status": "multiple_values",
                    "distinct_value_count": 2,
                    "source_count": 1,
                },
                {
                    "field_name": "primary_name",
                    "status": "consistent",
                },
            ]
        },
        as_of="2026-05-01",
    )

    assert _codes(gaps) == {"conflict", "multiple_values"}
    conflict = next(gap for gap in gaps if gap["code"] == "conflict")
    multiple = next(gap for gap in gaps if gap["code"] == "multiple_values")
    assert conflict["severity"] == "high"
    assert conflict["field_name"] == "amount_max_yen"
    assert conflict["values"] == [{"display_value": 100}, {"display_value": 200}]
    assert multiple["severity"] == "medium"


def test_known_gaps_returns_empty_when_metadata_is_complete() -> None:
    gaps = build_known_gaps(
        evidence=[
            {
                "source_id": 1,
                "source_url": "https://example.go.jp/program",
                "license": "gov_standard",
                "last_verified_at": "2026-04-20",
            }
        ],
        facts=[
            {
                "field_name": "application_deadline",
                "field_value_text": "2026-06-30",
                "source_id": 1,
            },
            {
                "field_name": "amount_max_yen",
                "field_value_numeric": 1_000_000,
                "source_id": 1,
            },
            {
                "field_name": "contact_email",
                "field_value_text": "desk@example.go.jp",
                "source_id": 1,
            },
        ],
        conflict_metadata={"fields": [{"field_name": "primary_name", "status": "consistent"}]},
        as_of="2026-05-01",
    )

    assert gaps == []
