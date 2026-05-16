"""Pure-function tests for ``scripts/etl/extract_eligibility_predicate.py``
(Stream EE, 80%→85%).

Targets the pure helper layer of the ETL script:
  * ``_safe_json_loads`` — None / malformed JSON fallthrough.
  * ``_to_yen`` — number + unit (億円 / 万円 / 円) conversion.
  * ``_to_int`` — number string parsing, 全角 comma tolerated.
  * ``_scan_text_for_industries`` — JSIC keyword fan-out.
  * ``_scan_text_for_certifications`` / ``_scan_text_for_funding_purposes``.
  * ``_first_regex_value`` — first-match wins behaviour.
  * ``_walk_eligibility_clauses`` — clauses + _source_quote roll-up.
  * ``_structured_eligibility_axes`` — eligibility_structured fold.
  * ``extract_predicate`` — end-to-end on a synthetic Row dict.

The script is loaded via ``importlib`` so we can exercise the module
without invoking ``main()``. NO DB / HTTP / LLM calls.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "extract_eligibility_predicate",
    REPO_ROOT / "scripts" / "etl" / "extract_eligibility_predicate.py",
)
assert _SPEC and _SPEC.loader, "spec / loader missing"
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# _safe_json_loads
# ---------------------------------------------------------------------------


def test_safe_json_loads_none_returns_none() -> None:
    assert mod._safe_json_loads(None) is None


def test_safe_json_loads_empty_string_returns_none() -> None:
    assert mod._safe_json_loads("") is None


def test_safe_json_loads_malformed_returns_none() -> None:
    assert mod._safe_json_loads("{not-json") is None


def test_safe_json_loads_valid_json_parsed() -> None:
    assert mod._safe_json_loads('["a","b"]') == ["a", "b"]


# ---------------------------------------------------------------------------
# _to_yen
# ---------------------------------------------------------------------------


def test_to_yen_oku_unit() -> None:
    assert mod._to_yen("3", "億円") == 300_000_000


def test_to_yen_man_unit() -> None:
    assert mod._to_yen("100", "万円") == 1_000_000


def test_to_yen_plain_yen_unit() -> None:
    assert mod._to_yen("500", "円") == 500


def test_to_yen_unknown_unit_returns_none() -> None:
    assert mod._to_yen("1", "kg") is None


def test_to_yen_zenkaku_comma_supported() -> None:
    assert mod._to_yen("1，000", "万円") == 10_000_000


def test_to_yen_invalid_number_returns_none() -> None:
    assert mod._to_yen("abc", "万円") is None


# ---------------------------------------------------------------------------
# _to_int
# ---------------------------------------------------------------------------


def test_to_int_plain_digits() -> None:
    assert mod._to_int("300") == 300


def test_to_int_with_commas() -> None:
    assert mod._to_int("1,234") == 1234


def test_to_int_invalid_returns_none() -> None:
    assert mod._to_int("xyz") is None


# ---------------------------------------------------------------------------
# _scan_text_for_industries
# ---------------------------------------------------------------------------


def test_scan_text_for_industries_picks_construction_d() -> None:
    out = mod._scan_text_for_industries("耐震改修工事")
    assert "D" in out


def test_scan_text_for_industries_multi_axes_returned_sorted() -> None:
    out = mod._scan_text_for_industries("農業とDX導入")
    # 農業 -> A, DX -> G. Sorted output.
    assert out == sorted(out)
    assert "A" in out and "G" in out


def test_scan_text_for_industries_empty_returns_empty() -> None:
    assert mod._scan_text_for_industries("") == []


# ---------------------------------------------------------------------------
# _scan_text_for_certifications / _scan_text_for_funding_purposes
# ---------------------------------------------------------------------------


def test_scan_text_for_certifications_detects_known_phrase() -> None:
    out = mod._scan_text_for_certifications("認定新規就農者として登録した方")
    assert "認定新規就農者" in out


def test_scan_text_for_certifications_empty_returns_empty() -> None:
    assert mod._scan_text_for_certifications("") == []


def test_scan_text_for_funding_purposes_picks_dx_and_gx() -> None:
    out = mod._scan_text_for_funding_purposes("DX投資とGXに対応")
    assert "DX" in out
    assert "GX" in out


# ---------------------------------------------------------------------------
# _first_regex_value
# ---------------------------------------------------------------------------


def test_first_regex_value_returns_first_match_groups() -> None:
    text = "資本金 3 億円 以下"
    out = mod._first_regex_value(text, mod.CAPITAL_MAX_PATTERNS)
    assert out is not None
    # groups = (number, unit)
    assert out[1] == "億円"


def test_first_regex_value_no_match_returns_none() -> None:
    out = mod._first_regex_value("資本金 unrelated text", mod.CAPITAL_MAX_PATTERNS)
    assert out is None


# ---------------------------------------------------------------------------
# _walk_eligibility_clauses
# ---------------------------------------------------------------------------


def test_walk_eligibility_clauses_extracts_dict_text_form() -> None:
    enriched = {
        "extraction": {
            "application_plan": {
                "eligibility_clauses": [
                    {"text": "従業員数 300人以下"},
                    "創業3年以上",
                ]
            }
        }
    }
    out = mod._walk_eligibility_clauses(enriched)
    assert "従業員数 300人以下" in out
    assert "創業3年以上" in out


def test_walk_eligibility_clauses_collects_source_quotes() -> None:
    enriched = {
        "extraction": {
            "eligibility_structured": {
                "section_a": {
                    "_source_quote": "資本金 3億円以下",
                }
            }
        }
    }
    out = mod._walk_eligibility_clauses(enriched)
    assert "資本金 3億円以下" in out


def test_walk_eligibility_clauses_none_input_returns_empty() -> None:
    assert mod._walk_eligibility_clauses(None) == []


# ---------------------------------------------------------------------------
# _structured_eligibility_axes
# ---------------------------------------------------------------------------


def test_structured_eligibility_axes_empty_enriched_returns_empty() -> None:
    assert mod._structured_eligibility_axes(None) == {}
    assert mod._structured_eligibility_axes({}) == {}


def test_structured_eligibility_axes_employee_max_extracted() -> None:
    enriched = {
        "extraction": {
            "eligibility_structured": {
                "entity": {"employees": {"max": 100}}
            }
        }
    }
    out = mod._structured_eligibility_axes(enriched)
    assert out.get("employee_max") == 100


def test_structured_eligibility_axes_age_min_max_picked() -> None:
    enriched = {
        "extraction": {
            "eligibility_structured": {
                "person_attributes": {"age": {"min": 20, "max": 65}},
            }
        }
    }
    out = mod._structured_eligibility_axes(enriched)
    assert out.get("age") == {"min": 20, "max": 65}


def test_structured_eligibility_axes_certifications_sorted_unique() -> None:
    enriched = {
        "extraction": {
            "eligibility_structured": {
                "certifications": {
                    "any_of": ["認定農業者", "認定農業者", "中小企業者"]
                }
            }
        }
    }
    out = mod._structured_eligibility_axes(enriched)
    # dedup + sort
    assert out["certifications_any_of"] == sorted({"認定農業者", "中小企業者"})


# ---------------------------------------------------------------------------
# extract_predicate — end-to-end on a synthetic row dict
# ---------------------------------------------------------------------------


def test_extract_predicate_minimal_row_produces_low_confidence() -> None:
    row = {
        "primary_name": "○○補助金",
        "prefecture": "",
        "municipality": "",
        "program_kind": "",
        "target_types_json": None,
        "crop_categories_json": None,
        "funding_purpose_json": None,
        "enriched_json": None,
    }
    predicate, confidence = mod.extract_predicate(row)
    assert isinstance(predicate, dict)
    # No structured axes; confidence is the populated_axes/6.0 ratio.
    assert 0.0 <= confidence <= 1.0


def test_extract_predicate_prefecture_jis_code_picked() -> None:
    row = {
        "primary_name": "東京都DX補助金",
        "prefecture": "東京都",
        "municipality": "",
        "program_kind": "",
        "target_types_json": '["sme"]',
        "crop_categories_json": None,
        "funding_purpose_json": '["DX"]',
        "enriched_json": None,
    }
    predicate, _ = mod.extract_predicate(row)
    assert predicate.get("prefectures") == ["東京都"]
    assert predicate.get("prefecture_jis") == ["13"]


def test_extract_predicate_keyword_industry_inference() -> None:
    row = {
        "primary_name": "農業者向け補助金",
        "prefecture": "",
        "municipality": "",
        "program_kind": "",
        "target_types_json": None,
        "crop_categories_json": None,
        "funding_purpose_json": None,
        "enriched_json": None,
    }
    predicate, _ = mod.extract_predicate(row)
    assert "A" in (predicate.get("industries_jsic") or [])
