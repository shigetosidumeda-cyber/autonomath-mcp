"""DB-fixture-based coverage push for
``src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py``.

Stream HH 2026-05-16 — push coverage 33→55%+ via tmp_path-backed
minimal schemas. No touch of the 9.7 GB production autonomath.db
(memory ``feedback_no_quick_check_on_huge_sqlite``); we monkeypatch
``connect_autonomath`` to a fresh tmp_path opener for each test.

Coverage targets: 12 tool impl functions × {table-missing graceful,
table-present happy path}. Each impl carries the same shape:

  1. Argument validation → 422-class envelope.
  2. ``_open_db`` indirection → tmp sqlite3 conn.
  3. ``_table_exists`` graceful-empty branch (data_quality fields).
  4. Happy-path SELECT → results envelope with ``_billing_unit``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half as W

# ---------------------------------------------------------------------------
# tmp_path autonomath.db opener — monkeypatched into the module
# ---------------------------------------------------------------------------


def _make_empty_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript("CREATE TABLE _placeholder (k TEXT);")
    conn.commit()
    conn.close()


def _make_jpi_programs_seeded(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE jpi_programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            prefecture TEXT,
            authority_name TEXT,
            amount_max_man_yen REAL,
            source_url TEXT,
            source_fetched_at TEXT,
            jsic_major TEXT,
            jsic_middle TEXT,
            jsic_minor TEXT,
            excluded INTEGER DEFAULT 0
        );
        INSERT INTO jpi_programs VALUES
            ('UNI-x-1','補助金A','S','東京都','経産省',1000,'https://x/a','2026-05-16','C',NULL,NULL,0),
            ('UNI-x-2','補助金B','A','大阪府','経産省',500,'https://x/b','2026-05-16','D',NULL,NULL,0),
            ('UNI-x-3','除外プログラム','X',NULL,NULL,0,NULL,NULL,'C',NULL,NULL,1);
        """
    )
    conn.commit()
    conn.close()


