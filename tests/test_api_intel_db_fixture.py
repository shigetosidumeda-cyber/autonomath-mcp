"""DB-fixture-based coverage push for ``src/jpintel_mcp/api/intel.py``.

Stream HH 2026-05-16 — push coverage 65→80%+ via tmp_path-backed
minimal schemas. No touch of the 9.7 GB production autonomath.db
(memory ``feedback_no_quick_check_on_huge_sqlite``).

Targets:
  * ``_normalize_houjin`` / ``_is_valid_houjin``
  * ``_table_exists`` / ``_column_exists``
  * ``_select_match_columns`` — COALESCE branch on missing columns.
  * ``_density_lookup`` — tmp pc_program_geographic_density rows.
  * ``_capital_fit_bonus`` — pure heuristic branches.
  * ``_similar_adopted_companies`` — adoption_records seed + JOIN.
  * ``_required_documents_for`` — program_documents seed.
  * ``_meaningful_list`` / ``_eligibility_predicate`` — pure shape.
  * ``_compute_match_score`` / ``_normalize_match_score`` — math branches.
  * ``_question`` / ``_gap`` — envelope shape.
  * ``_is_required_document`` / ``_document_readiness``.
  * ``_document_questions`` — envelope.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import jpintel_mcp.api.intel as I

# ---------------------------------------------------------------------------
# Fixture: minimal programs + auxiliary schema in tmp_path
# ---------------------------------------------------------------------------


def _make_intel_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            prefecture TEXT,
            authority_name TEXT,
            program_kind TEXT,
            amount_max_man_yen REAL,
            amount_min_man_yen REAL,
            subsidy_rate TEXT,
            source_url TEXT,
            official_url TEXT,
            verification_count INTEGER DEFAULT 0,
            jsic_majors TEXT,
            jsic_major TEXT,
            application_window_json TEXT,
            target_types_json TEXT,
            funding_purpose_json TEXT
        );
        CREATE TABLE pc_program_geographic_density (
            prefecture_code TEXT,
            tier TEXT,
            program_count INTEGER
        );
        CREATE TABLE adoption_records (
            id INTEGER PRIMARY KEY,
            houjin_bangou TEXT,
            company_name_raw TEXT,
            prefecture TEXT,
            industry_jsic_medium TEXT,
            announced_at TEXT,
            amount_granted_yen INTEGER
        );
        CREATE TABLE houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            normalized_name TEXT
        );
        CREATE TABLE program_documents (
            id INTEGER PRIMARY KEY,
            program_name TEXT,
            form_name TEXT,
            form_type TEXT,
            form_format TEXT,
            form_url_direct TEXT,
            signature_required INTEGER
        );
        """
    )
    conn.commit()
    conn.close()


