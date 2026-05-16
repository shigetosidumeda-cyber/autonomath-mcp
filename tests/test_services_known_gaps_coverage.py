"""Coverage tests for ``src/jpintel_mcp/services/known_gaps.py``.

This is the packet-level gap detector (A8). Targets the closed set of
detector kinds:

- ``not_found_in_local_mirror`` (via structured_miss kind + via lookup.status)
- ``lookup_status_unknown``
- ``houjin_bangou_unverified``
- ``source_url_quality`` (NULL / non-URL / HTTP-only)
- ``source_stale``
- ``low_confidence`` (record-level + facts-level)

Plus the shape-guard / dedup / output ordering paths.

No DB, no LLM — pure dict→list transform.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jpintel_mcp.services.known_gaps import (
    LOW_CONFIDENCE_THRESHOLD,
    STALE_THRESHOLD_DAYS,
    detect_gaps,
)


def _stale_ts() -> str:
    return (datetime.now(UTC) - timedelta(days=STALE_THRESHOLD_DAYS + 1)).isoformat()


def _fresh_ts() -> str:
    return (datetime.now(UTC) - timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Input shape guards
# ---------------------------------------------------------------------------


def test_detect_gaps_returns_empty_for_non_dict() -> None:
    assert detect_gaps("not a dict") == []  # type: ignore[arg-type]
    assert detect_gaps(None) == []  # type: ignore[arg-type]
    assert detect_gaps(42) == []  # type: ignore[arg-type]


def test_detect_gaps_returns_empty_when_records_missing() -> None:
    assert detect_gaps({}) == []
    assert detect_gaps({"records": None}) == []
    assert detect_gaps({"records": "not a list"}) == []


def test_detect_gaps_skips_non_dict_records() -> None:
    out = detect_gaps(
        {
            "records": [
                "x",
                1,
                None,
                {
                    "record_kind": "structured_miss",
                    "source_url": "https://x",
                    "entity_id": "ent-skip",
                },
            ]
        }
    )
    kinds = {g["kind"] for g in out}
    assert kinds == {"not_found_in_local_mirror"}


# ---------------------------------------------------------------------------
# not_found_in_local_mirror — via structured_miss + via lookup.status
# ---------------------------------------------------------------------------


def test_detect_gaps_structured_miss_emits_not_found_kind() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "ent-1",
                    "record_kind": "structured_miss",
                    "source_url": "https://x",
                },
            ]
        }
    )
    kinds = [g["kind"] for g in out]
    assert kinds == ["not_found_in_local_mirror"]
    assert out[0]["affected_records"] == ["ent-1"]
    assert "ローカルミラー" in out[0]["message"]


def test_detect_gaps_lookup_not_found_status_emits_not_found() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "ent-2",
                    "lookup": {"status": "not_found_in_local_mirror"},
                }
            ]
        }
    )
    assert out[0]["kind"] == "not_found_in_local_mirror"
    assert out[0]["affected_records"] == ["ent-2"]


def test_detect_gaps_lookup_unknown_status_emits_unknown_kind() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "ent-3",
                    "source_url": "https://x",
                    "lookup": {"status": "unknown"},
                },
                {
                    "entity_id": "ent-4",
                    "source_url": "https://x",
                    "lookup": {"status": "mirror_unavailable"},
                },
            ]
        }
    )
    kinds = {g["kind"] for g in out}
    assert kinds == {"lookup_status_unknown"}
    affected = [g for g in out if g["kind"] == "lookup_status_unknown"][0]["affected_records"]
    assert "ent-3" in affected and "ent-4" in affected


def test_detect_gaps_lookup_status_arbitrary_is_ignored() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "ent-x",
                    "source_url": "https://x",
                    "lookup": {"status": "completed"},
                }
            ]
        }
    )
    # "completed" is not in either status set → no gap emitted.
    assert all(g["kind"] != "lookup_status_unknown" for g in out)
    assert all(g["kind"] != "not_found_in_local_mirror" for g in out)


# ---------------------------------------------------------------------------
# houjin_bangou_unverified
# ---------------------------------------------------------------------------


def test_detect_gaps_houjin_unverified_kind_when_not_verifier() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "ent-5",
                    "record_kind": "case_study",
                    "houjin_bangou": "1234567890123",
                }
            ]
        }
    )
    assert out[0]["kind"] == "houjin_bangou_unverified"


def test_detect_gaps_invoice_registrant_does_not_emit_houjin_gap() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "ent-6",
                    "record_kind": "invoice_registrant",
                    "source_url": "https://x",
                    "houjin_bangou": "1234567890123",
                }
            ]
        }
    )
    # invoice_registrant IS a verifier — no houjin_bangou_unverified gap.
    assert all(g["kind"] != "houjin_bangou_unverified" for g in out)


def test_detect_gaps_houjin_blank_value_skips_gap() -> None:
    out = detect_gaps(
        {"records": [{"entity_id": "ent-7", "record_kind": "x", "houjin_bangou": "  "}]}
    )
    assert all(g["kind"] != "houjin_bangou_unverified" for g in out)


# ---------------------------------------------------------------------------
# source_url_quality
# ---------------------------------------------------------------------------


def test_detect_gaps_source_url_null_flags_thin() -> None:
    out = detect_gaps({"records": [{"entity_id": "e1", "source_url": None}]})
    assert out[0]["kind"] == "source_url_quality"


def test_detect_gaps_source_url_http_only_flags_thin() -> None:
    out = detect_gaps({"records": [{"entity_id": "e2", "source_url": "http://example.com"}]})
    assert out[0]["kind"] == "source_url_quality"


def test_detect_gaps_source_url_not_url_flags_thin() -> None:
    out = detect_gaps({"records": [{"entity_id": "e3", "source_url": "see brochure"}]})
    assert out[0]["kind"] == "source_url_quality"


def test_detect_gaps_source_url_https_does_not_flag() -> None:
    out = detect_gaps({"records": [{"entity_id": "e4", "source_url": "https://nta.go.jp/x"}]})
    assert all(g["kind"] != "source_url_quality" for g in out)


# ---------------------------------------------------------------------------
# source_stale
# ---------------------------------------------------------------------------


def test_detect_gaps_source_stale_when_ts_older_than_threshold() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e5",
                    "source_url": "https://x",
                    "last_verified": _stale_ts(),
                }
            ]
        }
    )
    assert out[0]["kind"] == "source_stale"


def test_detect_gaps_fresh_ts_does_not_flag_stale() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e6",
                    "source_url": "https://x",
                    "last_verified": _fresh_ts(),
                }
            ]
        }
    )
    assert all(g["kind"] != "source_stale" for g in out)


def test_detect_gaps_missing_ts_does_not_flag_stale() -> None:
    out = detect_gaps({"records": [{"entity_id": "e7", "source_url": "https://x"}]})
    assert all(g["kind"] != "source_stale" for g in out)


def test_detect_gaps_stale_accepts_iso_date_shorthand() -> None:
    yyyy_mm_dd = (datetime.now(UTC) - timedelta(days=STALE_THRESHOLD_DAYS + 5)).date().isoformat()
    out = detect_gaps(
        {"records": [{"entity_id": "e8", "source_url": "https://x", "fetched_at": yyyy_mm_dd}]}
    )
    assert out[0]["kind"] == "source_stale"


def test_detect_gaps_stale_handles_z_suffix() -> None:
    ts = (datetime.now(UTC) - timedelta(days=STALE_THRESHOLD_DAYS + 1)).isoformat().replace(
        "+00:00", ""
    ) + "Z"
    out = detect_gaps(
        {"records": [{"entity_id": "e9", "source_url": "https://x", "source_fetched_at": ts}]}
    )
    assert out[0]["kind"] == "source_stale"


def test_detect_gaps_stale_handles_unparseable_ts() -> None:
    out = detect_gaps(
        {"records": [{"entity_id": "e10", "source_url": "https://x", "fetched_at": "not a date"}]}
    )
    assert all(g["kind"] != "source_stale" for g in out)


# ---------------------------------------------------------------------------
# low_confidence
# ---------------------------------------------------------------------------


def test_detect_gaps_low_confidence_record_level() -> None:
    low = LOW_CONFIDENCE_THRESHOLD - 0.01
    out = detect_gaps(
        {"records": [{"entity_id": "e11", "source_url": "https://x", "confidence": low}]}
    )
    assert any(g["kind"] == "low_confidence" for g in out)


def test_detect_gaps_low_confidence_fact_level() -> None:
    low = LOW_CONFIDENCE_THRESHOLD - 0.01
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e12",
                    "source_url": "https://x",
                    "facts": [{"confidence": low}],
                }
            ]
        }
    )
    assert any(g["kind"] == "low_confidence" for g in out)


def test_detect_gaps_high_confidence_does_not_flag() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e13",
                    "source_url": "https://x",
                    "confidence": 0.9,
                    "facts": [{"confidence": 0.95}],
                }
            ]
        }
    )
    assert all(g["kind"] != "low_confidence" for g in out)


def test_detect_gaps_bool_confidence_is_rejected() -> None:
    # bool is int subclass; the helper explicitly rejects it so True/False
    # does not collapse to 1.0 / 0.0.
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e14",
                    "source_url": "https://x",
                    "confidence": False,
                }
            ]
        }
    )
    assert all(g["kind"] != "low_confidence" for g in out)


def test_detect_gaps_unparseable_confidence_does_not_crash() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e15",
                    "source_url": "https://x",
                    "confidence": "not a number",
                }
            ]
        }
    )
    # No low_confidence flag — value simply ignored.
    assert all(g["kind"] != "low_confidence" for g in out)


def test_detect_gaps_facts_non_list_is_ignored() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e16",
                    "source_url": "https://x",
                    "facts": "not a list",
                }
            ]
        }
    )
    assert all(g["kind"] != "low_confidence" for g in out)


def test_detect_gaps_facts_with_non_dict_entries_are_skipped() -> None:
    low = LOW_CONFIDENCE_THRESHOLD - 0.01
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e17",
                    "source_url": "https://x",
                    "facts": ["str", None, {"confidence": low}],
                }
            ]
        }
    )
    assert any(g["kind"] == "low_confidence" for g in out)


# ---------------------------------------------------------------------------
# Aggregation / dedup / ordering
# ---------------------------------------------------------------------------


def test_detect_gaps_dedups_same_entity_within_same_kind() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "shared",
                    "record_kind": "structured_miss",
                    "source_url": "https://x",
                },
                {
                    "entity_id": "shared",
                    "record_kind": "structured_miss",
                    "source_url": "https://x",
                },
            ]
        }
    )
    not_found = [g for g in out if g["kind"] == "not_found_in_local_mirror"]
    assert len(not_found) == 1
    assert not_found[0]["affected_records"] == ["shared"]


def test_detect_gaps_returns_stable_closed_enum_ordering() -> None:
    out = detect_gaps(
        {
            "records": [
                {
                    "entity_id": "e-low",
                    "source_url": "https://x",
                    "confidence": 0.1,
                },
                {
                    "entity_id": "e-miss",
                    "record_kind": "structured_miss",
                },
                {
                    "entity_id": "e-thin",
                    "source_url": None,
                },
            ]
        }
    )
    kinds = [g["kind"] for g in out]
    # _KIND_MESSAGES ordering: not_found_in_local_mirror, lookup_status_unknown,
    # houjin_bangou_unverified, source_url_quality, source_stale, low_confidence.
    assert kinds.index("not_found_in_local_mirror") < kinds.index("source_url_quality")
    assert kinds.index("source_url_quality") < kinds.index("low_confidence")


def test_detect_gaps_envelope_level_entity_id_omitted_when_blank() -> None:
    # entity_id blank / None → affected_records list stays empty for that signal.
    out = detect_gaps(
        {
            "records": [
                {"record_kind": "structured_miss"},
                {"entity_id": "", "lookup": {"status": "unknown"}},
            ]
        }
    )
    by_kind = {g["kind"]: g for g in out}
    assert by_kind["not_found_in_local_mirror"]["affected_records"] == []
    assert by_kind["lookup_status_unknown"]["affected_records"] == []


def test_detect_gaps_entity_id_whitespace_only_treated_as_blank() -> None:
    out = detect_gaps({"records": [{"entity_id": "   ", "record_kind": "structured_miss"}]})
    assert out[0]["affected_records"] == []


@pytest.mark.parametrize(
    "url, flagged",
    [
        ("https://example.com", False),
        ("http://example.com", True),
        ("ftp://example.com", True),
        ("", True),
        ("ramdom text", True),
    ],
)
def test_source_url_thinness_parametric(url: str, flagged: bool) -> None:
    out = detect_gaps({"records": [{"entity_id": f"u-{url}", "source_url": url}]})
    has_flag = any(g["kind"] == "source_url_quality" for g in out)
    assert has_flag is flagged
