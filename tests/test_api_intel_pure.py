"""Pure-function coverage tests for ``api.intel`` private helpers.

Targets ``src/jpintel_mcp/api/intel.py`` (1,805 stmt). Covers the
non-DB helpers: 法人番号 normaliser + validator, Merkle proof verifier,
matchmaking score builder, eligibility predicate dict builder, document
readiness summary, and gap/question constructors.

NO DB / HTTP / LLM calls. Pure function I/O.

Stream CC tick (coverage 76% → 80% target).
"""

from __future__ import annotations

import hashlib
from typing import Any

import jpintel_mcp.api.intel as i

# ---------------------------------------------------------------------------
# _normalize_houjin / _is_valid_houjin
# ---------------------------------------------------------------------------


def test_normalize_houjin_strips_whitespace_and_t_prefix() -> None:
    assert i._normalize_houjin(" T8010001213708 ") == "8010001213708"


def test_normalize_houjin_lowercase_t_also_works() -> None:
    # upper() folds first; t-prefix variants must also fold.
    assert i._normalize_houjin("t8010001213708") == "8010001213708"


def test_normalize_houjin_no_prefix_passthrough() -> None:
    assert i._normalize_houjin("8010001213708") == "8010001213708"


def test_normalize_houjin_none_or_empty_returns_empty() -> None:
    assert i._normalize_houjin(None) == ""
    assert i._normalize_houjin("") == ""


def test_is_valid_houjin_13_digits_passes() -> None:
    assert i._is_valid_houjin("8010001213708") is True


def test_is_valid_houjin_short_fails() -> None:
    assert i._is_valid_houjin("12345") is False


def test_is_valid_houjin_with_letters_fails() -> None:
    assert i._is_valid_houjin("A010001213708") is False


def test_is_valid_houjin_14_digits_fails() -> None:
    assert i._is_valid_houjin("80100012137081") is False


# ---------------------------------------------------------------------------
# _verify_proof_path
# ---------------------------------------------------------------------------


def _h(x: bytes) -> str:
    return hashlib.sha256(x).hexdigest()


def test_verify_proof_path_empty_inputs_return_false() -> None:
    assert i._verify_proof_path("", [], "abc") is False
    assert i._verify_proof_path("abc", [], "") is False


def test_verify_proof_path_single_left_sibling_correct() -> None:
    leaf = hashlib.sha256(b"L").hexdigest()
    sibling = hashlib.sha256(b"S").hexdigest()
    # 'left' means sibling || leaf
    expected = _h(bytes.fromhex(sibling) + bytes.fromhex(leaf))
    assert i._verify_proof_path(leaf, [{"position": "left", "hash": sibling}], expected) is True


def test_verify_proof_path_single_right_sibling_correct() -> None:
    leaf = hashlib.sha256(b"L").hexdigest()
    sibling = hashlib.sha256(b"S").hexdigest()
    expected = _h(bytes.fromhex(leaf) + bytes.fromhex(sibling))
    assert i._verify_proof_path(leaf, [{"position": "right", "hash": sibling}], expected) is True


def test_verify_proof_path_unknown_position_returns_false() -> None:
    leaf = hashlib.sha256(b"L").hexdigest()
    sibling = hashlib.sha256(b"S").hexdigest()
    assert i._verify_proof_path(leaf, [{"position": "diagonal", "hash": sibling}], "ff") is False


def test_verify_proof_path_non_hex_returns_false() -> None:
    leaf = hashlib.sha256(b"L").hexdigest()
    out = i._verify_proof_path(leaf, [{"position": "left", "hash": "not-hex!!"}], "00")
    assert out is False


def test_verify_proof_path_mismatch_returns_false() -> None:
    leaf = hashlib.sha256(b"L").hexdigest()
    sibling = hashlib.sha256(b"S").hexdigest()
    assert i._verify_proof_path(leaf, [{"position": "left", "hash": sibling}], "00" * 32) is False


# ---------------------------------------------------------------------------
# _capital_fit_bonus
# ---------------------------------------------------------------------------


def test_capital_fit_bonus_none_inputs_zero() -> None:
    assert i._capital_fit_bonus(None, 1000) == 0.0
    assert i._capital_fit_bonus(1000, None) == 0.0


def test_capital_fit_bonus_right_sized_zone() -> None:
    # amount_max_man_yen=1000 -> 10_000_000 yen vs capital 100M -> ratio=0.1
    out = i._capital_fit_bonus(100_000_000, 1000)
    assert out == 0.3


def test_capital_fit_bonus_undersized_returns_small() -> None:
    # 1_000 man_yen = 10M yen vs capital 100B -> ratio 0.0001
    out = i._capital_fit_bonus(100_000_000_000, 1_000)
    assert out == 0.05


def test_capital_fit_bonus_oversized() -> None:
    # 1000 man_yen = 10M yen vs capital 1M -> ratio 10 -> oversized
    out = i._capital_fit_bonus(1_000_000, 1_000)
    assert out == 0.1


def test_capital_fit_bonus_zero_capital_returns_zero() -> None:
    assert i._capital_fit_bonus(0, 1000) == 0.0


# ---------------------------------------------------------------------------
# _compute_match_score / _normalize_match_score
# ---------------------------------------------------------------------------


