"""Additional pure-function tests for ``api.intel`` (Stream EE, 80%→85%).

Builds on ``tests/test_api_intel_pure.py`` (Stream CC). Targets the
private helpers not yet covered:
  * ``_capital_fit_bonus`` — 4 size bands.
  * ``_compute_match_score`` — ranking formula edges.
  * ``_normalize_match_score`` — projection to [0, 1].
  * ``_eligibility_predicate`` — JSON column unpack to predicate dict.
  * ``_meaningful_list`` — sparse list filter.
  * ``_is_required_document`` / ``_document_readiness`` / ``_document_questions``.
  * ``_question`` / ``_gap`` — builder uniform shape contract.
  * ``_verify_proof_path`` — bad-hex + missing position fail-closed.

NO DB / HTTP / LLM calls. All pure Python over module-private helpers.
"""

from __future__ import annotations

import hashlib

import jpintel_mcp.api.intel as i

# ---------------------------------------------------------------------------
# _capital_fit_bonus
# ---------------------------------------------------------------------------


def test_capital_fit_bonus_missing_either_side_returns_zero() -> None:
    assert i._capital_fit_bonus(None, 100) == 0.0
    assert i._capital_fit_bonus(1_000_000, None) == 0.0


def test_capital_fit_bonus_non_numeric_amount_returns_zero() -> None:
    assert i._capital_fit_bonus(1_000_000, "abc") == 0.0


def test_capital_fit_bonus_right_sized_program_gets_full_bonus() -> None:
    # cap = 10万円 = 100,000 yen; capital_jpy = 1,000,000.
    # ratio = 0.1 (>=0.01, <=1.0) -> 0.3.
    assert i._capital_fit_bonus(1_000_000, 10) == 0.3


def test_capital_fit_bonus_tiny_program_below_one_percent_band() -> None:
    # cap = 100 yen, capital = 100,000,000 -> ratio = 1e-6 (<0.01) -> 0.05.
    assert i._capital_fit_bonus(100_000_000, 0.01) == 0.05


def test_capital_fit_bonus_oversized_program_gets_smaller_bonus() -> None:
    # cap = 1,000 万円 = 10,000,000; capital = 1,000,000 -> ratio = 10.
    assert i._capital_fit_bonus(1_000_000, 1000) == 0.1


# ---------------------------------------------------------------------------
# _compute_match_score / _normalize_match_score
# ---------------------------------------------------------------------------


