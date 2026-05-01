from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import httpx

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import reprobe_blocked_urls as reprobe  # noqa: E402


class FakeProber:
    def __init__(self, results: dict[str, reprobe.ReprobeResult]) -> None:
        self.results = results
        self.seen: list[str] = []

    def probe(self, row: reprobe.BlockedUrlCandidate) -> reprobe.ReprobeResult:
        self.seen.append(row.row_id)
        return self.results[row.row_id]


def _build_programs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            source_url TEXT,
            source_url_status TEXT
        );
        """
    )
    return conn


def test_load_blocked_url_candidates_filters_http_blocked_rows() -> None:
    conn = _build_programs_db()
    conn.executemany(
        "INSERT INTO programs(unified_id, source_url, source_url_status) VALUES (?, ?, ?)",
        [
            ("UNI-1", "https://blocked.example/a", "blocked"),
            ("UNI-2", "https://live.example/a", "live"),
            ("UNI-3", "internal://fixture", "blocked"),
            ("UNI-4", "https://blocked.example/b", "broken"),
        ],
    )

    rows = reprobe.load_blocked_url_candidates(conn, domain="blocked.example")

    assert [(row.row_id, row.source_url, row.previous_status) for row in rows] == [
        ("UNI-1", "https://blocked.example/a", "blocked"),
        ("UNI-4", "https://blocked.example/b", "broken"),
    ]


def test_reprobe_writes_report_and_never_mutates_db(tmp_path: Path) -> None:
    conn = _build_programs_db()
    conn.executemany(
        "INSERT INTO programs(unified_id, source_url, source_url_status) VALUES (?, ?, ?)",
        [
            ("UNI-1", "https://blocked.example/a", "blocked"),
            ("UNI-2", "https://blocked.example/b", "blocked"),
        ],
    )
    candidates = reprobe.load_blocked_url_candidates(conn)
    output = tmp_path / "blocked_url_reprobe.csv"
    prober = FakeProber(
        {
            "UNI-1": reprobe.ReprobeResult(
                source="programs",
                row_id="UNI-1",
                source_url="https://blocked.example/a",
                domain="blocked.example",
                previous_status="blocked",
                final_url="https://blocked.example/a",
                status_code=200,
                outcome="reachable",
                method="HEAD",
            ),
            "UNI-2": reprobe.ReprobeResult(
                source="programs",
                row_id="UNI-2",
                source_url="https://blocked.example/b",
                domain="blocked.example",
                previous_status="blocked",
                final_url="https://blocked.example/b",
                status_code=403,
                outcome="still_blocked",
                method="HEAD",
            ),
        }
    )

    result = reprobe.reprobe_blocked_urls(candidates, prober=prober, output=output)

    assert result["candidate_rows"] == 2
    assert result["probed_rows"] == 2
    assert result["outcomes"] == {"reachable": 1, "still_blocked": 1}
    assert [row[0] for row in conn.execute("SELECT source_url_status FROM programs")] == [
        "blocked",
        "blocked",
    ]
    with output.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["outcome"] for row in rows] == ["reachable", "still_blocked"]


def test_transparent_prober_uses_ua_respects_robots_and_get_fallback() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                str(request.url),
                request.headers.get("user-agent"),
            )
        )
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text=(
                    "User-agent: *\n"
                    "Disallow: /private\n"
                    "User-agent: jpcite-research\n"
                    "Allow: /\n"
                ),
            )
        if request.method == "HEAD":
            return httpx.Response(405, request=request)
        return httpx.Response(200, request=request)

    candidate = reprobe.BlockedUrlCandidate(
        source="programs",
        row_id="UNI-1",
        source_url="https://blocked.example/private",
        domain="blocked.example",
        previous_status="blocked",
    )

    with reprobe.TransparentUserAgentProber(
        per_host_delay_sec=0,
        transport=httpx.MockTransport(handler),
    ) as prober:
        result = prober.probe(candidate)

    assert result.outcome == "reachable"
    assert result.method == "GET"
    assert {entry[2] for entry in seen} == {reprobe.TRANSPARENT_USER_AGENT}
    assert [entry[0] for entry in seen] == ["GET", "HEAD", "GET"]
