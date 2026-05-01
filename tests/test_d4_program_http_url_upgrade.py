from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import upgrade_program_http_urls as upgrade  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            source_url TEXT,
            official_url TEXT,
            source_url_corrected_at TEXT
        );
        """
    )
    return conn


def test_upgrade_url_only_allows_public_sector_hosts() -> None:
    assert upgrade.upgrade_url("http://www.city.foo.lg.jp/a") == (
        "https://www.city.foo.lg.jp/a",
        "www.city.foo.lg.jp",
    )
    assert upgrade.upgrade_url("http://www.meti.go.jp/a?x=1") == (
        "https://www.meti.go.jp/a?x=1",
        "www.meti.go.jp",
    )
    assert upgrade.upgrade_url("http://www.example.or.jp/a") == (None, None)
    assert upgrade.upgrade_url("https://www.meti.go.jp/a") == (None, None)


def test_backfill_program_https_urls_updates_safe_columns_only() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO programs(unified_id, source_url, official_url) VALUES (?, ?, ?)",
        [
            (
                "UNI-1",
                "http://www.city.foo.lg.jp/a",
                "http://www.city.foo.lg.jp/a",
            ),
            (
                "UNI-2",
                "http://www.example.or.jp/a",
                "http://www.example.or.jp/a",
            ),
        ],
    )

    result = upgrade.backfill_program_https_urls(conn, apply=True)

    assert result["updated_cells"] == 2
    row1 = conn.execute(
        "SELECT source_url, official_url, source_url_corrected_at "
        "FROM programs WHERE unified_id='UNI-1'"
    ).fetchone()
    assert row1["source_url"] == "https://www.city.foo.lg.jp/a"
    assert row1["official_url"] == "https://www.city.foo.lg.jp/a"
    assert row1["source_url_corrected_at"]
    row2 = conn.execute(
        "SELECT source_url, official_url FROM programs WHERE unified_id='UNI-2'"
    ).fetchone()
    assert row2["source_url"] == "http://www.example.or.jp/a"
    assert row2["official_url"] == "http://www.example.or.jp/a"


def test_backfill_program_https_urls_is_idempotent() -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs(unified_id, source_url, official_url) VALUES (?, ?, ?)",
        ("UNI-1", "http://www.meti.go.jp/a", "https://www.meti.go.jp/a"),
    )

    first = upgrade.backfill_program_https_urls(conn, apply=True)
    second = upgrade.backfill_program_https_urls(conn, apply=True)

    assert first["updated_cells"] == 1
    assert second["candidate_updates"] == 0
    assert second["updated_cells"] == 0
