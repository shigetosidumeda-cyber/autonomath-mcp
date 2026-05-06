from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_am_source_last_verified as backfill  # noqa: E402


class FakeProber:
    def __init__(self, results: dict[int, backfill.ProbeResult]) -> None:
        self.results = results
        self.seen: list[int] = []

    def probe(self, row: backfill.SourceCandidate) -> backfill.ProbeResult:
        self.seen.append(row.source_id)
        return self.results[row.source_id]


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL,
            domain TEXT,
            last_verified TEXT
        );
        """
    )
    return conn


def test_load_candidates_filters_to_unverified_http_rows() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://a.example/one", "a.example", None),
            (2, "internal://fixture", "internal", None),
            (3, "https://a.example/two", "a.example", "2026-05-01 00:00:00"),
            (4, "https://b.example/one", "b.example", None),
        ],
    )

    rows = backfill.load_candidates(conn, domain="a.example")

    assert [(row.source_id, row.source_url) for row in rows] == [(1, "https://a.example/one")]


def test_verify_am_sources_updates_only_verified_results() -> None:
    conn = _build_db()
    conn.executemany(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        [
            (1, "https://a.example/ok", "a.example", None),
            (2, "https://a.example/robots", "a.example", None),
        ],
    )
    prober = FakeProber(
        {
            1: backfill.ProbeResult(
                source_id=1,
                source_url="https://a.example/ok",
                final_url="https://a.example/ok",
                status_code=200,
                outcome="ok",
                method="HEAD",
                verified=True,
            ),
            2: backfill.ProbeResult(
                source_id=2,
                source_url="https://a.example/robots",
                final_url="https://a.example/robots",
                status_code=None,
                outcome="robots_disallow",
                method=None,
                verified=False,
            ),
        }
    )

    result = backfill.verify_am_sources(conn, prober=prober, apply=True)

    assert result["candidate_rows"] == 2
    assert result["verified_probe_rows"] == 1
    assert result["updated_rows"] == 1
    assert result["outcomes"] == {"ok": 1, "robots_disallow": 1}
    assert (
        conn.execute("SELECT last_verified IS NOT NULL FROM am_source WHERE id = 1").fetchone()[0]
        == 1
    )
    assert conn.execute("SELECT last_verified FROM am_source WHERE id = 2").fetchone()[0] is None


def test_verify_am_sources_dry_run_does_not_update() -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_source(id, source_url, domain, last_verified) VALUES (?, ?, ?, ?)",
        (1, "https://a.example/ok", "a.example", None),
    )
    prober = FakeProber(
        {
            1: backfill.ProbeResult(
                source_id=1,
                source_url="https://a.example/ok",
                final_url="https://a.example/ok",
                status_code=200,
                outcome="ok",
                method="HEAD",
                verified=True,
            )
        }
    )

    result = backfill.verify_am_sources(conn, prober=prober, apply=False)

    assert result["verified_probe_rows"] == 1
    assert result["updated_rows"] == 0
    assert conn.execute("SELECT last_verified FROM am_source WHERE id = 1").fetchone()[0] is None


def test_classify_http_status_maps_common_outcomes() -> None:
    assert (
        backfill.classify_http_status(
            200,
            final_url="https://a.example/one",
            original_url="https://a.example/one",
        )
        == "ok"
    )
    assert (
        backfill.classify_http_status(
            200,
            final_url="https://a.example/two",
            original_url="https://a.example/one",
        )
        == "redirect"
    )
    assert (
        backfill.classify_http_status(
            403,
            final_url="https://a.example/one",
            original_url="https://a.example/one",
        )
        == "blocked"
    )
    assert (
        backfill.classify_http_status(
            404,
            final_url="https://a.example/one",
            original_url="https://a.example/one",
        )
        == "broken"
    )