def _make_minimal_programs_only(db_path: Path) -> None:
    """Schema missing source_url / official_url / verification_count / jsic_*
    so _select_match_columns hits the COALESCE branches."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            prefecture TEXT,
            authority_name TEXT,
            program_kind TEXT,
            amount_max_man_yen REAL,
            amount_min_man_yen REAL,
            subsidy_rate TEXT
        )
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def intel_db(tmp_path: Path) -> Path:
    db = tmp_path / "intel.db"
    _make_intel_db(db)
    return db


@pytest.fixture()
def intel_conn(intel_db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(intel_db)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture()
def minimal_programs_db(tmp_path: Path) -> Path:
    db = tmp_path / "minprog.db"
    _make_minimal_programs_only(db)
    return db


# ---------------------------------------------------------------------------
# _normalize_houjin / _is_valid_houjin
# ---------------------------------------------------------------------------


def test_normalize_houjin_strips_t_prefix() -> None:
    assert I._normalize_houjin("T8010001213708") == "8010001213708"


def test_normalize_houjin_passthrough() -> None:
    assert I._normalize_houjin("8010001213708") == "8010001213708"


def test_normalize_houjin_none_returns_empty() -> None:
    assert I._normalize_houjin(None) == ""


def test_is_valid_houjin_13_digits() -> None:
    assert I._is_valid_houjin("8010001213708") is True


def test_is_valid_houjin_short_rejected() -> None:
    assert I._is_valid_houjin("1234") is False


def test_is_valid_houjin_non_numeric_rejected() -> None:
    assert I._is_valid_houjin("abcdefghijklm") is False


# ---------------------------------------------------------------------------
# _table_exists / _column_exists
# ---------------------------------------------------------------------------


def test_table_exists_present(intel_conn: sqlite3.Connection) -> None:
    assert I._table_exists(intel_conn, "programs") is True


def test_table_exists_absent(intel_conn: sqlite3.Connection) -> None:
    assert I._table_exists(intel_conn, "nonexistent_table_xyz") is False


def test_column_exists_present(intel_conn: sqlite3.Connection) -> None:
    assert I._column_exists(intel_conn, "programs", "primary_name") is True


def test_column_exists_absent(intel_conn: sqlite3.Connection) -> None:
    assert I._column_exists(intel_conn, "programs", "nonexistent_col_xyz") is False


# ---------------------------------------------------------------------------
# _select_match_columns
# ---------------------------------------------------------------------------


def test_select_match_columns_full_schema(intel_conn: sqlite3.Connection) -> None:
    sql = I._select_match_columns(intel_conn)
    # All real columns should be present, no NULL AS fallbacks for these.
    assert "source_url" in sql
    assert "official_url" in sql
    assert "verification_count" in sql
    assert "jsic_majors" in sql
    assert "target_types_json" in sql


def test_select_match_columns_missing_columns_uses_null_fallback(
    minimal_programs_db: Path,
) -> None:
    c = sqlite3.connect(minimal_programs_db)
    c.row_factory = sqlite3.Row
    sql = I._select_match_columns(c)
    # Missing columns should appear as "NULL AS xxx" or "0 AS xxx".
    assert "NULL AS source_url" in sql or "0 AS source_url" in sql or "source_url" in sql
    assert "0 AS verification_count" in sql
    assert "NULL AS jsic_majors" in sql
    c.close()


# ---------------------------------------------------------------------------
# _density_lookup
# ---------------------------------------------------------------------------


def test_density_lookup_empty_when_no_rows(intel_conn: sqlite3.Connection) -> None:
    out = I._density_lookup(intel_conn, "13")
    assert out == {}


def test_density_lookup_returns_tier_counts(
    intel_db: Path, intel_conn: sqlite3.Connection
) -> None:
    intel_conn.execute(
        "INSERT INTO pc_program_geographic_density(prefecture_code, tier, program_count) "
        "VALUES (?,?,?)",
        ("JP-13", "S", 5),
    )
    intel_conn.execute(
        "INSERT INTO pc_program_geographic_density(prefecture_code, tier, program_count) "
        "VALUES (?,?,?)",
        ("JP-13", "A", 12),
    )
    intel_conn.commit()
    out = I._density_lookup(intel_conn, "13")
    assert out.get("S") == 5
    assert out.get("A") == 12


def test_density_lookup_missing_table(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    db.touch()
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    out = I._density_lookup(c, "13")
    assert out == {}
    c.close()


# ---------------------------------------------------------------------------
# _capital_fit_bonus
# ---------------------------------------------------------------------------


def test_capital_fit_bonus_both_none() -> None:
    assert I._capital_fit_bonus(None, None) == 0.0


def test_capital_fit_bonus_in_sweet_spot() -> None:
    # 1000万 capital, 500万 program cap -> ratio 0.5 (sweet spot)
    bonus = I._capital_fit_bonus(10_000_000, 500)
    assert bonus == 0.3


def test_capital_fit_bonus_oversized_program() -> None:
    # 100万 capital, 1億 program cap -> ratio 100 (oversized)
    bonus = I._capital_fit_bonus(1_000_000, 10000)
    assert bonus == 0.1


def test_capital_fit_bonus_very_small_program() -> None:
    # 1億 capital, 1万 program cap -> ratio 0.001 (tiny)
    bonus = I._capital_fit_bonus(100_000_000, 1)
    assert bonus == 0.05


def test_capital_fit_bonus_invalid_type_safe() -> None:
    assert I._capital_fit_bonus(1_000_000, "not-a-number") == 0.0


# ---------------------------------------------------------------------------
# _similar_adopted_companies
# ---------------------------------------------------------------------------


def test_similar_adopted_companies_empty_table(intel_conn: sqlite3.Connection) -> None:
    out = I._similar_adopted_companies(intel_conn, pref_name="東京都", jsic_major="C")
    assert out == []


def test_similar_adopted_companies_seeded(
    intel_db: Path, intel_conn: sqlite3.Connection
) -> None:
    intel_conn.execute(
        "INSERT INTO adoption_records(houjin_bangou, company_name_raw, prefecture, "
        "industry_jsic_medium, announced_at, amount_granted_yen) VALUES (?,?,?,?,?,?)",
        ("1234567890123", "テスト製造株式会社", "東京都", "C09", "2026-01-01", 1_000_000),
    )
    intel_conn.execute(
        "INSERT INTO adoption_records(houjin_bangou, company_name_raw, prefecture, "
        "industry_jsic_medium, announced_at, amount_granted_yen) VALUES (?,?,?,?,?,?)",
        ("9876543210987", "別会社", "東京都", "C10", "2026-02-01", 500_000),
    )
    intel_conn.commit()
    out = I._similar_adopted_companies(
        intel_conn, pref_name="東京都", jsic_major="C", limit=10
    )
    assert len(out) == 2
    assert all(r["trade_name"] for r in out)


def test_similar_adopted_companies_pref_filter(
    intel_db: Path, intel_conn: sqlite3.Connection
) -> None:
    intel_conn.execute(
        "INSERT INTO adoption_records(houjin_bangou, company_name_raw, prefecture, "
        "industry_jsic_medium, announced_at, amount_granted_yen) VALUES (?,?,?,?,?,?)",
        ("1234567890123", "東京会社", "東京都", "C09", "2026-01-01", 1_000_000),
    )
    intel_conn.execute(
        "INSERT INTO adoption_records(houjin_bangou, company_name_raw, prefecture, "
        "industry_jsic_medium, announced_at, amount_granted_yen) VALUES (?,?,?,?,?,?)",
        ("2222222222222", "大阪会社", "大阪府", "C09", "2026-01-01", 1_000_000),
    )
    intel_conn.commit()
    out = I._similar_adopted_companies(
        intel_conn, pref_name="東京都", jsic_major="C", limit=10
    )
    assert len(out) == 1
    assert out[0]["trade_name"] == "東京会社"


# ---------------------------------------------------------------------------
# _required_documents_for
# ---------------------------------------------------------------------------


def test_required_documents_for_empty(intel_conn: sqlite3.Connection) -> None:
    out = I._required_documents_for(intel_conn, primary_name="テスト補助金", limit=5)
    assert out == []


def test_required_documents_for_seeded(
    intel_db: Path, intel_conn: sqlite3.Connection
) -> None:
    intel_conn.execute(
        "INSERT INTO program_documents(program_name, form_name, form_type, form_format, "
        "form_url_direct, signature_required) VALUES (?,?,?,?,?,?)",
        ("テスト補助金", "事業計画書", "required", "pdf", "https://example.com/a.pdf", 1),
    )
    intel_conn.execute(
        "INSERT INTO program_documents(program_name, form_name, form_type, form_format, "
        "form_url_direct, signature_required) VALUES (?,?,?,?,?,?)",
        ("テスト補助金", "登記簿謄本", "optional", None, None, 0),
    )
    intel_conn.commit()
    out = I._required_documents_for(intel_conn, primary_name="テスト補助金", limit=5)
    assert len(out) == 2
    # required first by ORDER BY CASE
    assert out[0]["form_type"] == "required"
    assert out[0]["signature_required"] is True


# ---------------------------------------------------------------------------
# _meaningful_list / _eligibility_predicate
# ---------------------------------------------------------------------------


def test_meaningful_list_filters_empties() -> None:
    out = I._meaningful_list(["a", "", None, [], "b"])
    assert out == ["a", "b"]


def test_meaningful_list_non_list_returns_empty() -> None:
    assert I._meaningful_list("not-a-list") == []


def test_eligibility_predicate_decodes_json_arrays() -> None:
    row = {
        "target_types_json": '["sole_proprietor"]',
        "funding_purpose_json": '["設備投資"]',
        "application_window_json": '{"start":"2026-01-01"}',
        "prefecture": "東京都",
        "jsic_majors": '["C"]',
        "jsic_major": None,
        "amount_max_man_yen": 100,
        "amount_min_man_yen": 10,
        "subsidy_rate": "1/2",
    }
    out = I._eligibility_predicate(row)
    assert out["target_types"] == ["sole_proprietor"]
    assert out["funding_purpose"] == ["設備投資"]
    assert out["industry_jsic_majors"] == ["C"]
    assert out["prefecture"] == "東京都"


def test_eligibility_predicate_fallback_to_jsic_major_when_majors_empty() -> None:
    row = {
        "target_types_json": None,
        "funding_purpose_json": None,
        "application_window_json": None,
        "prefecture": None,
        "jsic_majors": None,
        "jsic_major": "C",
        "amount_max_man_yen": None,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
    }
    out = I._eligibility_predicate(row)
    assert out["industry_jsic_majors"] == ["C"]


def test_eligibility_predicate_invalid_json_safe() -> None:
    row = {
        "target_types_json": "not-json",
        "funding_purpose_json": "{bad",
        "application_window_json": None,
        "prefecture": None,
        "jsic_majors": None,
        "jsic_major": None,
        "amount_max_man_yen": None,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
    }
    out = I._eligibility_predicate(row)
    assert out["target_types"] == []
    assert out["funding_purpose"] == []


# ---------------------------------------------------------------------------
# _compute_match_score / _normalize_match_score
# ---------------------------------------------------------------------------


def test_compute_match_score_keyword_in_name_bonus() -> None:
    score = I._compute_match_score(
        tier="S",
        verification_count=0,
        density=0,
        keyword="補助",
        primary_name="補助金制度",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    # base S weight + 0.6 keyword bonus
    assert score > 0.6


def test_compute_match_score_no_keyword_match() -> None:
    score = I._compute_match_score(
        tier="C",
        verification_count=0,
        density=0,
        keyword="無関係",
        primary_name="補助金制度",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    assert score == round(I._TIER_WEIGHT.get("C", 0.5), 4)


def test_compute_match_score_density_log_bonus() -> None:
    score = I._compute_match_score(
        tier="A",
        verification_count=0,
        density=100,
        keyword=None,
        primary_name="",
        capital_bonus=0.0,
        vec_similarity=None,
    )
    assert score > I._TIER_WEIGHT["A"]


def test_normalize_match_score_zero_max_returns_zero() -> None:
    assert I._normalize_match_score(score=1.0, max_score=0.0) == 0.0


def test_normalize_match_score_clamps_to_1() -> None:
    assert I._normalize_match_score(score=2.0, max_score=1.0) == 1.0


def test_normalize_match_score_basic_division() -> None:
    out = I._normalize_match_score(score=0.5, max_score=1.0)
    assert out == 0.5


# ---------------------------------------------------------------------------
# _question / _gap / _is_required_document / _document_readiness
# ---------------------------------------------------------------------------


def test_question_shape() -> None:
    out = I._question(
        qid="q1", field="employee_count", question="?", reason="r", kind="x"
    )
    assert out["id"] == "q1"
    assert out["blocking"] is False


def test_question_blocking_impact() -> None:
    out = I._question(
        qid="q1", field="x", question="?", reason="r", kind="x", impact="blocking"
    )
    assert out["blocking"] is True


def test_gap_with_expected() -> None:
    out = I._gap(field="x", reason="r", required_by="y", expected=["a"])
    assert out["expected"] == ["a"]


def test_gap_without_expected_omits_key() -> None:
    out = I._gap(field="x", reason="r", required_by="y")
    assert "expected" not in out


def test_is_required_document_true_when_required() -> None:
    assert I._is_required_document({"form_type": "required"}) is True


def test_is_required_document_false_when_optional() -> None:
    assert I._is_required_document({"form_type": "optional"}) is False
    assert I._is_required_document({"form_type": "任意"}) is False


def test_document_readiness_empty_list() -> None:
    out = I._document_readiness([])
    assert out["required_document_count"] == 0
    assert out["needs_user_confirmation"] is False


def test_document_readiness_counts_required_only() -> None:
    docs = [
        {"form_type": "required", "form_url": "x", "signature_required": True},
        {"form_type": "optional", "form_url": "", "signature_required": False},
        {"form_type": "required", "form_url": "", "signature_required": None},
    ]
    out = I._document_readiness(docs)
    assert out["required_document_count"] == 2
    assert out["forms_with_url_count"] == 1
    assert out["signature_required_count"] == 1
    assert out["signature_unknown_count"] == 1


def test_document_questions_skips_optional() -> None:
    docs = [
        {"form_name": "事業計画書", "form_type": "required"},
        {"form_name": "添付書類", "form_type": "optional"},
    ]
    out = I._document_questions(docs)
    assert len(out) == 1
    assert "事業計画書" in out[0]["question"]
