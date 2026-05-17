"""Coverage push #6 — ``api.intel`` private helper bands not yet exercised.

CL15 task #276 — focus on the SQL-helper bands the prior streams (CC / EE /
HH) skipped: probability radar (``_compute_probability_estimate`` /
``_compute_industry_rate_and_award`` / ``_build_evidence_packets``), the
seal-source pipeline (``_seal_source_urls_for_epid`` / ``_enrich_with_am_source``),
applicable laws / 通達 / required_documents joins, ``_eligibility_gaps_for``
+ ``_next_questions_for`` compositions, ``_audit_proof_for`` graceful
degradation, and ``_open_intel_match_autonomath_ro`` happy / missing-file
branches.

Rules (memory feedback):
* **NO LLM API import** — every test is pure SQLite + Python.
* **NO mock DB** — we build a real tmp_path SQLite fixture so the helpers
  exercise the exact SQL they ship in production.
* New file only — never touches ``src/`` or other ``tests/`` files.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from jpintel_mcp.api import intel as intel_mod
from jpintel_mcp.api.intel import IntelMatchRequest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helper: build a tmp SQLite for the autonomath-side tables the radar reads.
# ---------------------------------------------------------------------------


def _make_radar_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE am_recommended_programs (
            houjin_bangou TEXT,
            program_unified_id TEXT,
            score REAL
        );
        CREATE TABLE jpi_adoption_records (
            id INTEGER PRIMARY KEY,
            program_id TEXT,
            amount_granted_yen INTEGER,
            industry_jsic_medium TEXT,
            source_url TEXT
        );
        CREATE TABLE am_adopted_company_features (
            houjin_bangou TEXT PRIMARY KEY,
            dominant_jsic_major TEXT
        );
        CREATE TABLE am_source (
            source_url TEXT PRIMARY KEY,
            content_hash TEXT,
            last_verified TEXT
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def radar_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = tmp_path / "radar.db"
    _make_radar_db(db)
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def empty_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = tmp_path / "empty.db"
    db.touch()
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


# ---------------------------------------------------------------------------
# _compute_probability_estimate
# ---------------------------------------------------------------------------


def test_compute_probability_estimate_missing_table_appends_to_missing(
    empty_conn: sqlite3.Connection,
) -> None:
    missing: list[str] = []
    out = intel_mod._compute_probability_estimate(
        empty_conn,
        houjin_bangou="8010001213708",
        program_id="UNI-x",
        missing_tables=missing,
    )
    assert out is None
    assert "am_recommended_programs" in missing


def test_compute_probability_estimate_row_returns_rounded(
    radar_conn: sqlite3.Connection,
) -> None:
    radar_conn.execute(
        "INSERT INTO am_recommended_programs(houjin_bangou, program_unified_id, score) "
        "VALUES (?,?,?)",
        ("8010001213708", "UNI-a", 0.123456789),
    )
    radar_conn.commit()
    missing: list[str] = []
    out = intel_mod._compute_probability_estimate(
        radar_conn,
        houjin_bangou="8010001213708",
        program_id="UNI-a",
        missing_tables=missing,
    )
    assert out == round(0.123456789, 4)
    assert missing == []


def test_compute_probability_estimate_null_score_returns_none(
    radar_conn: sqlite3.Connection,
) -> None:
    radar_conn.execute(
        "INSERT INTO am_recommended_programs(houjin_bangou, program_unified_id, score) "
        "VALUES (?,?,?)",
        ("8010001213708", "UNI-b", None),
    )
    radar_conn.commit()
    missing: list[str] = []
    assert (
        intel_mod._compute_probability_estimate(
            radar_conn,
            houjin_bangou="8010001213708",
            program_id="UNI-b",
            missing_tables=missing,
        )
        is None
    )


# ---------------------------------------------------------------------------
# _compute_industry_rate_and_award
# ---------------------------------------------------------------------------


def test_compute_industry_rate_missing_records_table(empty_conn: sqlite3.Connection) -> None:
    missing: list[str] = []
    rate, mean, n = intel_mod._compute_industry_rate_and_award(
        empty_conn,
        houjin_bangou="8010001213708",
        program_id="UNI-x",
        missing_tables=missing,
    )
    assert rate is None and mean is None and n == 0
    assert "jpi_adoption_records" in missing


def test_compute_industry_rate_empty_records(radar_conn: sqlite3.Connection) -> None:
    """Records table exists but empty → 0 count, no mean."""
    missing: list[str] = []
    rate, mean, n = intel_mod._compute_industry_rate_and_award(
        radar_conn,
        houjin_bangou="8010001213708",
        program_id="UNI-empty",
        missing_tables=missing,
    )
    assert n == 0
    assert mean is None
    assert rate is None


def test_compute_industry_rate_with_full_data(radar_conn: sqlite3.Connection) -> None:
    """Seed 5 records (3 in industry 'C', 2 outside) + features → rate = 0.6."""
    radar_conn.executemany(
        "INSERT INTO jpi_adoption_records(program_id, amount_granted_yen, industry_jsic_medium) "
        "VALUES (?,?,?)",
        [
            ("UNI-r", 1_000_000, "C01"),
            ("UNI-r", 2_000_000, "C02"),
            ("UNI-r", 3_000_000, "C03"),
            ("UNI-r", 5_000_000, "E01"),
            ("UNI-r", 4_000_000, "E02"),
        ],
    )
    radar_conn.execute(
        "INSERT INTO am_adopted_company_features(houjin_bangou, dominant_jsic_major) VALUES (?,?)",
        ("8010001213708", "C"),
    )
    radar_conn.commit()
    missing: list[str] = []
    rate, mean, n = intel_mod._compute_industry_rate_and_award(
        radar_conn,
        houjin_bangou="8010001213708",
        program_id="UNI-r",
        missing_tables=missing,
    )
    assert n == 5
    assert mean == 3_000_000  # (1+2+3+5+4)M / 5
    assert rate == 0.6  # 3/5


def test_compute_industry_rate_missing_company_features(radar_conn: sqlite3.Connection) -> None:
    """Records present but no am_adopted_company_features row → rate=None."""
    radar_conn.execute(
        "INSERT INTO jpi_adoption_records(program_id, amount_granted_yen, industry_jsic_medium) "
        "VALUES (?,?,?)",
        ("UNI-r", 1_000_000, "C01"),
    )
    radar_conn.commit()
    missing: list[str] = []
    rate, mean, n = intel_mod._compute_industry_rate_and_award(
        radar_conn,
        houjin_bangou="missing_houjin",
        program_id="UNI-r",
        missing_tables=missing,
    )
    assert n == 1
    assert mean == 1_000_000
    assert rate is None  # houjin's dominant_jsic_major not found


# ---------------------------------------------------------------------------
# _build_evidence_packets
# ---------------------------------------------------------------------------


def test_build_evidence_packets_missing_table(empty_conn: sqlite3.Connection) -> None:
    assert intel_mod._build_evidence_packets(empty_conn, program_id="UNI-x") == []


def test_build_evidence_packets_empty_table(radar_conn: sqlite3.Connection) -> None:
    assert intel_mod._build_evidence_packets(radar_conn, program_id="UNI-x") == []


def test_build_evidence_packets_distinct_urls(radar_conn: sqlite3.Connection) -> None:
    radar_conn.executemany(
        "INSERT INTO jpi_adoption_records(program_id, source_url) VALUES (?,?)",
        [
            ("UNI-r", "https://a.gov/x"),
            ("UNI-r", "https://b.gov/y"),
            ("UNI-r", "https://a.gov/x"),  # dup → DISTINCT removes
            ("UNI-r", None),  # NULL skipped by WHERE
        ],
    )
    radar_conn.commit()
    out = intel_mod._build_evidence_packets(radar_conn, program_id="UNI-r", limit=10)
    urls = {p["source_url"] for p in out}
    assert urls == {"https://a.gov/x", "https://b.gov/y"}
    assert all(p["kind"] == "adoption_record" for p in out)
    assert all(p["program_id"] == "UNI-r" for p in out)


# ---------------------------------------------------------------------------
# _eligibility_gaps_for + _next_questions_for
# ---------------------------------------------------------------------------


def _req(
    *,
    capital_jpy: int | None = None,
    employee_count: int | None = None,
    keyword: str | None = None,
) -> IntelMatchRequest:
    return IntelMatchRequest(
        industry_jsic_major="E",
        prefecture_code="13",
        capital_jpy=capital_jpy,
        employee_count=employee_count,
        keyword=keyword,
    )


def test_eligibility_gaps_emits_capital_and_employee_gaps_when_missing() -> None:
    payload = _req()
    predicate: dict[str, Any] = {
        "target_types": [],
        "funding_purpose": [],
        "application_window": {},
        "industry_jsic_majors": [],
        "prefecture": None,
    }
    gaps = intel_mod._eligibility_gaps_for(payload=payload, predicate=predicate)
    fields = {g["field"] for g in gaps}
    assert "capital_jpy" in fields
    assert "employee_count" in fields


def test_eligibility_gaps_emits_target_funding_when_predicate_lists_them() -> None:
    payload = _req(capital_jpy=1_000_000, employee_count=5)
    predicate: dict[str, Any] = {
        "target_types": ["sme"],
        "funding_purpose": ["dx"],
        "application_window": {},
        "industry_jsic_majors": [],
        "prefecture": None,
    }
    gaps = intel_mod._eligibility_gaps_for(payload=payload, predicate=predicate)
    fields = {g["field"] for g in gaps}
    assert "entity_type" in fields
    assert "funding_purpose" in fields


def test_next_questions_emits_q_for_each_missing_input() -> None:
    payload = _req()
    predicate: dict[str, Any] = {
        "target_types": [],
        "funding_purpose": [],
        "application_window": {},
        "industry_jsic_majors": [],
        "prefecture": None,
    }
    gaps = intel_mod._eligibility_gaps_for(payload=payload, predicate=predicate)
    qs = intel_mod._next_questions_for(
        payload=payload,
        predicate=predicate,
        eligibility_gaps=gaps,
        required_documents=[
            {"form_type": "required", "form_name": "事業計画書"},
            {"form_type": "optional", "form_name": "任意添付"},
        ],
    )
    qids = {q["id"] for q in qs}
    # employee_count + capital_jpy + 1 required doc.
    assert "employee_count" in qids
    assert "capital_jpy" in qids
    # The single non-optional doc → one document_readiness question.
    assert any(q["kind"] == "document_readiness" for q in qs)


# ---------------------------------------------------------------------------
# _seal_source_urls_for_epid + _enrich_with_am_source
# ---------------------------------------------------------------------------


def test_seal_source_urls_missing_table_returns_empty(empty_conn: sqlite3.Connection) -> None:
    assert intel_mod._seal_source_urls_for_epid(empty_conn, "evp_xxxx") == []


def test_seal_source_urls_parses_json_column(tmp_path: Path) -> None:
    db = tmp_path / "seals.db"
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE audit_seals (source_urls_json TEXT, ts TEXT)")
    c.execute(
        "INSERT INTO audit_seals(source_urls_json, ts) VALUES (?,?)",
        (
            '["https://nta.go.jp/x?epid=evp_aa", "https://maff.go.jp/y?epid=evp_aa"]',
            "2026-05-17T00:00:00Z",
        ),
    )
    c.commit()
    out = intel_mod._seal_source_urls_for_epid(c, "evp_aa")
    urls = {e["url"] for e in out}
    assert "https://nta.go.jp/x?epid=evp_aa" in urls
    assert "https://maff.go.jp/y?epid=evp_aa" in urls
    assert all(e["fetched_at"] == "2026-05-17T00:00:00Z" for e in out)
    c.close()


def test_enrich_with_am_source_unknown_url_keeps_null_hash(radar_conn: sqlite3.Connection) -> None:
    """Unknown URLs in am_source surface as null content_hash + preserve url."""
    seal_urls = [{"url": "https://unknown.gov/x", "fetched_at": "2026-05-17"}]
    enriched = intel_mod._enrich_with_am_source(radar_conn, seal_urls)
    assert len(enriched) == 1
    assert enriched[0]["url"] == "https://unknown.gov/x"
    assert enriched[0]["content_hash"] is None


def test_enrich_with_am_source_known_url_carries_hash(radar_conn: sqlite3.Connection) -> None:
    radar_conn.execute(
        "INSERT INTO am_source(source_url, content_hash, last_verified) VALUES (?,?,?)",
        ("https://nta.go.jp/x", "sha256:abc", "2026-05-16"),
    )
    radar_conn.commit()
    out = intel_mod._enrich_with_am_source(
        radar_conn,
        [{"url": "https://nta.go.jp/x", "fetched_at": "2026-05-15"}],
    )
    assert out[0]["content_hash"] == "sha256:abc"
    assert out[0]["fetched_at"] == "2026-05-16"  # last_verified wins


# ---------------------------------------------------------------------------
# _audit_proof_for graceful degradation
# ---------------------------------------------------------------------------


def test_audit_proof_for_empty_unified_id_returns_stub() -> None:
    assert intel_mod._audit_proof_for("") == {"merkle_root": None, "ots_url": None}


def test_audit_proof_for_no_anchor_returns_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When autonomath has the leaf table but no rows, returns stub."""

    def _mock_open() -> sqlite3.Connection:
        db = tmp_path / "am.db"
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        c.execute(
            "CREATE TABLE audit_merkle_leaves (epid TEXT, daily_date TEXT, leaf_index INTEGER, "
            "leaf_hash TEXT)"
        )
        c.commit()
        return c

    monkeypatch.setattr(intel_mod, "_open_autonomath_rw", _mock_open)
    out = intel_mod._audit_proof_for("UNI-x")
    assert out == {"merkle_root": None, "ots_url": None}


# ---------------------------------------------------------------------------
# _open_intel_match_autonomath_ro
# ---------------------------------------------------------------------------


def test_open_intel_match_autonomath_ro_missing_file_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When autonomath_db_path does not exist, helper returns None."""
    from jpintel_mcp import config

    monkeypatch.setattr(
        config.settings,
        "autonomath_db_path",
        tmp_path / "does_not_exist.db",
    )
    assert intel_mod._open_intel_match_autonomath_ro() is None
