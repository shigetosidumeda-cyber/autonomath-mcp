"""Tests for `api/_field_filter.py` partial-response projection.

The helper backs the `?fields_partial=` query parameter on
`/v1/programs/search`, `/v1/programs/{id}`, `/v1/laws/search`, and
`/v1/evidence/packets/program/{id}`. These tests pin the three invariants
the customer-facing contract depends on:

1.  Selected fields come back; unselected top-level fields disappear.
2.  Protected envelope fields (`_disclaimer`, `_attribution`,
    `corpus_snapshot_id`, `corpus_checksum`, `audit_seal`, `_billing_unit`) MUST stay
    present even when the caller does not list them — they carry the
    legal-responsibility envelope.
3.  Unknown / typo'd field tokens are silently ignored, never raise.
"""

from __future__ import annotations

from jpintel_mcp.api._field_filter import (
    PROTECTED_FIELDS,
    apply_fields_filter,
)


def _sample_envelope() -> dict[str, object]:
    """Realistic-shape envelope mirroring /v1/programs/search response."""
    return {
        "total": 2,
        "limit": 20,
        "offset": 0,
        "results": [
            {
                "unified_id": "UNI-test-1",
                "primary_name": "テスト 補助金 1",
                "tier": "A",
                "authority_level": "national",
                "prefecture": "東京都",
                "amount_max_man_yen": 100.0,
                "source_url": "https://example.go.jp/1",
            },
            {
                "unified_id": "UNI-test-2",
                "primary_name": "テスト 補助金 2",
                "tier": "B",
                "authority_level": "prefecture",
                "prefecture": "大阪府",
                "amount_max_man_yen": 50.0,
                "source_url": "https://example.go.jp/2",
            },
        ],
        # Protected envelope keys — the legal / audit / billing wrapper.
        "_disclaimer": "本データは参考情報です。最終判断は専門家にご相談ください。",
        "_disclaimer_gbiz": "出典：「Gビズインフォ」（経済産業省）を加工して作成",
        "_attribution": {
            "source": "Gビズインフォ",
            "publisher": "経済産業省",
            "license_url": "https://help.info.gbiz.go.jp/hc/ja/articles/4795140981406",
        },
        "corpus_snapshot_id": "2026-05-01T00:00:00Z",
        "corpus_checksum": "abc123def456",
        "audit_seal": {
            "call_id": "call-001",
            "sha256": "deadbeef",
        },
        "_billing_unit": 1,
    }


# --------------------------------------------------------------------------
# Test 1 — only requested top-level fields come back (plus protected).
# --------------------------------------------------------------------------


def test_filter_returns_only_requested_fields() -> None:
    env = _sample_envelope()
    out = apply_fields_filter(env, "total,results")

    # Selected fields present.
    assert "total" in out
    assert "results" in out
    assert out["total"] == 2
    assert isinstance(out["results"], list)
    assert len(out["results"]) == 2

    # Unselected top-level fields removed.
    assert "limit" not in out
    assert "offset" not in out

    # Protected fields still present (test 2 covers this in detail).
    assert "_disclaimer" in out
    assert "corpus_snapshot_id" in out

    # Input envelope was NOT mutated.
    assert "limit" in env
    assert "offset" in env


def test_filter_dotted_path_projects_list_items() -> None:
    """`results.unified_id,results.primary_name` keeps only those keys per row."""
    env = _sample_envelope()
    out = apply_fields_filter(env, "results.unified_id,results.primary_name")

    assert "results" in out
    rows = out["results"]
    assert isinstance(rows, list)
    assert len(rows) == 2
    for row in rows:
        assert isinstance(row, dict)
        assert set(row.keys()) == {"unified_id", "primary_name"}

    # `total` was not selected so it's dropped from the top level.
    assert "total" not in out
    # Protected envelope keys still survive.
    assert "_disclaimer" in out
    assert "audit_seal" in out


# --------------------------------------------------------------------------
# Test 2 — protected fields are always included (legal envelope guard).
# --------------------------------------------------------------------------


def test_protected_fields_always_included() -> None:
    env = _sample_envelope()
    # Caller asks for ONLY `unified_id` (deliberately narrow). Protected
    # fields must still appear because they form the legal-responsibility
    # envelope (景表法 / 消費者契約法 / Stripe metered audit / 会計士
    # reproducibility) that the customer agent relays downstream.
    out = apply_fields_filter(env, "results")

    for protected_key in (
        "_disclaimer",
        "_disclaimer_gbiz",
        "_attribution",
        "corpus_snapshot_id",
        "corpus_checksum",
        "audit_seal",
        "_billing_unit",
    ):
        assert (
            protected_key in out
        ), f"protected key {protected_key!r} must survive partial projection"

    # Confirm the protected set in the helper's source matches the one
    # the test pins — the helper is the single source of truth.
    for k in (
        "_disclaimer",
        "_disclaimer_gbiz",
        "_attribution",
        "corpus_snapshot_id",
        "corpus_checksum",
        "audit_seal",
        "_billing_unit",
    ):
        assert k in PROTECTED_FIELDS

    # Even an empty-token projection returns protected fields. (The
    # implementation short-circuits empty selectors to the full deepcopy.)
    out_empty = apply_fields_filter(env, "")
    for k in PROTECTED_FIELDS:
        if k in env:
            assert k in out_empty


def test_protected_fields_kept_even_when_caller_requests_one_unrelated_field() -> None:
    """Caller asks for one ordinary field — protected envelope still flows."""
    env = _sample_envelope()
    out = apply_fields_filter(env, "limit")
    assert "limit" in out
    assert "total" not in out  # not requested
    assert "_disclaimer" in out
    assert "_attribution" in out
    assert "corpus_snapshot_id" in out
    assert "audit_seal" in out


# --------------------------------------------------------------------------
# Test 3 — unknown / malformed field tokens ignored, no exception.
# --------------------------------------------------------------------------


def test_invalid_field_ignored_not_error() -> None:
    env = _sample_envelope()
    # Mix of: real key, typo'd key, dotted-with-empty-half, only-comma.
    out = apply_fields_filter(
        env,
        "total,does_not_exist,results.unified_id,results.,.bad,,,,",
    )
    # Real fields still present.
    assert out["total"] == 2
    rows = out["results"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        assert "unified_id" in row
    # Unknown top-level key silently ignored — does NOT appear.
    assert "does_not_exist" not in out
    # Protected envelope intact.
    assert "_disclaimer" in out


def test_filter_with_none_returns_full_envelope_unchanged() -> None:
    env = _sample_envelope()
    out = apply_fields_filter(env, None)
    # Same shape as input (deepcopy — same content, different object).
    assert out == env
    assert out is not env


def test_filter_non_dict_input_returns_unchanged() -> None:
    # Defensive: helper must not crash on non-dict inputs.
    assert apply_fields_filter([1, 2, 3], "id") == [1, 2, 3]  # type: ignore[arg-type]
    assert apply_fields_filter("hello", "id") == "hello"  # type: ignore[arg-type]
    assert apply_fields_filter(None, "id") is None  # type: ignore[arg-type]