def test_compute_match_score_unknown_tier_uses_default_05() -> None:
    score = i._compute_match_score(
        tier=None,
        verification_count=0,
        density=0,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    assert score == 0.5


def test_compute_match_score_includes_keyword_bonus() -> None:
    s_no_match = i._compute_match_score(
        tier="S",
        verification_count=0,
        density=0,
        keyword="補助金",
        primary_name="まったく違う",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    s_match = i._compute_match_score(
        tier="S",
        verification_count=0,
        density=0,
        keyword="補助金",
        primary_name="○○補助金交付事業",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    # 0.6 added when keyword substring matches name (case-insensitive).
    assert round(s_match - s_no_match, 4) == 0.6


def test_compute_match_score_verification_count_capped_at_five() -> None:
    s_5 = i._compute_match_score(
        tier="A",
        verification_count=5,
        density=0,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    s_50 = i._compute_match_score(
        tier="A",
        verification_count=50,
        density=0,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    # Both should match (5 is the cap).
    assert s_5 == s_50


def test_compute_match_score_density_log_term_bounded() -> None:
    # density bonus is capped at 0.4 even for huge density.
    s_tiny = i._compute_match_score(
        tier="A",
        verification_count=0,
        density=1,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    s_huge = i._compute_match_score(
        tier="A",
        verification_count=0,
        density=10**9,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    # Both bounded; huge - tiny should not exceed the 0.4 cap.
    assert s_huge - s_tiny <= 0.4 + 1e-6


def test_compute_match_score_vec_similarity_added_when_set() -> None:
    s_off = i._compute_match_score(
        tier="A",
        verification_count=0,
        density=0,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    s_on = i._compute_match_score(
        tier="A",
        verification_count=0,
        density=0,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=0.05,
    )
    assert round(s_on - s_off, 4) == 0.05


def test_normalize_match_score_zero_max_returns_zero() -> None:
    assert i._normalize_match_score(2.5, 0.0) == 0.0


def test_normalize_match_score_clamps_to_unit_interval() -> None:
    assert i._normalize_match_score(10.0, 1.0) == 1.0
    assert i._normalize_match_score(-3.0, 1.0) == 0.0


def test_normalize_match_score_intermediate_value() -> None:
    assert i._normalize_match_score(1.0, 4.0) == 0.25


# ---------------------------------------------------------------------------
# _eligibility_predicate
# ---------------------------------------------------------------------------


def test_eligibility_predicate_empty_row_returns_empty_axes() -> None:
    out = i._eligibility_predicate({})
    assert out["target_types"] == []
    assert out["funding_purpose"] == []
    assert out["application_window"] == {}
    assert out["industry_jsic_majors"] == []


def test_eligibility_predicate_unpacks_json_columns() -> None:
    row = {
        "target_types_json": '["sme", "npo"]',
        "funding_purpose_json": '["dx"]',
        "application_window_json": '{"open": "2026-04-01"}',
        "jsic_majors": '["D", "E"]',
        "jsic_major": "D",
        "prefecture": "東京都",
        "amount_max_man_yen": 200,
        "amount_min_man_yen": 50,
        "subsidy_rate": "2/3",
    }
    out = i._eligibility_predicate(row)
    assert out["target_types"] == ["sme", "npo"]
    assert out["funding_purpose"] == ["dx"]
    assert out["application_window"] == {"open": "2026-04-01"}
    assert out["industry_jsic_majors"] == ["D", "E"]
    assert out["prefecture"] == "東京都"
    assert out["amount_max_man_yen"] == 200


def test_eligibility_predicate_falls_back_to_singular_jsic_major() -> None:
    row = {"jsic_major": "M"}
    out = i._eligibility_predicate(row)
    assert out["industry_jsic_majors"] == ["M"]


def test_eligibility_predicate_malformed_json_treated_as_empty() -> None:
    row = {"target_types_json": "{not-json}"}
    out = i._eligibility_predicate(row)
    assert out["target_types"] == []


# ---------------------------------------------------------------------------
# _meaningful_list / _is_required_document
# ---------------------------------------------------------------------------


def test_meaningful_list_drops_falsy_entries() -> None:
    out = i._meaningful_list([0, "", None, "abc", [], {}, "xyz"])
    # Note: 0 is preserved because `0 not in (None, "", [], {})`.
    assert "abc" in out and "xyz" in out
    assert "" not in out and None not in out


def test_meaningful_list_non_list_returns_empty() -> None:
    assert i._meaningful_list("string") == []
    assert i._meaningful_list(None) == []


def test_is_required_document_default_is_required() -> None:
    assert i._is_required_document({"form_type": "required"}) is True


def test_is_required_document_optional_returns_false() -> None:
    assert i._is_required_document({"form_type": "optional"}) is False


def test_is_required_document_japanese_任意_returns_false() -> None:
    assert i._is_required_document({"form_type": "任意"}) is False


def test_is_required_document_empty_form_type_returns_true() -> None:
    # Default-unknown is treated as required (semi-blocking).
    assert i._is_required_document({"form_type": ""}) is True


# ---------------------------------------------------------------------------
# _document_readiness / _document_questions
# ---------------------------------------------------------------------------


def test_document_readiness_summary_required_count() -> None:
    docs = [
        {"form_type": "required", "form_url": "http://example.com/a"},
        {"form_type": "required", "form_url": ""},
        {"form_type": "optional", "form_url": "http://example.com/c"},
        {"form_type": "任意", "form_url": "http://example.com/d"},
    ]
    out = i._document_readiness(docs)
    assert out["required_document_count"] == 2
    assert out["forms_with_url_count"] == 1
    assert out["needs_user_confirmation"] is True


def test_document_readiness_signature_required_buckets() -> None:
    docs = [
        {"form_type": "required", "signature_required": True},
        {"form_type": "required", "signature_required": False},
        {"form_type": "required", "signature_required": None},
    ]
    out = i._document_readiness(docs)
    assert out["signature_required_count"] == 1
    assert out["signature_unknown_count"] == 1


def test_document_questions_emits_one_per_required_doc() -> None:
    docs = [
        {"form_type": "required", "form_name": "事業計画書"},
        {"form_type": "optional", "form_name": "任意添付"},
        {"form_type": "required", "form_name": "決算書"},
    ]
    out = i._document_questions(docs)
    assert len(out) == 2
    assert all(q["kind"] == "document_readiness" for q in out)


# ---------------------------------------------------------------------------
# _question / _gap
# ---------------------------------------------------------------------------


def test_question_builder_blocking_when_impact_blocking() -> None:
    q = i._question(
        qid="x1",
        field="capital_jpy",
        question="?",
        reason="r",
        kind="eligibility_input",
        impact="blocking",
    )
    assert q["blocking"] is True
    assert q["id"] == "x1"


def test_question_builder_default_impact_semi_blocking_not_blocking() -> None:
    q = i._question(qid="x2", field="f", question="q", reason="r", kind="k")
    assert q["impact"] == "semi_blocking"
    assert q["blocking"] is False


def test_gap_builder_omits_expected_when_none() -> None:
    g = i._gap(field="f", reason="r", required_by="rb")
    assert "expected" not in g


def test_gap_builder_includes_expected_when_set() -> None:
    g = i._gap(field="f", reason="r", required_by="rb", expected=["a", "b"])
    assert g["expected"] == ["a", "b"]


# ---------------------------------------------------------------------------
# _verify_proof_path
# ---------------------------------------------------------------------------


def test_verify_proof_path_empty_inputs_return_false() -> None:
    assert i._verify_proof_path("", [], "abc") is False
    assert i._verify_proof_path("abc", [], "") is False


def test_verify_proof_path_unknown_position_returns_false() -> None:
    leaf = hashlib.sha256(b"x").hexdigest()
    sibling = hashlib.sha256(b"y").hexdigest()
    bad = [{"position": "middle", "hash": sibling}]
    assert i._verify_proof_path(leaf, bad, "00" * 32) is False


def test_verify_proof_path_bad_hex_in_sibling_returns_false() -> None:
    leaf = hashlib.sha256(b"x").hexdigest()
    bad = [{"position": "left", "hash": "zz"}]
    assert i._verify_proof_path(leaf, bad, "00" * 32) is False


def test_verify_proof_path_single_step_roundtrip_validates() -> None:
    # Construct a 1-step proof so the recomputed root matches.
    leaf = hashlib.sha256(b"leaf").hexdigest()
    sibling = hashlib.sha256(b"sibling").hexdigest()
    # We are "right" of sibling: root = sha256(sibling || leaf).
    expected = hashlib.sha256(
        bytes.fromhex(sibling) + bytes.fromhex(leaf)
    ).hexdigest()
    proof = [{"position": "left", "hash": sibling}]
    assert i._verify_proof_path(leaf, proof, expected) is True


def test_verify_proof_path_mismatched_root_returns_false() -> None:
    leaf = hashlib.sha256(b"leaf").hexdigest()
    sibling = hashlib.sha256(b"sibling").hexdigest()
    proof = [{"position": "left", "hash": sibling}]
    # Bogus expected root → False (but no exception).
    assert i._verify_proof_path(leaf, proof, "00" * 32) is False
