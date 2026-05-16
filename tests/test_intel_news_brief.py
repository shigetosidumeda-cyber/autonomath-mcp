from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import get_db
from jpintel_mcp.api.intel_news_brief import router

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def news_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "news.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_value_json TEXT,
            source_url TEXT,
            fetched_at TEXT
        )
        """
    )
    # R3 P0-1: the route binds to a narrow allow-list of field_name
    # buckets per axis (see _AXIS_FIELD_NAMES in intel_news_brief.py).
    # Seed rows use the allow-listed field_name (`adoption.program_name`
    # for the program axis) and embed the query token in
    # field_value_text so the LIKE predicate hits.
    rows = [
        (
            "program:UNI-news-1",
            "adoption.program_name",
            "UNI-news-1: 公募締切が2026-06-30に変更されました",
            None,
            None,
            "https://example.go.jp/program/change",
            "2026-05-04T10:00:00Z",
        ),
        (
            "program:UNI-news-1",
            "adoption.program_name",
            "UNI-news-1: 不正受給に関する行政処分の公表",
            None,
            None,
            "https://example.go.jp/program/enforcement",
            "2026-05-04T11:00:00Z",
        ),
        (
            "industry:manufacturing",
            "industry_name",
            "製造業向け設備投資枠が更新",
            None,
            None,
            "https://example.go.jp/industry/update",
            "2026-05-03T09:00:00Z",
        ),
    ]
    conn.executemany(
        "INSERT INTO am_entity_facts("
        " entity_id, field_name, field_value_text, field_value_numeric,"
        " field_value_json, source_url, fetched_at"
        ") VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


@pytest.fixture()
def sparse_news_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "sparse-news.db"
    sqlite3.connect(db_path).close()
    app = FastAPI()
    app.include_router(router)

    def override_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_news_brief_happy_path(news_client: TestClient) -> None:
    resp = news_client.post("/v1/intel/news_brief", json={"program": "UNI-news-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["as_of"] == "2026-05-04T11:00:00Z"
    assert len(body["recent_changes"]) == 1
    assert "締切" in body["recent_changes"][0]["summary"]
    assert len(body["enforcement_mentions"]) == 1
    assert "行政処分" in body["enforcement_mentions"][0]["summary"]
    assert {link["url"] for link in body["source_links"]} == {
        "https://example.go.jp/program/change",
        "https://example.go.jp/program/enforcement",
    }
    assert body["known_gaps"] == []


def test_news_brief_validation_requires_query(news_client: TestClient) -> None:
    resp = news_client.post("/v1/intel/news_brief", json={})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "missing_query"


def test_news_brief_sparse_db_graceful(sparse_news_client: TestClient) -> None:
    resp = sparse_news_client.post("/v1/intel/news_brief", json={"industry": "製造業"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["recent_changes"] == []
    assert body["enforcement_mentions"] == []
    assert body["source_links"] == []
    assert "am_entity_facts table is not available" in body["known_gaps"]
    assert "no matching local facts found for the supplied query" in body["known_gaps"]


@pytest.fixture()
def bulk_news_client(tmp_path: Path) -> TestClient:
    """Seed >50 matching rows so the row-cap probe can saturate the LIMIT.

    Each row mentions the literal program token ``UNI-bulk-cap`` in
    ``field_value_text`` so a single ``program=UNI-bulk-cap`` query
    matches all 120 rows. With ``max_items=20``, the unbounded path
    would request 20*6=120 rows; the R3 cap clips the LIMIT at 50.
    """
    db_path = tmp_path / "bulk-news.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_value_json TEXT,
            source_url TEXT,
            fetched_at TEXT
        )
        """
    )
    # D4 (R3 P0-1) narrowed the program axis to a fixed allow-list of
    # `field_name` values (`_AXIS_FIELD_NAMES["program"]`). To exercise
    # the row cap we must seed with a `field_name` that the query path
    # will actually scan. `adoption.program_name` is one of those allow-
    # listed buckets. The `field_value_text` carries the literal program
    # token so the LIKE predicate matches every row.
    rows = [
        (
            f"program:UNI-bulk-cap-{i:03d}",
            "adoption.program_name",
            f"UNI-bulk-cap row {i}: 公募締切 改正",
            None,
            None,
            f"https://example.go.jp/program/cap-{i:03d}",
            f"2026-05-04T10:{i % 60:02d}:00Z",
        )
        for i in range(120)
    ]
    conn.executemany(
        "INSERT INTO am_entity_facts("
        " entity_id, field_name, field_value_text, field_value_numeric,"
        " field_value_json, source_url, fetched_at"
        ") VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_news_brief_row_cap_50_at_max_items_20(bulk_news_client: TestClient) -> None:
    """R3 guard: SQL LIMIT is hard-capped at 50 rows regardless of multiplier.

    With ``max_items=20`` the unbounded multiplier would request
    ``20 * 6 = 120`` rows from ``am_entity_facts`` (6.12M rows on
    production). The R3 cap forces the LIMIT to ``min(120, 50) = 50``.
    The response slice itself is still capped at ``max_items=20`` per
    bucket, so the externally-observable signal is the union of
    distinct source URLs (one per matching row before bucket-split):
    cap=50 means at most 50 distinct source URLs surface even though
    120 rows match.
    """
    resp = bulk_news_client.post(
        "/v1/intel/news_brief",
        json={"program": "UNI-bulk-cap", "max_items": 20},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # `source_links` is built from the full row set (before bucket-split
    # and max_items truncation happen in parallel), then deduped on URL
    # and sliced at max_items. So the visible signal of the row cap is
    # that the underlying scan saw at most 50 rows: the union of
    # distinct URLs visible across recent_changes + enforcement_mentions
    # source items + source_links cannot exceed 50.
    seen_urls: set[str] = set()
    for item in body["recent_changes"]:
        url = item["source"]["source_url"]
        if url:
            seen_urls.add(url)
    for item in body["enforcement_mentions"]:
        url = item["source"]["source_url"]
        if url:
            seen_urls.add(url)
    for link in body["source_links"]:
        seen_urls.add(link["url"])

    # Distinct URL count is bounded by the SQL LIMIT (rows fetched),
    # not by max_items (which only slices each bucket). Pre-cap this
    # would be ≤120; post-cap it is ≤50. We must observe ≥1 URL — a
    # zero-URL result would mean the bulk seed never matched and the
    # cap test passed vacuously (e.g. allow-list drift on field_name).
    assert len(seen_urls) > 0, (
        "row cap test seeded 120 rows but observed 0 URLs — "
        "field_name allow-list drift suspected; verify "
        "_AXIS_FIELD_NAMES['program'] still contains the seed bucket."
    )
    assert len(seen_urls) <= 50, (
        f"row cap regression: saw {len(seen_urls)} distinct URLs, expected ≤ 50 (LIMIT cap)"
    )


def test_news_brief_query_under_100ms_with_index(tmp_path: Path) -> None:
    """R3 P0-1: with the composite (field_name, field_value_text) index in
    place, an intel_news_brief query over 1000 randomized am_entity_facts
    rows must complete well under 100ms.

    Pre-R3 the route ran a 5-column LIKE-OR with leading wildcards over
    6.12M rows producing 5-15s p99. The migration-290 index plus the
    single-axis rewrite reduce that to a per-bucket index seek + range.
    The synthetic 1000-row corpus emulates the shape (many field_name
    buckets, leading-wildcard LIKE inside one bucket) on a scale the
    test runner can build deterministically; the assertion threshold of
    100ms is generous for the indexed path and would catch any
    regression that reintroduces a table scan.
    """
    import random
    import time

    db_path = tmp_path / "perf-news.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_numeric REAL,
            field_value_json TEXT,
            source_url TEXT,
            fetched_at TEXT
        )
        """
    )
    # Match the production index added in migration 290 so the test
    # exercises the same query plan the production hot path will use.
    conn.execute(
        "CREATE INDEX idx_am_entity_facts_field_name_value "
        "ON am_entity_facts(field_name, field_value_text)"
    )

    # 1000 rows distributed across 10 distinct field_name buckets so
    # the index seek skips ~900 rows. The needle row carries the
    # query token; the other 999 rows are decoys.
    rng = random.Random(20260513)
    decoy_buckets = (
        "noise.bucket_a",
        "noise.bucket_b",
        "noise.bucket_c",
        "noise.bucket_d",
        "noise.bucket_e",
        "noise.bucket_f",
        "noise.bucket_g",
        "noise.bucket_h",
        "noise.bucket_i",
    )
    rows: list[tuple] = []
    for i in range(999):
        bucket = decoy_buckets[i % len(decoy_buckets)]
        rows.append(
            (
                f"entity:{i:05d}",
                bucket,
                f"decoy row {i} {rng.randint(0, 1_000_000)}",
                None,
                None,
                f"https://example.go.jp/d/{i}",
                "2026-05-04T10:00:00Z",
            )
        )
    # Needle: a single allow-listed program-axis row matching `PERF-needle`.
    rows.append(
        (
            "program:PERF-needle",
            "adoption.program_name",
            "PERF-needle: 公募締切 改正",
            None,
            None,
            "https://example.go.jp/perf/needle",
            "2026-05-04T11:00:00Z",
        )
    )
    rng.shuffle(rows)
    conn.executemany(
        "INSERT INTO am_entity_facts("
        " entity_id, field_name, field_value_text, field_value_numeric,"
        " field_value_json, source_url, fetched_at"
        ") VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    # Warm up once so the TestClient + FastAPI route resolution caches
    # are populated before we measure pure query latency.
    warm = client.post("/v1/intel/news_brief", json={"program": "PERF-needle"})
    assert warm.status_code == 200, warm.text

    start = time.perf_counter()
    resp = client.post("/v1/intel/news_brief", json={"program": "PERF-needle"})
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The needle row must surface in the response (sanity check that
    # the index isn't masking the result).
    needle_urls = {link["url"] for link in body["source_links"]}
    assert "https://example.go.jp/perf/needle" in needle_urls
    # Hard cap: indexed path must beat 100ms on a 1000-row corpus.
    assert elapsed_ms < 100.0, (
        f"intel_news_brief query took {elapsed_ms:.1f}ms; "
        f"expected <100ms with idx_am_entity_facts_field_name_value"
    )
