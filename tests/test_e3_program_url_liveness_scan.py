from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import httpx

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import scan_program_url_liveness as liveness  # noqa: E402


class FakeProber:
    def __init__(self, results: dict[str, liveness.LivenessResult]) -> None:
        self.results = results
        self.seen: list[str] = []

    def probe(self, row: liveness.ProgramUrlCandidate) -> liveness.LivenessResult:
        self.seen.append(row.unified_id)
        return self.results[row.unified_id]


def _build_programs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT,
            tier TEXT,
            source_url TEXT,
            source_url_status TEXT
        );
        """
    )
    return conn


def test_load_unknown_tier_bc_candidates_filters_to_http_unknown_rows() -> None:
    conn = _build_programs_db()
    conn.executemany(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?)",
        [
            ("UNI-A", "Tier A", "A", "https://example.jp/a", "unknown"),
            ("UNI-B1", "Tier B unknown", "B", "https://example.jp/b1", "unknown"),
            ("UNI-B2", "Tier B blank", "B", "https://example.jp/b2", " "),
            ("UNI-B3", "Tier B live", "B", "https://example.jp/b3", "ok"),
            ("UNI-C1", "Tier C null", "C", "https://other.jp/c1", None),
            ("UNI-C2", "Tier C non-http", "C", "mailto:info@example.jp", "unknown"),
        ],
    )

    rows = liveness.load_unknown_tier_bc_candidates(conn, limit=10)

    assert [(row.unified_id, row.tier, row.source_url) for row in rows] == [
        ("UNI-B1", "B", "https://example.jp/b1"),
        ("UNI-B2", "B", "https://example.jp/b2"),
        ("UNI-C1", "C", "https://other.jp/c1"),
    ]


def test_load_unknown_tier_bc_candidates_applies_limit_and_domain() -> None:
    conn = _build_programs_db()
    conn.executemany(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?)",
        [
            ("UNI-1", "One", "B", "https://keep.example/a", "unknown"),
            ("UNI-2", "Two", "B", "https://skip.example/a", "unknown"),
            ("UNI-3", "Three", "C", "https://keep.example/b", "unknown"),
        ],
    )

    rows = liveness.load_unknown_tier_bc_candidates(
        conn,
        limit=1,
        domain="keep.example",
    )

    assert [row.unified_id for row in rows] == ["UNI-1"]


def test_classify_liveness() -> None:
    assert liveness.classify_liveness(
        200,
        final_url="https://example.jp/a",
        original_url="https://example.jp/a",
    ) == "ok"
    assert liveness.classify_liveness(
        200,
        final_url="https://example.jp/b",
        original_url="https://example.jp/a",
    ) == "ok_redirect"
    assert liveness.classify_liveness(
        403,
        final_url="https://example.jp/a",
        original_url="https://example.jp/a",
    ) == "blocked"
    assert liveness.classify_liveness(
        404,
        final_url="https://example.jp/a",
        original_url="https://example.jp/a",
    ) == "hard_404"
    assert liveness.classify_liveness(
        503,
        final_url="https://example.jp/a",
        original_url="https://example.jp/a",
    ) == "server_error"


def test_scan_writes_report_and_never_mutates_db(tmp_path: Path) -> None:
    conn = _build_programs_db()
    conn.executemany(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?)",
        [
            ("UNI-1", "One", "B", "https://example.jp/one", "unknown"),
            ("UNI-2", "Two", "C", "https://example.jp/two", "unknown"),
        ],
    )
    candidates = liveness.load_unknown_tier_bc_candidates(conn, limit=10)
    output = tmp_path / "tier_bc_url_liveness.csv"
    prober = FakeProber(
        {
            "UNI-1": liveness.LivenessResult(
                unified_id="UNI-1",
                primary_name="One",
                tier="B",
                source_url="https://example.jp/one",
                domain="example.jp",
                previous_status="unknown",
                final_url="https://example.jp/one",
                status_code=200,
                classification="ok",
                method="HEAD",
            ),
            "UNI-2": liveness.LivenessResult(
                unified_id="UNI-2",
                primary_name="Two",
                tier="C",
                source_url="https://example.jp/two",
                domain="example.jp",
                previous_status="unknown",
                final_url="https://example.jp/two",
                status_code=404,
                classification="hard_404",
                method="HEAD",
            ),
        }
    )

    result = liveness.scan_program_url_liveness(candidates, prober=prober, output=output)

    assert result["candidate_rows"] == 2
    assert result["probed_rows"] == 2
    assert result["classifications"] == {"hard_404": 1, "ok": 1}
    assert [row[0] for row in conn.execute("SELECT source_url_status FROM programs")] == [
        "unknown",
        "unknown",
    ]
    with output.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [row["classification"] for row in rows] == ["ok", "hard_404"]


def test_transparent_prober_uses_ua_respects_robots_and_get_fallback() -> None:
    seen: list[tuple[str, str, str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.method,
                str(request.url),
                request.headers.get("user-agent"),
                request.headers.get("range"),
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

    candidate = liveness.ProgramUrlCandidate(
        unified_id="UNI-1",
        primary_name="One",
        tier="B",
        source_url="https://example.jp/private",
        domain="example.jp",
        previous_status="unknown",
    )

    with liveness.TransparentUserAgentLivenessProber(
        per_host_delay_sec=0,
        transport=httpx.MockTransport(handler),
    ) as prober:
        result = prober.probe(candidate)

    assert result.classification == "ok"
    assert result.method == "GET"
    assert {entry[2] for entry in seen} == {liveness.TRANSPARENT_USER_AGENT}
    assert [entry[0] for entry in seen] == ["GET", "HEAD", "GET"]
    assert seen[-1][3] == "bytes=0-0"
