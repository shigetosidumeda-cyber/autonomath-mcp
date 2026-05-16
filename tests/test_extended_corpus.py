"""Tests for the Wave 32 extended corpus (Axis 1d+1e+1f).

Coverage:
    * ETL dry-run smoke (no network) — 3 sample fetch each
    * aggregator URL refusal — banned hosts are rejected
    * migration 228/229/230 schema invariants applied to a temp DB

NO LLM. Pure stdlib + sqlite3.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ETL = REPO_ROOT / "scripts" / "etl"
SCRIPTS_MIG = REPO_ROOT / "scripts" / "migrations"

# Ensure scripts/etl is importable for the dry-run modules.
sys.path.insert(0, str(SCRIPTS_ETL))


@pytest.fixture
def fresh_autonomath_db():
    """Build a fresh autonomath.db with migrations 228+229+230 applied + a
    minimal nta_tsutatsu_index stub so the tsutatsu ETL has a parent table."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        # nta_tsutatsu_index stub (subset of mig 103 schema) — required by
        # the tsutatsu extended ETL bulk path.
        conn.executescript(
            """
            CREATE TABLE nta_tsutatsu_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                law_canonical_id TEXT NOT NULL,
                article_number TEXT NOT NULL,
                title TEXT,
                body_excerpt TEXT,
                parent_code TEXT,
                source_url TEXT NOT NULL,
                last_amended TEXT,
                refreshed_at TEXT NOT NULL
            );
            INSERT INTO nta_tsutatsu_index (code, law_canonical_id, article_number, source_url, refreshed_at)
            VALUES
              ('法基通-9-2-3', 'law:hojin-zei', '9-2-3', 'https://www.nta.go.jp/law/tsutatsu/houjin/09/09_02_03.htm', '2026-05-12'),
              ('所基通-36-1',  'law:shotoku-zei', '36-1', 'https://www.nta.go.jp/law/tsutatsu/shotoku/36/01.htm', '2026-05-12'),
              ('消基通-5-1-1', 'law:shohi-zei',   '5-1-1', 'https://www.nta.go.jp/law/tsutatsu/shohi/05/01_01.htm', '2026-05-12');
            """
        )
        conn.commit()

        for fname in (
            "228_court_decisions_extended.sql",
            "229_industry_guidelines.sql",
            "230_nta_tsutatsu_extended.sql",
        ):
            sql = (SCRIPTS_MIG / fname).read_text()
            conn.executescript(sql)
        conn.commit()
        conn.close()
        yield Path(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Migration invariants
# --------------------------------------------------------------------------


def test_migration_228_tables(fresh_autonomath_db):
    conn = sqlite3.connect(fresh_autonomath_db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_court_decisions_extended%'"
        )
    }
    assert "am_court_decisions_extended" in tables
    # FTS5 shadow tables present
    assert "am_court_decisions_extended_fts" in tables
    # CHECK constraint rejects invalid court_level
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_court_decisions_extended "
            "(unified_id, court_level, case_type, source_url, ingested_at) "
            "VALUES ('HAN-test000001', 'invalid_level', 'tax', 'https://example.gov', '2026-05-12')"
        )
    conn.close()


def test_migration_229_tables(fresh_autonomath_db):
    conn = sqlite3.connect(fresh_autonomath_db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_industry_guidelines%'"
        )
    }
    assert "am_industry_guidelines" in tables
    assert "am_industry_guidelines_fts" in tables
    # CHECK constraint rejects bogus ministry
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO am_industry_guidelines "
            "(guideline_id, ministry, title, source_url, ingested_at) "
            "VALUES ('GL-test00001', 'bogus_ministry', 't', 'https://example.gov', '2026-05-12')"
        )
    conn.close()


def test_migration_230_tables(fresh_autonomath_db):
    conn = sqlite3.connect(fresh_autonomath_db)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_nta_tsutatsu_extended%'"
        )
    }
    assert "am_nta_tsutatsu_extended" in tables
    assert "am_nta_tsutatsu_extended_fts" in tables
    # View should exist
    views = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='v_am_nta_tsutatsu_sections'"
        )
    }
    assert "v_am_nta_tsutatsu_sections" in views
    conn.close()


# --------------------------------------------------------------------------
# ETL dry-run smoke (Axis 1d/1e/1f, 10 sample target each)
# --------------------------------------------------------------------------