def test_compute_match_score_tier_weight_dominates() -> None:
    s_high = i._compute_match_score(
        tier="S",
        verification_count=0,
        density=0,
        keyword=None,
        primary_name="X",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    s_low = i._compute_match_score(
        tier="C",
        verification_count=0,
        density=0,
        keyword=None,
        primary_name="X",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    assert s_high > s_low


def test_compute_match_score_keyword_match_adds_bonus() -> None:
    with_kw = i._compute_match_score(
        tier="A",
        verification_count=0,
        density=0,
        keyword="DX",
        primary_name="DX 補助金",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    without_kw = i._compute_match_score(
        tier="A",
        verification_count=0,
        density=0,
        keyword="DX",
        primary_name="まったく違う",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    assert with_kw > without_kw


def test_compute_match_score_unknown_tier_uses_baseline() -> None:
    out = i._compute_match_score(
        tier=None,
        verification_count=0,
        density=0,
        keyword=None,
        primary_name="X",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    assert out == 0.5


def test_normalize_match_score_zero_max_returns_zero() -> None:
    assert i._normalize_match_score(1.0, 0.0) == 0.0


def test_normalize_match_score_clamps_to_unit_interval() -> None:
    assert i._normalize_match_score(5.0, 2.0) == 1.0
    assert i._normalize_match_score(-3.0, 2.0) == 0.0
    assert i._normalize_match_score(1.0, 2.0) == 0.5


# ---------------------------------------------------------------------------
# _eligibility_predicate
# ---------------------------------------------------------------------------


def test_eligibility_predicate_uses_json_blob_fields() -> None:
    row: dict[str, Any] = {
        "target_types_json": '["sme","startup"]',
        "funding_purpose_json": '["DX","設備"]',
        "application_window_json": '{"start_date":"2026-01-01"}',
        "prefecture": "東京都",
        "jsic_majors": '["E"]',
        "jsic_major": None,
        "amount_max_man_yen": 1000,
        "amount_min_man_yen": 100,
        "subsidy_rate": "2/3",
    }
    out = i._eligibility_predicate(row)
    assert out["target_types"] == ["sme", "startup"]
    assert out["industry_jsic_majors"] == ["E"]
    assert out["prefecture"] == "東京都"
    assert out["application_window"] == {"start_date": "2026-01-01"}


def test_eligibility_predicate_handles_empty_jsic_majors() -> None:
    row: dict[str, Any] = {
        "target_types_json": None,
        "funding_purpose_json": None,
        "application_window_json": None,
        "prefecture": None,
        "jsic_majors": None,
        "jsic_major": "F",
    }
    out = i._eligibility_predicate(row)
    assert out["industry_jsic_majors"] == ["F"]


def test_eligibility_predicate_invalid_json_returns_defaults() -> None:
    row: dict[str, Any] = {
        "target_types_json": "this is not json",
        "funding_purpose_json": None,
        "application_window_json": None,
        "prefecture": None,
        "jsic_majors": None,
        "jsic_major": None,
    }
    out = i._eligibility_predicate(row)
    assert out["target_types"] == []
    assert out["application_window"] == {}


# ---------------------------------------------------------------------------
# Question / gap / document helpers
# ---------------------------------------------------------------------------


def test_question_builds_canonical_shape() -> None:
    q = i._question(
        qid="q1",
        field="capital_jpy",
        question="資本金は?",
        reason="SME 判定に必要",
        kind="eligibility",
    )
    assert q["id"] == "q1"
    assert q["blocking"] is False
    assert q["impact"] == "semi_blocking"


def test_question_blocking_when_impact_blocking() -> None:
    q = i._question(
        qid="q1",
        field="x",
        question="?",
        reason="r",
        kind="k",
        impact="blocking",
    )
    assert q["blocking"] is True


def test_gap_includes_expected_when_provided() -> None:
    g = i._gap(
        field="capital_jpy",
        reason="r",
        required_by="rb",
        expected=["sme", "startup"],
    )
    assert g["expected"] == ["sme", "startup"]


def test_gap_excludes_expected_when_none() -> None:
    g = i._gap(field="x", reason="r", required_by="rb")
    assert "expected" not in g


def test_is_required_document_true_for_required() -> None:
    assert i._is_required_document({"form_type": "required"}) is True


def test_is_required_document_false_for_optional() -> None:
    assert i._is_required_document({"form_type": "optional"}) is False
    assert i._is_required_document({"form_type": "任意"}) is False


def test_document_readiness_counts_each_axis() -> None:
    docs = [
        {"form_type": "required", "form_url": "https://x", "signature_required": True},
        {"form_type": "required", "form_url": "", "signature_required": False},
        {"form_type": "optional", "form_url": "https://y", "signature_required": True},
        {"form_type": "required", "form_url": "https://z", "signature_required": None},
    ]
    out = i._document_readiness(docs)
    # 3 required docs.
    assert out["required_document_count"] == 3
    # 2 of those have a URL.
    assert out["forms_with_url_count"] == 2
    # 1 explicit signature required.
    assert out["signature_required_count"] == 1
    assert out["signature_unknown_count"] == 1
    assert out["needs_user_confirmation"] is True


def test_document_readiness_empty_does_not_need_confirmation() -> None:
    out = i._document_readiness([])
    assert out["needs_user_confirmation"] is False


def test_meaningful_list_filters_falsy() -> None:
    out = i._meaningful_list(["x", "", None, "y", [], {}])
    assert out == ["x", "y"]


def test_meaningful_list_non_list_returns_empty() -> None:
    assert i._meaningful_list(None) == []
    assert i._meaningful_list("string") == []
