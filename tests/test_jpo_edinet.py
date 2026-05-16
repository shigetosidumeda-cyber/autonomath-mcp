"""Wave 31 Axis 1b+1c — JPO 特許 + EDINET 全文 ingest schema + ETL contract tests.

Validates:

  * migration 226 schema lands (am_jpo_patents + am_jpo_utility_models +
    views v_jpo_patents_resolved + v_jpo_utility_models_resolved).
  * migration 227 schema lands (am_edinet_filings + 2 views).
  * ETL row builders produce schema-conformant rows.
  * 5 sample rows can be inserted into each table without CHECK failures.
  * houjin_master-style join works against am_jpo_patents.
  * LLM imports remain zero in the new files (delegated to the global
    `test_no_llm_in_production.py` guard — this test file does NOT
    import any LLM SDK).

These are pure schema + helper unit tests — no live HTTP fetches.
"""

from __future__ import annotations

import importlib
import pathlib
import sqlite3
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MIG_226 = REPO_ROOT / "scripts" / "migrations" / "226_jpo_patents.sql"
MIG_227 = REPO_ROOT / "scripts" / "migrations" / "227_edinet_full.sql"


# Ensure scripts/ETL modules are importable for this test only.
_SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: pathlib.Path) -> sqlite3.Connection:
    """Fresh in-process SQLite seeded with migrations 226 + 227 + a small
    houjin_master stub so cross-table joins are exercisable.
    """
    db_path = tmp_path / "jpo_edinet.db"
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    c.executescript(MIG_226.read_text())
    c.executescript(MIG_227.read_text())

    # Minimal houjin_master stub (mig 014 family in prod has a much wider
    # schema; this test only joins on houjin_bangou + name).
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS houjin_master (
            houjin_bangou TEXT PRIMARY KEY,
            name          TEXT NOT NULL
        );
        INSERT OR REPLACE INTO houjin_master(houjin_bangou, name) VALUES
            ('8010001213708', 'Bookyou株式会社'),
            ('1234567890123', 'テスト法人A'),
            ('9876543210987', 'テスト法人B');
        """
    )
    c.commit()
    return c


def _ingest_jpo():
    return importlib.import_module("etl.ingest_jpo_patents")


def _ingest_edinet():
    return importlib.import_module("cron.ingest_edinet_daily")


# ---------------------------------------------------------------------------
# Schema landing
# ---------------------------------------------------------------------------


def test_mig_226_tables_landed(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_jpo_%' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert names == ["am_jpo_patents", "am_jpo_utility_models"], names


def test_mig_226_views_landed(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'v_jpo_%' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "v_jpo_patents_resolved" in names
    assert "v_jpo_utility_models_resolved" in names


def test_mig_227_table_landed(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_edinet_filings'"
    ).fetchall()
    assert len(rows) == 1


def test_mig_227_views_landed(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE 'v_edinet_filings_full_%' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "v_edinet_filings_full_resolved" in names
    assert "v_edinet_filings_full_unresolved" in names


# ---------------------------------------------------------------------------
# JPO ETL helpers
# ---------------------------------------------------------------------------


def test_jpo_parse_minimum_required_fields() -> None:
    mod = _ingest_jpo()
    rec = {
        "application_no": "2024-123456",
        "title": "発明1",
        "application_date": "2024-01-15",
    }
    row = mod.parse_jplatpat_record(rec)
    assert row is not None
    assert row["application_no"] == "2024-123456"
    assert row["title"] == "発明1"
    assert row["status"] == "unknown"
    assert len(row["content_hash"]) == 64


def test_jpo_parse_rejects_invalid_application_no() -> None:
    mod = _ingest_jpo()
    bad = mod.parse_jplatpat_record(
        {"application_no": "garbage", "title": "x", "application_date": "2024-01-01"}
    )
    assert bad is None


def test_jpo_parse_houjin_validation() -> None:
    mod = _ingest_jpo()
    row = mod.parse_jplatpat_record(
        {
            "application_no": "2024-000001",
            "title": "発明",
            "application_date": "2024-01-01",
            "applicant_houjin_bangou": "1234567890123",
        }
    )
    assert row is not None
    assert row["applicant_houjin_bangou"] == "1234567890123"
    bad = mod.parse_jplatpat_record(
        {
            "application_no": "2024-000002",
            "title": "発明",
            "application_date": "2024-01-01",
            "applicant_houjin_bangou": "garbage",
        }
    )
    assert bad is not None
    assert bad["applicant_houjin_bangou"] is None


def test_jpo_insert_five_sample_rows_and_join(conn: sqlite3.Connection) -> None:
    mod = _ingest_jpo()
    samples = [
        {
            "application_no": f"2024-10000{i}",
            "registration_no": f"特許700000{i}" if i % 2 == 0 else None,
            "title": f"発明{i}",
            "applicants": ["Bookyou株式会社"],
            "applicant_houjin_bangou": "8010001213708",
            "ipc_codes": ["G06F 17/30"],
            "ipc_classification": "G06F 17/30",
            "application_date": f"2024-01-0{i + 1}",
            "registration_date": (f"2026-01-0{i + 1}" if i % 2 == 0 else None),
            "status": "registered" if i % 2 == 0 else "published",
            "source_url": f"https://www.j-platpat.inpit.go.jp/c1800/PU/JP-2024-10000{i}/15/ja",
        }
        for i in range(5)
    ]
    inserted = 0
    for s in samples:
        row = mod.parse_jplatpat_record(s)
        assert row is not None, s
        if mod._insert_row(conn, "am_jpo_patents", row, dry_run=False):
            inserted += 1
    conn.commit()
    assert inserted == 5

    # Cross-table join against houjin_master.
    joined = conn.execute(
        """SELECT p.application_no, h.name
             FROM am_jpo_patents p
             JOIN houjin_master h ON h.houjin_bangou = p.applicant_houjin_bangou
            ORDER BY p.application_no"""
    ).fetchall()
    assert len(joined) == 5
    assert all(r["name"] == "Bookyou株式会社" for r in joined)

    # Resolved-view filtering matches the inserted set.
    view = conn.execute("SELECT COUNT(*) AS c FROM v_jpo_patents_resolved").fetchone()
    assert int(view["c"]) == 5


def test_jpo_insert_utility_models_five_rows(conn: sqlite3.Connection) -> None:
    mod = _ingest_jpo()
    inserted = 0
    for i in range(5):
        rec = {
            "application_no": f"2024-20000{i}",
            "title": f"考案{i}",
            "application_date": f"2024-02-0{i + 1}",
            "applicant_houjin_bangou": "1234567890123",
            "applicants": ["テスト法人A"],
            "ipc_codes": ["A01B 1/00"],
            "ipc_classification": "A01B 1/00",
            "source_url": f"https://www.j-platpat.inpit.go.jp/c1800/UM/JP-2024-20000{i}/15/ja",
            "status": "registered",
        }
        row = mod.parse_jplatpat_record(rec)
        assert row is not None
        if mod._insert_row(conn, "am_jpo_utility_models", row, dry_run=False):
            inserted += 1
    conn.commit()
    assert inserted == 5
    count = conn.execute("SELECT COUNT(*) AS c FROM am_jpo_utility_models").fetchone()
    assert int(count["c"]) == 5


# ---------------------------------------------------------------------------
# EDINET ETL helpers
# ---------------------------------------------------------------------------


def test_edinet_parse_minimum_required_fields() -> None:
    mod = _ingest_edinet()
    rec = {
        "docID": "S100ABCD",
        "edinetCode": "E12345",
        "submitDateTime": "2026-05-10 16:00",
        "docTypeCode": "120",
        "JCN": "8010001213708",
        "xbrlFlag": 1,
        "pdfFlag": 1,
        "secCode": "13010",
    }
    row = mod.parse_edinet_record(rec, body_excerpt="abc", full_text_r2_url=None)
    assert row is not None
    assert row["doc_id"] == "S100ABCD"
    assert row["edinet_code"] == "E12345"
    assert row["submit_date"] == "2026-05-10"
    assert row["security_code"] == "13010"
    assert row["filer_houjin_bangou"] == "8010001213708"
    assert row["file_xbrl_url"].startswith("https://disclosure2.edinet-fsa.go.jp")
    assert row["body_text_excerpt"] == "abc"
    assert row["full_text_r2_url"] is None
    assert len(row["content_hash"]) == 64
    assert len(row["filing_id"]) == 40  # sha1 hex


def test_edinet_parse_rejects_missing_doc_id() -> None:
    mod = _ingest_edinet()
    assert mod.parse_edinet_record({}, body_excerpt="", full_text_r2_url=None) is None


def test_edinet_xbrl_to_excerpt_smoke() -> None:
    """xbrl_zip_to_excerpt on an empty payload returns empty string (no crash)."""
    mod = _ingest_edinet()
    assert mod.xbrl_zip_to_excerpt(b"") == ""
    assert mod.xbrl_zip_to_excerpt(b"not-a-zip") == ""


def test_edinet_insert_five_sample_rows_and_join(conn: sqlite3.Connection) -> None:
    mod = _ingest_edinet()
    samples = [
        {
            "docID": f"S100ABC{i}",
            "edinetCode": "E12345",
            "submitDateTime": f"2026-05-0{i + 1} 16:00",
            "docTypeCode": "120" if i % 2 == 0 else "350",
            "JCN": "8010001213708",
            "xbrlFlag": 1,
            "pdfFlag": 1,
            "secCode": "13010",
        }
        for i in range(5)
    ]
    inserted = 0
    for s in samples:
        row = mod.parse_edinet_record(
            s, body_excerpt=f"excerpt-{s['docID']}", full_text_r2_url=None
        )
        assert row is not None, s
        if mod._insert_row(conn, row, dry_run=False):
            inserted += 1
    conn.commit()
    assert inserted == 5

    # Cross-table join against houjin_master.
    joined = conn.execute(
        """SELECT f.doc_id, h.name
             FROM am_edinet_filings f
             JOIN houjin_master h ON h.houjin_bangou = f.filer_houjin_bangou
            ORDER BY f.doc_id"""
    ).fetchall()
    assert len(joined) == 5
    assert all(r["name"] == "Bookyou株式会社" for r in joined)

    resolved = conn.execute("SELECT COUNT(*) AS c FROM v_edinet_filings_full_resolved").fetchone()
    assert int(resolved["c"]) == 5


# ---------------------------------------------------------------------------
# Honesty contract — no LLM imports in the new files.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "scripts/etl/ingest_jpo_patents.py",
        "scripts/cron/ingest_edinet_daily.py",
        "src/jpintel_mcp/api/jpo.py",
        "src/jpintel_mcp/api/edinet.py",
    ],
)
def test_no_llm_imports(rel_path: str) -> None:
    blob = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    for forbidden in ("anthropic", "openai", "google.generativeai", "claude_agent_sdk"):
        assert f"import {forbidden}" not in blob, rel_path
        assert f"from {forbidden}" not in blob, rel_path
