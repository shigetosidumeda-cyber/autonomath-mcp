"""Tests for AnalyticsRecorderMiddleware (P0-10, 2026-04-30).

Confirms that the middleware writes one ``analytics_events`` row per
HTTP request — including the 99% anonymous tail that ``usage_events``
cannot capture (FK + NOT NULL on key_hash).

Per CLAUDE.md "What NOT to do": NO mocked DB. We use the real seeded_db
fixture and inspect the row that the middleware committed.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _count_analytics_for_path(db_path: Path, path: str) -> int:
    c = sqlite3.connect(db_path)
    try:
        return int(
            c.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE path = ?",
                (path,),
            ).fetchone()[0]
        )
    finally:
        c.close()


def _clear_analytics(db_path: Path) -> None:
    c = sqlite3.connect(db_path)
    try:
        c.execute("DELETE FROM analytics_events")
        c.commit()
    finally:
        c.close()


def test_analytics_events_table_exists(seeded_db: Path) -> None:
    """Migration 111 (also embedded in schema.sql) creates the table."""
    c = sqlite3.connect(seeded_db)
    try:
        cols = {row[1] for row in c.execute("PRAGMA table_info(analytics_events)")}
    finally:
        c.close()
    expected = {
        "id",
        "ts",
        "method",
        "path",
        "status",
        "latency_ms",
        "key_hash",
        "anon_ip_hash",
        "client_tag",
        "is_anonymous",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_anon_search_records_one_analytics_row(
    client: TestClient, seeded_db: Path
) -> None:
    """A single anonymous GET /v1/programs/search must persist exactly
    one analytics_events row with is_anonymous=1, status=200, NULL
    key_hash, non-NULL anon_ip_hash."""
    _clear_analytics(seeded_db)

    r = client.get("/v1/programs/search", params={"limit": 5})
    assert r.status_code == 200

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT * FROM analytics_events WHERE path = ? ORDER BY id",
            ("/v1/programs/search",),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1, (
        f"Expected exactly 1 analytics_events row, got {len(rows)}: "
        f"{[dict(r) for r in rows]}"
    )
    row = rows[0]
    assert row["method"] == "GET"
    assert row["path"] == "/v1/programs/search"
    assert row["status"] == 200
    assert row["latency_ms"] is not None
    assert row["latency_ms"] >= 0
    assert row["is_anonymous"] == 1
    assert row["key_hash"] is None
    # anon_ip_hash is best-effort; the TestClient yields client.host
    # "testclient" which still produces a non-NULL hash.
    assert row["anon_ip_hash"] is not None


def test_authenticated_request_records_key_hash(
    client: TestClient, seeded_db: Path, paid_key: str
) -> None:
    """An authenticated GET should record key_hash, is_anonymous=0,
    NULL anon_ip_hash."""
    _clear_analytics(seeded_db)

    r = client.get(
        "/v1/programs/search",
        params={"limit": 1},
        headers={"X-API-Key": paid_key},
    )
    assert r.status_code == 200

    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT * FROM analytics_events WHERE path = ? ORDER BY id",
            ("/v1/programs/search",),
        ).fetchall()
    finally:
        c.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["is_anonymous"] == 0
    assert row["key_hash"] is not None
    assert row["anon_ip_hash"] is None


def test_health_path_excluded(
    client: TestClient, seeded_db: Path
) -> None:
    """/healthz must NOT generate analytics_events rows — health probes
    would dominate the table without adding signal."""
    _clear_analytics(seeded_db)

    r = client.get("/healthz")
    # Status doesn't matter; just that no row was written.
    assert r.status_code in (200, 503)

    assert _count_analytics_for_path(seeded_db, "/healthz") == 0


def test_multiple_requests_aggregate_correctly(
    client: TestClient, seeded_db: Path
) -> None:
    """N requests => N rows. This is the primary launch-blocker check
    behind P0-10: analytics dashboards counted 0 in production because
    no middleware persisted the universe of traffic."""
    _clear_analytics(seeded_db)

    for _ in range(3):
        r = client.get("/v1/programs/search", params={"limit": 1})
        assert r.status_code == 200

    assert _count_analytics_for_path(seeded_db, "/v1/programs/search") == 3