def test_dry_run_court_decisions_extended(fresh_autonomath_db, capsys):
    import importlib

    mod = importlib.import_module("ingest_court_decisions_extended")
    rc = mod.main(["--db-path", str(fresh_autonomath_db), "--dry-run", "--max-records", "10"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run] done" in captured.out


def test_dry_run_industry_guidelines(fresh_autonomath_db, capsys):
    import importlib

    mod = importlib.import_module("ingest_industry_guidelines")
    rc = mod.main(
        [
            "--db-path",
            str(fresh_autonomath_db),
            "--ministries",
            "env,maff,mhlw",
            "--max-per-ministry",
            "3",
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run] done" in captured.out


def test_dry_run_nta_tsutatsu_extended(fresh_autonomath_db, capsys):
    import importlib

    mod = importlib.import_module("ingest_nta_tsutatsu_extended")
    rc = mod.main(
        [
            "--db-path",
            str(fresh_autonomath_db),
            "--tsutatsu-code",
            "法基通-9-2-3",
            "--max-tsutatsu",
            "3",
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run] done" in captured.out


# --------------------------------------------------------------------------
# Aggregator URL refusal — verify all 3 ETLs share the banned host list
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    [
        "ingest_court_decisions_extended",
        "ingest_industry_guidelines",
        "ingest_nta_tsutatsu_extended",
    ],
)
def test_banned_aggregator_urls_refused(module_name):
    import importlib

    mod = importlib.import_module(module_name)
    assert hasattr(mod, "BANNED_SOURCE_HOSTS")
    banned_examples = [
        "https://noukaweb.com/foo",
        "https://hojyokin-portal.jp/bar",
        "https://biz.stayway.jp/baz",
    ]
    for url in banned_examples:
        assert mod.is_banned_url(url) is True, f"{module_name} accepted banned url: {url}"

    # Primary sources must be accepted
    primaries = [
        "https://www.courts.go.jp/app/hanrei_jp/x",
        "https://dl.ndl.go.jp/oai/foo",
        "https://www.env.go.jp/policy/",
        "https://www.maff.go.jp/j/guide/",
        "https://www.nta.go.jp/law/tsutatsu/x.htm",
    ]
    for url in primaries:
        assert mod.is_banned_url(url) is False, f"{module_name} rejected primary url: {url}"


# --------------------------------------------------------------------------
# REST endpoint sanity — module import + route registration
# --------------------------------------------------------------------------


def test_extended_corpus_router_routes():
    """Verify the REST router exposes the 3 spec'd endpoints."""
    # Import lazily so the test runs even if downstream dependencies
    # are unavailable in the test env.
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from jpintel_mcp.api.extended_corpus import router  # type: ignore

    paths = [r.path for r in router.routes]
    assert "/v1/court/decisions/extended" in paths
    assert "/v1/industry/guidelines" in paths
    assert "/v1/nta/tsutatsu/{tsutatsu_id}/sections" in paths


def test_court_decisions_unified_id_pattern():
    """Sanity: unified_id derivation is stable + 14-char prefix-matched."""
    import importlib

    mod = importlib.import_module("ingest_court_decisions_extended")
    uid = mod.compute_unified_id("平成29年(行ヒ)第123号", "最高裁判所第三小法廷")
    assert uid.startswith("HAN-")
    assert len(uid) == 14
    # Determinism check
    assert mod.compute_unified_id("平成29年(行ヒ)第123号", "最高裁判所第三小法廷") == uid


def test_industry_jsic_classification():
    """JSIC keyword override correctly remaps METI 建設 → JSIC F."""
    import importlib

    mod = importlib.import_module("ingest_industry_guidelines")
    code, label = mod.classify_jsic("meti", "建設業向け省エネガイドライン")
    assert code == "F"
    assert "建設" in label

    # No keyword → ministry default
    code2, _ = mod.classify_jsic("maff", "輸出促進ガイドライン")
    assert code2 == "A"  # MAFF default


def test_nta_tsutatsu_canonical_law_id():
    """法基通 prefix maps to law:hojin-zei."""
    import importlib

    mod = importlib.import_module("ingest_nta_tsutatsu_extended")
    assert mod.canonical_law_id("法基通-9-2-3") == "law:hojin-zei"
    assert mod.canonical_law_id("所基通-36-1") == "law:shotoku-zei"
    assert mod.canonical_law_id("消基通-5-1-1") == "law:shohi-zei"
    assert mod.canonical_law_id("unknown-prefix") is None
