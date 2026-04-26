"""Regression test for the short-ASCII search latency outlier.

Context (docs/performance.md, 2026-04-24):
  - Japanese 2+ char kanji queries: P95 = 17 ms (FTS path, phrase-quoted).
  - GET /v1/programs/search?q=IT (2-char ASCII): P95 = 434 ms (LIKE scan
    against enriched_json — 12k rows, ~60% substring false-positive rate
    on English words).

Fix: programs.py::search_programs LIKE-fallback branch narrows to
primary_name + aliases_json for short (<3 char) pure-ASCII queries.

This test pins:
  1. q=IT returns results (correctness).
  2. 20 consecutive calls to ?q=IT stay under 150 ms P95
     (latency regression guard).
  3. A Japanese 2-char control query keeps working
     (?q=税額 still exercises the enriched_json scan path).

The CI seed DB in tests/conftest.py has only 4 rows, so absolute wall
time is dominated by FastAPI + TestClient overhead rather than SQLite
scan. The 150 ms ceiling is still enough headroom over the observed
~5-10 ms test-suite baseline that a regression re-introducing the
enriched_json scan would trip it (the scan blows past 150 ms even on
a tiny corpus when the test client is warm).
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _percentile(samples: list[float], pct: float) -> float:
    """Small-sample percentile — nearest-rank method. For 20 samples at
    P95, returns the 19th element of sorted(samples) (0-indexed 18)."""
    if not samples:
        raise ValueError("empty samples")
    ordered = sorted(samples)
    # nearest-rank: ceil(pct/100 * N) - 1
    from math import ceil
    idx = max(0, ceil(pct / 100 * len(ordered)) - 1)
    return ordered[idx]


def _insert_row(
    conn: sqlite3.Connection,
    *,
    unified_id: str,
    primary_name: str,
    tier: str = "A",
    aliases: list[str] | None = None,
    enriched_text: str = "",
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO programs(
            unified_id, primary_name, aliases_json,
            authority_level, authority_name, prefecture, municipality,
            program_kind, official_url,
            amount_max_man_yen, amount_min_man_yen, subsidy_rate,
            trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
            excluded, exclusion_reason,
            crop_categories_json, equipment_category,
            target_types_json, funding_purpose_json,
            amount_band, application_window_json,
            enriched_json, source_mentions_json, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            unified_id, primary_name,
            json.dumps(aliases or [], ensure_ascii=False),
            "国", None, None, None,
            "補助金", None,
            None, None, None,
            None, tier, None, None, None,
            0, None,
            None, None,
            json.dumps([], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            None, None,
            enriched_text or None, None, now,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO programs_fts"
        "(unified_id, primary_name, aliases, enriched_text) VALUES (?,?,?,?)",
        (unified_id, primary_name, " ".join(aliases or []), enriched_text),
    )
    conn.commit()


@pytest.fixture()
def seeded_for_perf(seeded_db: Path) -> Path:
    """Seed rows that exercise both the hit path (IT in primary_name) and
    the false-positive-bait path (IT as substring in enriched JSON)."""
    conn = sqlite3.connect(seeded_db)
    try:
        # Real hit: 'IT' appears in primary_name — must survive the narrow
        # scan.
        _insert_row(
            conn,
            unified_id="UNI-perf-it-hit",
            primary_name="IT導入補助金(テスト)",
            tier="A",
        )
        # False-positive bait: 'IT' buried inside English words in the
        # enriched blob. Under the old behavior this row would latency-
        # and relevance-pollute the q=IT result set.
        for i in range(20):
            _insert_row(
                conn,
                unified_id=f"UNI-perf-it-noise-{i:02d}",
                primary_name=f"テスト英文ノイズ行 {i:02d}",
                tier="B",
                enriched_text=(
                    "This program covers credit counseling, exhibIT "
                    "travel, Information sessions, legITimate applicant "
                    "verification, and audIT fees."
                ),
            )
    finally:
        conn.close()
    return seeded_db


def test_short_ascii_query_returns_results(
    client: TestClient, seeded_for_perf: Path
) -> None:
    """q=IT must surface the primary_name match."""
    r = client.get("/v1/programs/search", params={"q": "IT", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert "IT導入補助金(テスト)" in names, (
        f"q=IT did not return the primary_name hit; names={names}"
    )
    # Enriched-blob-only noise rows must NOT appear (relevance guard —
    # this is the second half of the perf fix).
    for name in names:
        assert not name.startswith("テスト英文ノイズ行"), (
            f"enriched-only row leaked into q=IT result set: {name}"
        )


def test_short_ascii_query_p95_under_150ms(
    client: TestClient, seeded_for_perf: Path
) -> None:
    """P95 over 20 consecutive q=IT calls must stay under 150 ms.

    Warm-up: 3 calls to fill any lazy caches (first-request FastAPI
    startup work, sqlite page cache) so the measurement is steady-state.
    """
    # Warm-up (not measured).
    for _ in range(3):
        client.get("/v1/programs/search", params={"q": "IT", "limit": 20})

    samples: list[float] = []
    for _ in range(20):
        t0 = time.perf_counter()
        r = client.get("/v1/programs/search", params={"q": "IT", "limit": 20})
        samples.append((time.perf_counter() - t0) * 1000.0)
        assert r.status_code == 200

    p95 = _percentile(samples, 95)
    assert p95 < 150.0, (
        f"q=IT P95={p95:.1f} ms (target <150 ms). "
        f"All samples (ms): {[f'{s:.1f}' for s in samples]}"
    )


def test_short_japanese_query_still_covers_enriched(
    client: TestClient, seeded_for_perf: Path
) -> None:
    """Control: 2-char Japanese kanji queries must still search
    enriched_json. If a future change over-eagerly drops the enriched
    column for all short queries (not just ASCII), this test catches it.
    """
    # Seed a row whose 税額 token lives only in enriched_text.
    conn = sqlite3.connect(seeded_for_perf)
    try:
        _insert_row(
            conn,
            unified_id="UNI-perf-kanji-enriched",
            primary_name="テスト控除対象事業(本文のみ)",
            tier="A",
            enriched_text="本制度は税額の計算に影響します。",
        )
    finally:
        conn.close()

    r = client.get("/v1/programs/search", params={"q": "税額", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    names = [row["primary_name"] for row in body["results"]]
    assert "テスト控除対象事業(本文のみ)" in names, (
        f"2-char kanji '税額' failed to match enriched_text; "
        f"names={names}"
    )