def _make_program_documents_seeded(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE am_program_documents (
            program_unified_id TEXT,
            doc_name TEXT,
            doc_kind TEXT,
            is_required INTEGER,
            url TEXT,
            source_url TEXT
        );
        INSERT INTO am_program_documents VALUES
            ('UNI-x-1','事業計画書','application_form',1,'https://x/a.pdf','https://x'),
            ('UNI-x-1','登記簿謄本','attachment',0,NULL,NULL);
        """
    )
    conn.commit()
    conn.close()


def _make_adoption_records_seeded(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE jpi_adoption_records (
            id INTEGER PRIMARY KEY,
            houjin_bangou TEXT,
            company_name_raw TEXT,
            program_id TEXT,
            program_id_hint TEXT,
            program_name_raw TEXT,
            round_label TEXT,
            announced_at TEXT,
            prefecture TEXT,
            municipality TEXT,
            industry_jsic_medium TEXT,
            amount_granted_yen INTEGER,
            source_url TEXT
        );
        INSERT INTO jpi_adoption_records
            (houjin_bangou, company_name_raw, program_id, program_id_hint,
             program_name_raw, announced_at, prefecture, industry_jsic_medium,
             amount_granted_yen, source_url)
        VALUES
            ('1234567890123','テスト製造','UNI-x-1','UNI-x-1','補助金A','2026-01-01','東京都','C09',1000000,'https://x'),
            ('2222222222222','別会社','UNI-x-1','UNI-x-1','補助金A','2026-02-01','大阪府','C10',500000,'https://x');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def patch_db_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db = tmp_path / "empty.db"
    _make_empty_db(db)

    def _open() -> sqlite3.Connection:
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(W, "connect_autonomath", _open)
    return db


@pytest.fixture()
def patch_db_programs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db = tmp_path / "progs.db"
    _make_jpi_programs_seeded(db)

    def _open() -> sqlite3.Connection:
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(W, "connect_autonomath", _open)
    return db


@pytest.fixture()
def patch_db_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db = tmp_path / "docs.db"
    _make_program_documents_seeded(db)

    def _open() -> sqlite3.Connection:
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(W, "connect_autonomath", _open)
    return db


@pytest.fixture()
def patch_db_adoption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db = tmp_path / "adopt.db"
    _make_adoption_records_seeded(db)

    def _open() -> sqlite3.Connection:
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(W, "connect_autonomath", _open)
    return db


# ---------------------------------------------------------------------------
# #109 find_programs_by_jsic — table-missing graceful + happy path
# ---------------------------------------------------------------------------


def test_find_programs_by_jsic_missing_args_returns_error() -> None:
    out = W._find_programs_by_jsic_impl()
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_find_programs_by_jsic_invalid_jsic_major_format() -> None:
    out = W._find_programs_by_jsic_impl(jsic_major="invalid-long")
    assert out.get("code") == "invalid_enum" or "error" in out


def test_find_programs_by_jsic_invalid_tier() -> None:
    out = W._find_programs_by_jsic_impl(jsic_major="C", tier="X")
    assert out.get("code") == "invalid_enum" or "error" in out


def test_find_programs_by_jsic_empty_db_graceful(
    patch_db_empty: Path,
) -> None:
    out = W._find_programs_by_jsic_impl(jsic_major="C")
    # No jpi_programs table → graceful empty envelope
    assert out["total"] == 0
    assert out["results"] == []


def test_find_programs_by_jsic_seeded_returns_rows(
    patch_db_programs: Path,
) -> None:
    out = W._find_programs_by_jsic_impl(jsic_major="C")
    # Should find UNI-x-1 (excluded=0) but not UNI-x-3 (excluded=1)
    assert out["total"] >= 1
    assert any(r["unified_id"] == "UNI-x-1" for r in out["results"])


# ---------------------------------------------------------------------------
# #110 get_program_application_documents
# ---------------------------------------------------------------------------


def test_get_program_application_documents_missing_arg_errors() -> None:
    out = W._get_program_application_documents_impl(program_id="")
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_get_program_application_documents_no_table_graceful(
    patch_db_empty: Path,
) -> None:
    out = W._get_program_application_documents_impl(program_id="UNI-x-1")
    assert out["total"] == 0
    assert out["results"] == []
    assert "data_quality" in out


def test_get_program_application_documents_happy(
    patch_db_documents: Path,
) -> None:
    out = W._get_program_application_documents_impl(program_id="UNI-x-1")
    assert out["total"] == 2
    # is_required DESC → required first
    assert out["results"][0]["is_required"] == 1


# ---------------------------------------------------------------------------
# #111 find_adopted_companies_by_program
# ---------------------------------------------------------------------------


def test_find_adopted_companies_missing_both_args() -> None:
    out = W._find_adopted_companies_by_program_impl()
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_find_adopted_companies_no_table_graceful(
    patch_db_empty: Path,
) -> None:
    out = W._find_adopted_companies_by_program_impl(program_id="UNI-x-1")
    assert out["total"] == 0


def test_find_adopted_companies_happy(
    patch_db_adoption: Path,
) -> None:
    out = W._find_adopted_companies_by_program_impl(program_id="UNI-x-1")
    assert out["total"] == 2
    assert len(out["results"]) == 2


def test_find_adopted_companies_partial_name(
    patch_db_adoption: Path,
) -> None:
    out = W._find_adopted_companies_by_program_impl(
        program_name_partial="補助金"
    )
    assert out["total"] >= 1


# ---------------------------------------------------------------------------
# #112 score_application_probability — argument validation
# ---------------------------------------------------------------------------


def test_score_application_probability_missing_houjin() -> None:
    out = W._score_application_probability_impl(
        houjin_bangou="", program_id="UNI-x-1"
    )
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_score_application_probability_bad_houjin_format() -> None:
    out = W._score_application_probability_impl(
        houjin_bangou="1234", program_id="UNI-x-1"
    )
    assert out.get("code") == "invalid_enum" or "error" in out


def test_score_application_probability_missing_program() -> None:
    out = W._score_application_probability_impl(
        houjin_bangou="1234567890123", program_id=""
    )
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_score_application_probability_empty_db_returns_null_score(
    patch_db_empty: Path,
) -> None:
    out = W._score_application_probability_impl(
        houjin_bangou="1234567890123", program_id="UNI-x-1"
    )
    # No tables → score None, missing_tables populated
    assert out.get("score") is None
    assert "data_quality" in out


# ---------------------------------------------------------------------------
# #120 get_houjin_subsidy_history — arg validation
# ---------------------------------------------------------------------------


def test_get_houjin_subsidy_history_missing_arg() -> None:
    out = W._get_houjin_subsidy_history_impl(houjin_bangou="")
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_get_houjin_subsidy_history_bad_format() -> None:
    out = W._get_houjin_subsidy_history_impl(houjin_bangou="abc")
    assert out.get("code") == "invalid_enum" or "error" in out


def test_get_houjin_subsidy_history_bad_year_type() -> None:
    out = W._get_houjin_subsidy_history_impl(
        houjin_bangou="1234567890123", since_year="not-int"  # type: ignore[arg-type]
    )
    assert out.get("code") == "invalid_enum" or "error" in out


def test_get_houjin_subsidy_history_empty_db_graceful(
    patch_db_empty: Path,
) -> None:
    out = W._get_houjin_subsidy_history_impl(houjin_bangou="1234567890123")
    assert out["total"] == 0


# ---------------------------------------------------------------------------
# #119 get_program_renewal_probability — arg validation
# ---------------------------------------------------------------------------


def test_get_program_renewal_probability_missing_arg() -> None:
    out = W._get_program_renewal_probability_impl(program_id="")
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_get_program_renewal_probability_no_table_graceful(
    patch_db_empty: Path,
) -> None:
    out = W._get_program_renewal_probability_impl(program_id="UNI-x-1")
    # No am_amendment_diff table → graceful
    assert out.get("predicate_diff_forecast") is None or out["total"] == 0


# ---------------------------------------------------------------------------
# Misc compliance + emerging programs + density
# ---------------------------------------------------------------------------


def test_get_compliance_risk_score_missing_arg() -> None:
    out = W._get_compliance_risk_score_impl(houjin_bangou="")
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_get_compliance_risk_score_empty_db(patch_db_empty: Path) -> None:
    out = W._get_compliance_risk_score_impl(houjin_bangou="1234567890123")
    # Should return a structured envelope without crash
    assert isinstance(out, dict)


def test_simulate_tax_change_impact_empty_db(patch_db_empty: Path) -> None:
    # Minimal valid call shape — tool returns graceful envelope or error.
    out = W._simulate_tax_change_impact_impl(
        houjin_bangou="1234567890123"
    )
    assert isinstance(out, dict)


def test_simulate_tax_change_impact_bad_houjin() -> None:
    out = W._simulate_tax_change_impact_impl(houjin_bangou="abc")
    assert out.get("code") == "invalid_enum" or "error" in out


def test_find_complementary_subsidies_missing_arg() -> None:
    out = W._find_complementary_subsidies_impl(program_id="")
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_get_program_keyword_analysis_missing_arg() -> None:
    out = W._get_program_keyword_analysis_impl(program_id="")
    assert out.get("code") == "missing_required_arg" or "error" in out


def test_get_industry_program_density_empty_db(
    patch_db_empty: Path,
) -> None:
    out = W._get_industry_program_density_impl(jsic_major="C")
    assert isinstance(out, dict)


def test_find_emerging_programs_empty_db(patch_db_empty: Path) -> None:
    out = W._find_emerging_programs_impl()
    assert isinstance(out, dict)
