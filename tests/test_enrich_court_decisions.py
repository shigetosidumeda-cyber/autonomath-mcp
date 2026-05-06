"""Tests for ``scripts/etl/enrich_court_decisions_excerpt.py``.

The fetcher path is exercised against an in-memory fixture HTML modelled on
the real courts.go.jp ``hanrei/<id>/detail2/index.html`` markup (DL pairs:
``判示事項`` / ``裁判要旨`` / ``参照法条`` etc.). HTTP layer is mocked via a
local ``httpx.MockTransport``.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    import pytest

_ETL_DIR = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL_DIR) not in sys.path:
    sys.path.insert(0, str(_ETL_DIR))

import enrich_court_decisions_excerpt as enrich  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture HTML
# ---------------------------------------------------------------------------

# Minimal but realistic detail-page snippet. dl/dt/dd ordering matches the live
# layout we observed on https://www.courts.go.jp/hanrei/89339/detail2/index.html
_FIXTURE_DETAIL_HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>fixture</title></head>
<body>
<main>
<dl><dt>事件番号</dt><dd>令和3(行ヒ)100</dd></dl>
<dl><dt>事件名</dt><dd>所得税更正処分取消請求事件</dd></dl>
<dl><dt>裁判年月日</dt><dd>令和4年5月20日</dd></dl>
<dl><dt>法廷名</dt><dd>最高裁判所第三小法廷</dd></dl>
<dl><dt>裁判種別</dt><dd>判決</dd></dl>
<dl><dt>結果</dt><dd>棄却</dd></dl>
<dl><dt>判示事項</dt><dd>所得税法59条1項所定の「その時における価額」につき配当還元価額によって評価した原審の判断に違法があるとされた事例。</dd></dl>
<dl><dt>裁判要旨</dt><dd>取引相場のない株式の譲渡に係る所得税法59条1項の「その時における価額」を、譲受人が財産評価基本通達上配当還元価額によって評価される株主に該当することを理由として配当還元価額で評価した原審の判断には法令の解釈適用を誤った違法がある。</dd></dl>
<dl><dt>参照法条</dt><dd>所得税法59条1項、所得税法施行令169条</dd></dl>
</main>
</body></html>
"""


_EMPTY_DETAIL_HTML = """<!DOCTYPE html>
<html><body><main><p>該当データがありません</p></main></body></html>
"""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_safe_url_accepts_canonical_hanrei_pattern() -> None:
    assert enrich._safe_url("https://www.courts.go.jp/hanrei/89339/detail2/index.html") is True


def test_safe_url_rejects_other_hosts() -> None:
    assert enrich._safe_url("https://example.com/hanrei/1/detail2/index.html") is False


def test_safe_url_rejects_kozisotatu_path() -> None:
    assert enrich._safe_url("https://www.courts.go.jp/tokyo/saiban/kozisotatu/index.html") is False


def test_safe_url_rejects_http_scheme() -> None:
    assert enrich._safe_url("http://www.courts.go.jp/hanrei/1/detail2/index.html") is False


def test_extract_excerpt_returns_labelled_segments_within_400_chars() -> None:
    excerpt, blob = enrich.extract_excerpt(_FIXTURE_DETAIL_HTML)
    assert excerpt.startswith("【判示事項】")
    assert "【裁判要旨】" in excerpt
    assert len(excerpt) <= enrich.EXCERPT_MAX_CHARS
    # Blob is the untrimmed concat — should be at least as long as excerpt.
    assert len(blob) >= len(excerpt)


def test_extract_excerpt_returns_empty_when_no_labelled_segment() -> None:
    excerpt, blob = enrich.extract_excerpt(_EMPTY_DETAIL_HTML)
    assert excerpt == ""
    assert blob == ""


def test_content_hash_is_16_hex_chars_and_stable() -> None:
    h1 = enrich._content_hash("hello")
    h2 = enrich._content_hash("hello")
    assert h1 == h2
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


# ---------------------------------------------------------------------------
# DB read
# ---------------------------------------------------------------------------


