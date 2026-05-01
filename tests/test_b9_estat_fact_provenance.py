from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_estat_fact_provenance as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE,
            domain TEXT
        );
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            source_topic TEXT,
            primary_name TEXT NOT NULL,
            source_url TEXT,
            source_url_domain TEXT
        );
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            source_id INTEGER
        );
        """
    )
    return conn


def _insert_estat_entity(conn: sqlite3.Connection, entity_id: str, source_url: str) -> None:
    conn.execute(
        """INSERT INTO am_entities(
               canonical_id, record_kind, source_topic, primary_name,
               source_url, source_url_domain
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            entity_id,
            "statistic",
            backfill.ESTAT_INDUSTRY_TOPIC,
            "e-Stat industry row",
            source_url,
            "e-stat.go.jp",
        ),
    )


def test_normalize_source_url_keeps_query_and_strips_fragment() -> None:
    assert backfill.normalize_source_url(
        "HTTPS://WWW.E-STAT.GO.JP/path/%E7%B5%B1%E8%A8%88/?a=1#section"
    ) == "https://www.e-stat.go.jp/path/統計?a=1"


def test_dry_run_reports_assignments_without_updating() -> None:
    conn = _build_db()
    source_url = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=1&fileKind=0"
    conn.execute(
        "INSERT INTO am_source(id, source_url, domain) VALUES (?, ?, ?)",
        (100, source_url, "www.e-stat.go.jp"),
    )
    _insert_estat_entity(conn, "stat:one", source_url)
    conn.executemany(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, source_id) VALUES (?, ?, ?, ?)",
        [(1, "stat:one", "region_name", None), (2, "stat:one", "employee_count", None)],
    )

    result = backfill.backfill_estat_fact_provenance(conn, apply=False)

    assert result["candidate_assignments"] == 2
    assert result["updated_rows"] == 0
    assert result["method_counts"] == {"entity_source_url_exact": 2}
    assert conn.execute(
        "SELECT COUNT(*) FROM am_entity_facts WHERE source_id IS NULL"
    ).fetchone()[0] == 2


def test_apply_updates_only_limited_estat_industry_rows() -> None:
    conn = _build_db()
    source_url = "https://www.e-stat.go.jp/stat-search/file-download?statInfId=1&fileKind=0"
    conn.execute(
        "INSERT INTO am_source(id, source_url, domain) VALUES (?, ?, ?)",
        (100, source_url, "www.e-stat.go.jp"),
    )
    _insert_estat_entity(conn, "stat:one", source_url)
    conn.execute(
        """INSERT INTO am_entities(
               canonical_id, record_kind, source_topic, primary_name,
               source_url, source_url_domain
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "program:one",
            "program",
            backfill.ESTAT_INDUSTRY_TOPIC,
            "not statistic",
            source_url,
            "e-stat.go.jp",
        ),
    )
    conn.executemany(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, source_id) VALUES (?, ?, ?, ?)",
        [
            (1, "stat:one", "region_name", None),
            (2, "stat:one", "employee_count", None),
            (3, "stat:one", "already_done", 100),
            (4, "program:one", "not_touched", None),
        ],
    )

    result = backfill.backfill_estat_fact_provenance(
        conn,
        apply=True,
        limit=1,
        batch_size=1,
    )

    assert result["candidate_assignments"] == 1
    assert result["updated_rows"] == 1
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 1").fetchone()[0] == 100
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 2").fetchone()[0] is None
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 4").fetchone()[0] is None


def test_normalized_url_match_requires_unambiguous_estat_source() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain) VALUES (?, ?, ?)",
        [
            (100, "https://www.e-stat.go.jp/stat-search/files/", "www.e-stat.go.jp"),
            (200, "https://example.go.jp/stat-search/files", "example.go.jp"),
        ],
    )
    _insert_estat_entity(conn, "stat:one", "https://www.e-stat.go.jp/stat-search/files")
    conn.execute(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, source_id) VALUES (?, ?, ?, ?)",
        (1, "stat:one", "region_name", None),
    )

    result = backfill.backfill_estat_fact_provenance(conn, apply=True)

    assert result["updated_rows"] == 1
    assert result["method_counts"] == {"entity_source_url_normalized": 1}
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 1").fetchone()[0] == 100


def test_domain_guard_skips_non_estat_entities() -> None:
    conn = _build_db()
    source_url = "https://www.e-stat.go.jp/stat-search/files"
    conn.execute(
        "INSERT INTO am_source(id, source_url, domain) VALUES (?, ?, ?)",
        (100, source_url, "www.e-stat.go.jp"),
    )
    conn.execute(
        """INSERT INTO am_entities(
               canonical_id, record_kind, source_topic, primary_name,
               source_url, source_url_domain
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "stat:one",
            "statistic",
            backfill.ESTAT_INDUSTRY_TOPIC,
            "wrong domain",
            source_url,
            "example.go.jp",
        ),
    )
    conn.execute(
        "INSERT INTO am_entity_facts(id, entity_id, field_name, source_id) VALUES (?, ?, ?, ?)",
        (1, "stat:one", "region_name", None),
    )

    result = backfill.backfill_estat_fact_provenance(conn, apply=True)

    assert result["candidate_assignments"] == 0
    assert result["updated_rows"] == 0
    assert conn.execute("SELECT source_id FROM am_entity_facts WHERE id = 1").fetchone()[0] is None
