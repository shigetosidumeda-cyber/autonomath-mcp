"""Tests for the token-efficient compact envelope projection.

Goal: confirm that ``api/_compact_envelope.to_compact`` (1) actually shrinks
the wire payload by 30-50% on a realistic Evidence Packet sample, (2) keeps
every value the customer LLM uses for inference recoverable via either the
returned compact form or the published reference tables, and (3) the
disclaimer reference id round-trips back to the full Japanese text.

No DB / network — pure-Python projection helpers under test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure src/ on path for direct test runs (mirrors test_disclaimer_envelope).
_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.api._compact_envelope import (  # noqa: E402
    DISCLAIMER_TABLE,
    KNOWN_GAPS_TABLE,
    from_compact,
    to_compact,
    wants_compact,
)

# ---------------------------------------------------------------------------
# Realistic full-envelope fixture (mirrors services.evidence_packet output).
# ---------------------------------------------------------------------------


def _full_program_envelope() -> dict:
    return {
        "packet_id": "pkt_8c3d7a4e9b1f4a2c8d5e6f7a8b9c0d1e",
        "generated_at": "2026-05-05T12:34:56+09:00",
        "api_version": "v1",
        "corpus_snapshot_id": "2026-05-05T07:21:33+09:00:abcd1234efgh5678",
        "answer_not_included": True,
        "query": {
            "user_intent": "detail:program:UNI-test-s-1",
            "normalized_filters": {},
        },
        "records": [
            {
                "record_kind": "program",
                "entity_id": "program:test:s1",
                "primary_name": "テスト S-tier 補助金",
                "source_url": "https://www.maff.go.jp/policy/test1.html",
                "facts": [
                    {
                        "field_name": "amount_max_yen",
                        "value": 50_000_000,
                        "source_id": 1,
                    }
                ],
                "rules": [],
                "aliases": ["テスト補助金", "S-tier"],
                "recent_changes": [],
            }
        ],
        "quality": {
            "freshness_bucket": "0-3d",
            "freshness_scope": "corpus_wide_max_not_record_level",
            "freshness_basis": "corpus_snapshot_id",
            "coverage_score": 0.78,
            "known_gaps": [
                "Per-fact provenance unavailable for 2 of 4 facts (source_id NULL on this entity).",
                "Citation verification stale (last live URL probe > 30 days).",
                "Result truncated at the 500-record cap; paginate via cursor.",
            ],
            "human_review_required": False,
            "known_gaps_inventory": {
                # Verbose inventory the compact form intentionally drops.
                "by_kind": {"provenance": 1, "verification": 1, "truncation": 1},
                "details": [
                    {"code": "EP1", "where": "facts[0]", "since": "2026-04-30"},
                    {"code": "EP2", "where": "citations[0]", "since": "2026-04-01"},
                ],
            },
        },
        "verification": {
            "replay_endpoint": "/v1/programs/UNI-test-s-1/evidence",
            "provenance_endpoint": "/v1/am/provenance/program:test:s1",
            "freshness_endpoint": "/v1/meta/freshness",
        },
        "_disclaimer": {
            "type": "information_only",
            "not_legal_or_tax_advice": True,
            "note": DISCLAIMER_TABLE["disc_evp_v1"],  # exact known text → maps to id
        },
        "_disclaimer_gbiz": "出典：「Gビズインフォ」（経済産業省）を加工して作成",
        "_attribution": {
            "source": "Gビズインフォ",
            "publisher": "経済産業省",
            "source_url": "https://info.gbiz.go.jp/hojin/v2/hojin/8010001213708",
            "license_url": "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
            "modification_notice": "編集・加工して作成",
            "fetched_via": "gBizINFO REST API v2",
            "snapshot_date": "2026-05-06T00:00:00+00:00",
            "upstream_source": "NTA Houjin Bangou Web-API",
        },
        "_audit_seal": {
            "seal_id": "seal_8c3d7a4e9b1f4a2c8d5e6f7a8b9c0d1e",
            "issued_at": "2026-05-05T12:34:56+00:00",
            "subject_hash": "sha256:" + ("a" * 64),
            "key_hash_prefix": "abc12345",
            "corpus_snapshot_id": "2026-05-05T07:21:33+09:00:abcd1234efgh5678",
            "verify_endpoint": "/v1/audit/seals/seal_8c3d7a4e9b1f4a2c8d5e6f7a8b9c0d1e",
            "_disclaimer": (
                "信頼できる出典として運用する場合は、verify_endpoint で seal の真正性を確認してください。"
            ),
            "call_id": "01HW2J3K4L5M6N7P8Q9R0S1T2V",
            "ts": "2026-05-05T12:34:56+00:00",
            "endpoint": "/v1/programs/UNI-test-s-1/evidence",
            "query_hash": "f" * 64,
            "response_hash": "e" * 64,
            "source_urls": [
                "https://www.maff.go.jp/policy/test1.html",
                "https://www.meti.go.jp/policy/test2.pdf",
            ],
            "hmac": "0123456789abcdef" * 4,
        },
        "_next_calls": [
            {"tool": "get_program", "args": {"unified_id": "UNI-test-s-1"}},
            {"tool": "trace_program_to_law", "args": {"unified_id": "UNI-test-s-1"}},
            {"tool": "find_cases_by_program", "args": {"program_id": "UNI-test-s-1"}},
            # Duplicate to confirm dedup.
            {"tool": "get_program", "args": {"unified_id": "UNI-test-s-1"}},
        ],
    }


def _byte_size(payload: dict) -> int:
    """Wire-byte estimate. UTF-8 + sort_keys + no whitespace mirrors what
    the FastAPI JSON encoder emits after `model_dump(mode='json',
    exclude_none=True)`."""
    return len(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_compact_smaller_than_default() -> None:
    """30-50% byte-reduction target on the realistic Evidence Packet sample."""
    full = _full_program_envelope()
    compact = to_compact(full)

    full_bytes = _byte_size(full)
    compact_bytes = _byte_size(compact)
    ratio = compact_bytes / full_bytes

    # The reduction MUST be at least 30% to clear the 30-50% target.
    assert ratio < 0.70, (
        f"compact envelope ratio {ratio:.2f} fails 30%+ savings target "
        f"(full={full_bytes}B compact={compact_bytes}B)"
    )
    # Anything < 0.20 likely means we dropped a load-bearing field — guard
    # against accidental over-stripping.
    assert ratio > 0.20, (
        f"compact envelope ratio {ratio:.2f} suspiciously small "
        f"(full={full_bytes}B compact={compact_bytes}B) — verify we didn't "
        "drop records / citations / status by mistake"
    )

    # Print the size-comparison sample required by the spec.
    sample = {
        "kind": "program",
        "full": full_bytes,
        "compact": compact_bytes,
        "ratio": round(ratio, 3),
    }
    print(sample)


def test_compact_round_trip() -> None:
    """`from_compact(to_compact(x))` recovers every value the agent reads.

    Lossy fields (audit_seal sub-fields beyond hmac, replay_endpoint URL,
    next_calls.args) are NOT required to round-trip — those are recovered
    via verify_endpoint / tool-schema introspection, per the design.
    """
    full = _full_program_envelope()
    compact = to_compact(full)
    expanded = from_compact(compact)

    # Required round-trip set: records, citations (none here), status copy,
    # disclaimer text, known_gaps text list, next-call tool names, seal hmac,
    # corpus_snapshot_id (in shortened form), warnings.
    assert expanded.get("records") == full["records"], "records mismatched on round-trip"

    # Disclaimer reference id resolves back to the original Japanese text.
    assert (
        expanded["_disclaimer"] == full["_disclaimer"]["note"]
    ), "disclaimer text not recovered from reference id"

    # known_gaps come back as the canonical reference-table text (NOT the
    # original verbose sentence — that's the lossy bit; the canonical text
    # is sufficient for an LLM to reason about the gap).
    gaps_back = expanded["quality"]["known_gaps"]
    assert isinstance(gaps_back, list) and gaps_back, "known_gaps list missing on round-trip"
    for g in gaps_back:
        assert isinstance(g, str) and g.strip(), "empty known_gap entry"
    # At least EP1 and EP7 must be in the expanded form (per fixture content).
    assert KNOWN_GAPS_TABLE["EP1"] in gaps_back
    assert KNOWN_GAPS_TABLE["EP7"] in gaps_back

    # Next-calls — tool names recovered, args left empty for caller to refill.
    nx_back = expanded["_next_calls"]
    tool_names = [c["tool"] for c in nx_back]
    assert "get_program" in tool_names
    assert "trace_program_to_law" in tool_names
    assert "find_cases_by_program" in tool_names
    # Dedup confirmed — `get_program` must appear exactly once.
    assert tool_names.count("get_program") == 1, "next_calls dedup failed on round-trip"

    # Seal HMAC preserved (the only field surviving the projection).
    assert expanded["_audit_seal"]["hmac"] == full["_audit_seal"]["hmac"]
    assert expanded["_disclaimer_gbiz"] == full["_disclaimer_gbiz"]
    assert expanded["_attribution"] == full["_attribution"]


def test_compact_disclaimer_id_resolves() -> None:
    """The published `DISCLAIMER_TABLE` lets a customer SDK look up the full
    Japanese text from the compact `_dx` reference id without ever holding
    the verbose payload."""
    # Every published id must resolve to a non-empty Japanese string.
    for ref_id, text in DISCLAIMER_TABLE.items():
        assert isinstance(ref_id, str) and ref_id.startswith(
            "disc_"
        ), f"disclaimer reference id {ref_id!r} doesn't follow `disc_*` convention"
        assert (
            isinstance(text, str) and len(text) >= 30
        ), f"disclaimer text for {ref_id!r} is suspiciously short (≤ 30 chars)"

    # End-to-end: full envelope → compact → expansion → original text.
    full = _full_program_envelope()
    compact = to_compact(full)

    # Confirm the disclaimer id present in the compact form is one of the
    # published ones (not silently passed-through verbatim text).
    assert compact["_dx"] in DISCLAIMER_TABLE, (
        f"compact `_dx`={compact['_dx']!r} is not in the published "
        f"DISCLAIMER_TABLE — a customer SDK couldn't resolve it"
    )

    # Resolution path that a thin customer SDK would use:
    resolved = DISCLAIMER_TABLE[compact["_dx"]]
    assert resolved == full["_disclaimer"]["note"], (
        "disclaimer reference table entry doesn't match the verbatim text "
        "in the full envelope — the customer SDK lookup would diverge"
    )


def test_wants_compact_query_and_header() -> None:
    """`wants_compact` accepts both `?compact=true` and `X-JPCite-Compact: 1`."""

    class _Req:
        def __init__(self, qp: dict[str, str], headers: dict[str, str]) -> None:
            self.query_params = qp
            self.headers = headers

    assert wants_compact(_Req({"compact": "true"}, {})) is True
    assert wants_compact(_Req({"compact": "1"}, {})) is True
    assert wants_compact(_Req({"compact": "yes"}, {})) is True
    assert wants_compact(_Req({}, {"x-jpcite-compact": "1"})) is True
    assert wants_compact(_Req({}, {})) is False
    assert wants_compact(_Req({"compact": "false"}, {})) is False
    # Soft-fail on garbage shape.
    assert wants_compact(None) is False
    assert wants_compact(object()) is False


def test_compact_envelope_sample_assertion() -> None:
    """Print + assert the size-comparison sample in the format the spec
    requires: `{kind: program, full: 1234 byte, compact: 543 byte, ratio: 0.44}`.
    """
    full = _full_program_envelope()
    compact = to_compact(full)

    full_bytes = _byte_size(full)
    compact_bytes = _byte_size(compact)
    ratio = round(compact_bytes / full_bytes, 3)
    sample = {"kind": "program", "full": full_bytes, "compact": compact_bytes, "ratio": ratio}
    print(sample)
    # Spec target: 30-50% smaller → ratio in (0.50, 0.70].
    assert ratio <= 0.70