def _build_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_excerpt TEXT,
            decision_date TEXT
        );
        INSERT INTO court_decisions VALUES
          ('HAN-aaaaaaaaaa', 'https://www.courts.go.jp/hanrei/1/detail2/index.html',  NULL, '2024-05-01'),
          ('HAN-bbbbbbbbbb', 'https://www.courts.go.jp/hanrei/2/detail2/index.html',  '',   '2023-04-01'),
          ('HAN-cccccccccc', 'https://www.courts.go.jp/hanrei/3/detail2/index.html',  '既存抜粋', '2022-01-01');
        """
    )
    conn.commit()
    conn.close()
    return db


def test_fetch_pending_skips_rows_with_existing_excerpt(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    conn = enrich.open_db(db)
    try:
        rows = enrich.fetch_pending(conn, limit=None)
    finally:
        conn.close()
    ids = {r.decision_id for r in rows}
    assert "HAN-aaaaaaaaaa" in ids
    assert "HAN-bbbbbbbbbb" in ids
    assert "HAN-cccccccccc" not in ids


def test_fetch_pending_respects_limit(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    conn = enrich.open_db(db)
    try:
        rows = enrich.fetch_pending(conn, limit=1)
    finally:
        conn.close()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Mocked HTTP path
# ---------------------------------------------------------------------------


def _build_mock_client() -> enrich.CourtsClient:
    """A CourtsClient whose underlying httpx.Client uses MockTransport.

    Hanrei IDs are mapped:
      * /hanrei/1/... -> 200 OK with fixture HTML
      * /hanrei/2/... -> 200 OK with empty body
      * /hanrei/3/... -> 404
      * /robots.txt   -> permissive (User-agent: *, Disallow: kozisotatu only)
    """
    robots_body = "User-agent: *\nDisallow: /tokyo/saiban/kozisotatu/index.html\n"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == enrich.ROBOTS_URL:
            return httpx.Response(200, text=robots_body)
        if "/hanrei/1/" in url:
            return httpx.Response(200, text=_FIXTURE_DETAIL_HTML)
        if "/hanrei/2/" in url:
            return httpx.Response(200, text=_EMPTY_DETAIL_HTML)
        if "/hanrei/3/" in url:
            return httpx.Response(404, text="not found")
        # PDF mirror: pretend it's also missing so the empty-html path stays
        # in the "no excerpt available" branch instead of recovering via PDF.
        if url.startswith("https://www.courts.go.jp/assets/hanrei/"):
            return httpx.Response(404, text="not found")
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    client = enrich.CourtsClient.__new__(enrich.CourtsClient)
    client._client = httpx.Client(
        transport=transport,
        headers={"User-Agent": enrich.USER_AGENT},
        follow_redirects=True,
    )
    client._last_call = 0.0
    client._robots = None
    return client


def test_enrich_one_happy_path() -> None:
    client = _build_mock_client()
    try:
        row = enrich.PendingRow(
            decision_id="HAN-aaaaaaaaaa",
            source_url="https://www.courts.go.jp/hanrei/1/detail2/index.html",
        )
        res = enrich.enrich_one(client, row)
    finally:
        client.close()
    assert res.status == "ok"
    assert res.error == ""
    assert res.excerpt.startswith("【判示事項】")
    assert "【裁判要旨】" in res.excerpt
    assert len(res.excerpt) <= enrich.EXCERPT_MAX_CHARS
    assert len(res.content_hash) == 16


def test_enrich_one_empty_html_falls_through_to_http_error_on_missing_pdf() -> None:
    """When HTML has no labelled section *and* the PDF mirror 404s, surface
    that as an http_error so we can distinguish "page truly empty" (PDF 404 +
    HTML empty) from "page renders but section missing" (which is the more
    interesting empty status). The PDF path is exercised because the fixture
    HTML matches the canonical detail URL pattern.
    """
    client = _build_mock_client()
    try:
        row = enrich.PendingRow(
            decision_id="HAN-bbbbbbbbbb",
            source_url="https://www.courts.go.jp/hanrei/2/detail2/index.html",
        )
        res = enrich.enrich_one(client, row)
    finally:
        client.close()
    assert res.status == "http_error"
    assert res.excerpt == ""
    assert res.content_hash == ""
    assert "pdf fallback failed" in res.error


def test_enrich_one_http_error_yields_http_error_status() -> None:
    client = _build_mock_client()
    try:
        row = enrich.PendingRow(
            decision_id="HAN-cccccccccc",
            source_url="https://www.courts.go.jp/hanrei/3/detail2/index.html",
        )
        res = enrich.enrich_one(client, row)
    finally:
        client.close()
    assert res.status == "http_error"
    assert res.excerpt == ""


def test_enrich_one_unsafe_url_short_circuits_without_http() -> None:
    client = _build_mock_client()
    try:
        row = enrich.PendingRow(
            decision_id="HAN-dddddddddd",
            source_url="https://example.com/something/else",
        )
        res = enrich.enrich_one(client, row)
    finally:
        client.close()
    assert res.status == "unsafe_url"
    assert res.error
    assert res.content_hash == ""


def test_run_dry_run_skips_http_fetch(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    conn = enrich.open_db(db)
    try:
        rows = enrich.fetch_pending(conn, limit=None)
    finally:
        conn.close()
    results = enrich.run(rows, dry_run=True)
    assert {r.status for r in results} == {"dryrun"}
    assert all(r.excerpt == "" for r in results)


def test_write_csv_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "court_decisions_excerpt.csv"
    results = [
        enrich.EnrichResult(
            decision_id="HAN-aaaaaaaaaa",
            source_url="https://www.courts.go.jp/hanrei/1/detail2/index.html",
            excerpt="【判示事項】fixture",
            fetched_at="2026-05-01T00:00:00Z",
            content_hash="0123456789abcdef",
            status="ok",
            error="",
        ),
    ]
    n = enrich.write_csv(results, out)
    assert n == 1
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["decision_id"] == "HAN-aaaaaaaaaa"
    assert rows[0]["status"] == "ok"
    assert rows[0]["excerpt"].startswith("【判示事項】")
    assert rows[0]["content_hash"] == "0123456789abcdef"


def test_main_dry_run_end_to_end(tmp_path: Path) -> None:
    db = _build_db(tmp_path)
    out = tmp_path / "out.csv"
    rc = enrich.main(
        [
            "--db",
            str(db),
            "--output",
            str(out),
            "--dry-run",
        ]
    )
    assert rc == 0
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2  # two pending rows in fixture DB
    assert {r["status"] for r in rows} == {"dryrun"}


def test_robots_disallows_kozisotatu(monkeypatch: pytest.MonkeyPatch) -> None:
    """The kozisotatu path is denied at both _safe_url and robots layers.

    _safe_url short-circuits first, but the robotparser would also block it.
    """
    rp = enrich.urllib.robotparser.RobotFileParser()
    rp.parse(
        [
            "User-agent: *",
            "Disallow: /tokyo/saiban/kozisotatu/index.html",
        ]
    )
    assert enrich.robots_allows(rp, "https://www.courts.go.jp/hanrei/1/detail2/index.html")
    assert not enrich.robots_allows(
        rp, "https://www.courts.go.jp/tokyo/saiban/kozisotatu/index.html"
    )
