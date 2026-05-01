"""Tests for ``services.known_gaps.detect_gaps``.

Each test feeds a packet of a different shape and asserts that the
expected ``kind`` is present (and that unrelated kinds are absent so
we don't drift into false positives).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jpintel_mcp.services.known_gaps import (
    LOW_CONFIDENCE_THRESHOLD,
    STALE_THRESHOLD_DAYS,
    detect_gaps,
)


def _kinds(report: list[dict[str, Any]]) -> set[str]:
    return {entry["kind"] for entry in report}


def _by_kind(report: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    for entry in report:
        if entry["kind"] == kind:
            return entry
    raise AssertionError(f"kind {kind!r} not found in report: {report}")


# 1. structured_miss → not_found_in_local_mirror
def test_structured_miss_emits_not_found_in_local_mirror() -> None:
    packet = {
        "records": [
            {
                "entity_id": "structured_miss:enforcement:T1234567890123",
                "primary_name": "法人番号 1234567890123 行政処分ローカル照合",
                "record_kind": "structured_miss",
                "source_url": "https://example.go.jp/check",
                "lookup": {
                    "kind": "enforcement_by_houjin_bangou",
                    "houjin_bangou": "1234567890123",
                    "status": "not_found_in_local_mirror",
                    "checked_tables": ["am_enforcement_detail"],
                    "official_absence_proven": False,
                },
            }
        ],
    }
    report = detect_gaps(packet)
    assert "not_found_in_local_mirror" in _kinds(report)
    entry = _by_kind(report, "not_found_in_local_mirror")
    assert entry["affected_records"] == [
        "structured_miss:enforcement:T1234567890123"
    ]
    assert "ローカルミラー" in entry["message"]


# 2. lookup.status == 'unknown' → lookup_status_unknown
def test_lookup_status_unknown_emits_lookup_status_unknown() -> None:
    # Use a non-structured_miss record so we isolate the lookup-status
    # signal from the record_kind signal.
    packet = {
        "records": [
            {
                "entity_id": "houjin:T9999999999999",
                "primary_name": "T9999999999999 法人検索",
                "record_kind": "houjin",
                "source_url": "https://www.houjin-bangou.nta.go.jp/",
                "lookup": {
                    "kind": "invoice_registration_number",
                    "status": "unknown",
                    "checked_tables": [],
                },
            }
        ],
    }
    report = detect_gaps(packet)
    kinds = _kinds(report)
    assert "lookup_status_unknown" in kinds
    # status='unknown' should NOT trigger not_found_in_local_mirror
    # (that signal is reserved for explicit not_found / structured_miss).
    assert "not_found_in_local_mirror" not in kinds


# 3. houjin_bangou unverified
def test_houjin_bangou_on_non_verifying_kind_emits_houjin_bangou_unverified() -> None:
    packet = {
        "records": [
            {
                "entity_id": "law:tokuteishouhou:1",
                "primary_name": "特定商取引法 第14条",
                "record_kind": "law",
                "source_url": "https://elaws.e-gov.go.jp/document?lawid=123",
                "houjin_bangou": "8010001213708",
            }
        ],
    }
    report = detect_gaps(packet)
    assert "houjin_bangou_unverified" in _kinds(report)


def test_houjin_bangou_on_invoice_registrant_does_not_flag() -> None:
    packet = {
        "records": [
            {
                "entity_id": "T8010001213708",
                "primary_name": "Bookyou株式会社",
                "record_kind": "invoice_registrant",
                "source_url": "https://www.invoice-kohyo.nta.go.jp/regno/T8010001213708",
                "houjin_bangou": "8010001213708",
            }
        ],
    }
    report = detect_gaps(packet)
    assert "houjin_bangou_unverified" not in _kinds(report)


# 4. source_url quality (NULL / non-HTTPS / HTTP)
def test_source_url_quality_fires_on_null_and_http_only() -> None:
    packet = {
        "records": [
            {
                "entity_id": "rec-1",
                "record_kind": "program",
                "source_url": None,  # NULL
            },
            {
                "entity_id": "rec-2",
                "record_kind": "program",
                "source_url": "http://www.example.go.jp/legacy.html",  # HTTP
            },
            {
                "entity_id": "rec-3",
                "record_kind": "program",
                "source_url": "https://www.example.go.jp/ok.html",  # HTTPS — fine
            },
        ]
    }
    report = detect_gaps(packet)
    entry = _by_kind(report, "source_url_quality")
    assert set(entry["affected_records"]) == {"rec-1", "rec-2"}
    assert "rec-3" not in entry["affected_records"]


# 5. source_stale (>90d)
def test_source_stale_fires_on_old_last_verified() -> None:
    old_iso = (datetime.now(UTC) - timedelta(days=STALE_THRESHOLD_DAYS + 5)).isoformat()
    fresh_iso = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    packet = {
        "records": [
            {
                "entity_id": "rec-stale",
                "record_kind": "program",
                "source_url": "https://example.go.jp/old",
                "last_verified": old_iso,
            },
            {
                "entity_id": "rec-fresh",
                "record_kind": "program",
                "source_url": "https://example.go.jp/new",
                "last_verified": fresh_iso,
            },
        ]
    }
    report = detect_gaps(packet)
    entry = _by_kind(report, "source_stale")
    assert entry["affected_records"] == ["rec-stale"]


# 6. low confidence (record-level OR fact-level)
def test_low_confidence_fires_on_record_and_fact_level() -> None:
    low = LOW_CONFIDENCE_THRESHOLD - 0.1
    high = 0.95
    packet = {
        "records": [
            {
                "entity_id": "rec-low-rec",
                "record_kind": "program",
                "source_url": "https://example.go.jp/p",
                "confidence": low,
            },
            {
                "entity_id": "rec-low-fact",
                "record_kind": "program",
                "source_url": "https://example.go.jp/p2",
                "confidence": high,
                "facts": [
                    {"field": "amount_max_yen", "value": 1, "confidence": low},
                ],
            },
            {
                "entity_id": "rec-clean",
                "record_kind": "program",
                "source_url": "https://example.go.jp/p3",
                "confidence": high,
                "facts": [
                    {"field": "amount_max_yen", "value": 1, "confidence": high},
                ],
            },
        ]
    }
    report = detect_gaps(packet)
    entry = _by_kind(report, "low_confidence")
    assert set(entry["affected_records"]) == {"rec-low-rec", "rec-low-fact"}


# Hygiene
def test_empty_packet_yields_empty_report() -> None:
    assert detect_gaps({}) == []
    assert detect_gaps({"records": []}) == []


def test_clean_packet_yields_empty_report() -> None:
    fresh_iso = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    packet = {
        "records": [
            {
                "entity_id": "rec-ok",
                "record_kind": "program",
                "source_url": "https://example.go.jp/ok",
                "last_verified": fresh_iso,
                "confidence": 0.92,
                "facts": [
                    {"field": "amount_max_yen", "value": 1, "confidence": 0.9}
                ],
            }
        ]
    }
    assert detect_gaps(packet) == []


def test_malformed_input_does_not_raise() -> None:
    assert detect_gaps(None) == []  # type: ignore[arg-type]
    assert detect_gaps("not a dict") == []  # type: ignore[arg-type]
    assert detect_gaps({"records": "not a list"}) == []
    assert detect_gaps({"records": [None, 1, "two"]}) == []  # type: ignore[list-item]


@pytest.mark.parametrize(
    "url,thin",
    [
        (None, True),
        ("", True),
        ("see brochure", True),
        ("ftp://example.com/file", True),
        ("http://example.com/legacy", True),
        ("https://example.com/ok", False),
        ("HTTPS://EXAMPLE.GO.JP/UPPER", False),
    ],
)
def test_source_url_quality_classifier(url: object, thin: bool) -> None:
    packet = {"records": [{"entity_id": "x", "source_url": url}]}
    report = detect_gaps(packet)
    has_gap = "source_url_quality" in _kinds(report)
    assert has_gap is thin


def test_compose_evidence_packet_attaches_inventory() -> None:
    """End-to-end smoke: ``_attach_known_gaps_inventory`` runs from the composer."""
    from jpintel_mcp.services.evidence_packet import (
        _attach_known_gaps_inventory,
    )

    envelope: dict[str, Any] = {
        "records": [
            {
                "entity_id": "smoke-rec",
                "record_kind": "structured_miss",
                "source_url": None,
                "lookup": {"status": "not_found_in_local_mirror"},
            }
        ],
        "quality": {"known_gaps": []},
    }
    _attach_known_gaps_inventory(envelope)
    inventory = envelope["quality"]["known_gaps_inventory"]
    kinds = {entry["kind"] for entry in inventory}
    assert "not_found_in_local_mirror" in kinds
    assert "source_url_quality" in kinds
