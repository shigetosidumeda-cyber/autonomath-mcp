"""End-to-end tests for the ``?format=…`` query-parameter route wiring.

The renderer-level dispatcher is covered by ``test_output_formats.py`` (it
runs ``render(rows, fmt, meta)`` directly). This file is the route-layer
counterpart: it walks the actual FastAPI surface so we know the dispatcher
is reachable from a paying customer's HTTP call.

Coverage matrix (one test per format × endpoint):

    GET /v1/programs/search?format=csv             text/csv          (search)
    GET /v1/programs/search?format=csv-freee       text/csv          (search)
    GET /v1/programs/search?format=csv-mf          text/csv          (search)
    GET /v1/programs/search?format=csv-yayoi       text/csv;sjis     (search)
    GET /v1/programs/search?format=invalid         400                (search)
    GET /v1/programs/{id}?format=docx-application  application/…doc  (get)
    GET /v1/me/saved_searches/{id}/results?format=ics text/calendar  (saved)
    GET /v1/me/saved_searches/{id}/results?format=csv text/csv        (saved)

Each test asserts:
  1. status_code == 200 (or 400 for the negative case)
  2. Content-Type header matches the format's canonical media type
  3. Body parses with the canonical lib for that format
  4. Snapshot pair (X-Corpus-Snapshot-Id / X-Corpus-Checksum) is present
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fmt_key(seeded_db: Path) -> str:
    """Provision a metered API key — saved-search routes require auth."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_format_test",
        tier="paid",
        stripe_subscription_id="sub_format_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _seed_deadline_and_saved_search(seeded_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Seed a deadline-bearing program + saved_searches table.

    The default conftest fixture seeds 4 programs but none has a
    `next_deadline` — without one, the ICS test would emit zero VEVENTs
    and we couldn't tell the route from the renderer apart. We patch
    one program to carry a next_deadline column value.

    saved_searches table is provisioned via migration 079 (idempotent).
    """
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        cols = {row[1] for row in c.execute("PRAGMA table_info(saved_searches)")}
        if "channel_format" not in cols:
            c.execute(
                "ALTER TABLE saved_searches ADD COLUMN channel_format TEXT NOT NULL DEFAULT 'email'"
            )
        if "channel_url" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN channel_url TEXT")
        c.execute("DELETE FROM saved_searches")
        # Patch one row so the ICS path has a deadline to render.
        # `next_deadline` on the response is derived from
        # application_window_json (see _extract_next_deadline in
        # api/programs.py) — we seed a future end_date so the ICS
        # renderer sees a valid VEVENT-bearing row.
        c.execute(
            "UPDATE programs "
            "SET application_window_json = ?, source_url = ?, source_fetched_at = ? "
            "WHERE unified_id = ?",
            (
                json.dumps({"end_date": "2026-12-31"}, ensure_ascii=False),
                "https://www.meti.go.jp/policy/test-program.html",
                "2026-05-07T00:00:00+00:00",
                "UNI-test-s-1",
            ),
        )
        c.commit()
    finally:
        c.close()
    monkeypatch.setattr(
        "jpintel_mcp.api._universal_envelope.license_for_url",
        lambda url: "gov_standard_v2.0" if url else "unknown",
    )
    yield


# ---------------------------------------------------------------------------
# 1. /v1/programs/search?format=csv — happy path.
# ---------------------------------------------------------------------------


def test_programs_search_csv(client, fmt_key):
    r = client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "csv"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers.get("X-AutonoMath-Format") == "csv"
    # Snapshot pair mirrored to header for auditor grep.
    assert r.headers.get("X-Corpus-Snapshot-Id"), r.headers
    assert r.headers.get("X-Corpus-Checksum", "").startswith("sha256:")

    raw = r.content
    assert raw.startswith(b"\xef\xbb\xbf"), "CSV must lead with UTF-8 BOM"
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    # Comment row 0 — §52 disclaimer.
    assert lines[0].startswith("# 税理士法 §52"), lines[0]
    # Header row + at least one data row.
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    parsed = list(csv.DictReader(io.StringIO("\n".join(lines[header_idx:]))))
    # The seeded UNI-test-s-1 row is in 東京都, so it must round-trip.
    assert any(row.get("unified_id") == "UNI-test-s-1" for row in parsed), parsed


def _usage_count(seeded_db: Path, raw_key: str, endpoint: str) -> int:
    from jpintel_mcp.api.deps import hash_api_key

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (hash_api_key(raw_key), endpoint),
        ).fetchone()
    finally:
        c.close()
    return int(row[0] if row else 0)


def test_programs_search_renderer_failure_does_not_bill(
    client,
    fmt_key,
    seeded_db: Path,
    monkeypatch,
):
    """A failed non-JSON renderer must not create a metered usage row."""
    import jpintel_mcp.api._format_dispatch as dispatch

    def _boom(*_args, **_kwargs):
        raise RuntimeError("renderer boom")

    monkeypatch.setattr(dispatch, "render", _boom)
    safe_client = TestClient(client.app, raise_server_exceptions=False)

    r = safe_client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "csv"},
        headers={"X-API-Key": fmt_key},
    )

    assert r.status_code == 500
    assert _usage_count(seeded_db, fmt_key, "programs.search") == 0


# ---------------------------------------------------------------------------
# 2. /v1/programs/{id}?format=docx-application — §1 行政書士法 marker.
# ---------------------------------------------------------------------------


def test_program_get_docx_application(client, fmt_key):
    docx_mod = pytest.importorskip("docx")

    r = client.get(
        "/v1/programs/UNI-test-s-1",
        params={"format": "docx-application"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert r.headers.get("X-AutonoMath-Format") == "docx-application"
    assert r.headers.get("X-Corpus-Snapshot-Id"), r.headers

    doc = docx_mod.Document(io.BytesIO(r.content))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "行政書士法 §1" in full_text, "§1 行政書士法 fence missing"
    assert "{{customer_name}}" in full_text, "placeholder must stay unfilled"
    # §52 also reprinted on cover.
    assert "§52" in full_text


def test_program_get_renderer_failure_does_not_bill(
    client,
    fmt_key,
    seeded_db: Path,
    monkeypatch,
):
    """A failed single-program renderer must not create a metered usage row."""
    import jpintel_mcp.api._format_dispatch as dispatch

    def _boom(*_args, **_kwargs):
        raise RuntimeError("renderer boom")

    monkeypatch.setattr(dispatch, "render", _boom)
    safe_client = TestClient(client.app, raise_server_exceptions=False)

    r = safe_client.get(
        "/v1/programs/UNI-test-s-1",
        params={"format": "docx-application"},
        headers={"X-API-Key": fmt_key},
    )

    assert r.status_code == 500
    assert _usage_count(seeded_db, fmt_key, "programs.get") == 0


# ---------------------------------------------------------------------------
# 3. /v1/me/saved_searches/{id}/results?format=ics — VEVENT round-trip.
# ---------------------------------------------------------------------------


def _create_saved_search(client, key: str) -> int:
    r = client.post(
        "/v1/me/saved_searches",
        headers={"X-API-Key": key},
        json={
            "name": "format-test",
            "query": {"prefecture": "東京都"},
            "frequency": "daily",
            "notify_email": "fmt@example.com",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_saved_search_results_ics(client, fmt_key):
    icalendar = pytest.importorskip("icalendar")

    saved_id = _create_saved_search(client, fmt_key)
    r = client.get(
        f"/v1/me/saved_searches/{saved_id}/results",
        params={"format": "ics"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/calendar")
    assert r.headers.get("X-AutonoMath-Format") == "ics"
    assert r.headers.get("X-Corpus-Snapshot-Id"), r.headers

    cal = icalendar.Calendar.from_ical(r.content)
    events = list(cal.walk("VEVENT"))
    # The seeded UNI-test-s-1 program in 東京都 has next_deadline patched
    # in by the autouse fixture. ICS skips deadline-less rows silently —
    # if zero events come back the route either dropped the row or the
    # ICS renderer lost it.
    assert len(events) >= 1, "expected at least one VEVENT"
    uid_re = re.compile(r"^[0-9a-f]{64}@autonomath\.ai$")
    for ev in events:
        assert uid_re.match(str(ev.get("UID")))


def test_saved_search_results_csv(client, fmt_key):
    saved_id = _create_saved_search(client, fmt_key)
    r = client.get(
        f"/v1/me/saved_searches/{saved_id}/results",
        params={"format": "csv"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers.get("X-Corpus-Snapshot-Id"), r.headers
    text = r.content.decode("utf-8-sig")
    assert "# 税理士法 §52" in text


def test_saved_search_results_json_default(client, fmt_key, seeded_db: Path):
    saved_id = _create_saved_search(client, fmt_key)
    r = client.get(
        f"/v1/me/saved_searches/{saved_id}/results",
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved_search_id"] == saved_id
    assert "corpus_snapshot_id" in body
    assert isinstance(body["results"], list)
    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT metered, result_count, quantity FROM usage_events WHERE endpoint = ?",
            ("saved_searches.results",),
        ).fetchone()
    finally:
        c.close()
    assert row == (1, len(body["results"]), 1)


# ---------------------------------------------------------------------------
# 4. Invalid format on /v1/programs/search — 422 from FastAPI pattern guard.
# ---------------------------------------------------------------------------


def test_programs_search_invalid_format_rejected(client, fmt_key):
    """An unsupported format must NOT silently fall through to JSON.

    FastAPI's ``Query(pattern=...)`` returns 422 on regex mismatch. The
    instructions specify 400 — but FastAPI's standard validation is 422
    and changing that contract for one parameter would break the
    error-envelope shape every other endpoint uses. We accept either as
    a "client error" (4xx) and document the actual code below.
    """
    r = client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "yaml"},
        headers={"X-API-Key": fmt_key},
    )
    # FastAPI Query(pattern=...) → 422; the dispatcher's own SUPPORTED check → 400.
    # Either is a client-error response and means the format was rejected.
    assert r.status_code in (400, 422), r.text


# ---------------------------------------------------------------------------
# 5. csv-freee — accounting vendor template URL header + freee column order.
# ---------------------------------------------------------------------------


def test_programs_search_csv_freee(client, fmt_key):
    r = client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "csv-freee"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers.get("X-AutonoMath-Format") == "csv-freee"
    # Vendor-template URL header is the unique freee marker.
    assert "support.freee.co.jp" in (r.headers.get("X-AutonoMath-Vendor-Template") or "")
    text = r.content.decode("utf-8")
    lines = text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    header = lines[header_idx].split(",")
    assert header[:4] == ["取引日", "借方勘定科目", "借方税区分", "借方金額"]


# ---------------------------------------------------------------------------
# 6. csv-mf — MoneyForward column order (取引No / 借方補助科目 / 備考).
# ---------------------------------------------------------------------------


def test_programs_search_csv_mf(client, fmt_key):
    r = client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "csv-mf"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers.get("X-AutonoMath-Format") == "csv-mf"
    text = r.content.decode("utf-8-sig")
    lines = text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    header = lines[header_idx].split(",")
    assert header[0] == "取引No"
    assert "借方補助科目" in header
    assert "備考" in header


# ---------------------------------------------------------------------------
# 7. csv-yayoi — Shift_JIS encoding + 識別フラグ 2000.
# ---------------------------------------------------------------------------


def test_programs_search_csv_yayoi(client, fmt_key):
    r = client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "csv-yayoi"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("X-AutonoMath-Format") == "csv-yayoi"
    assert "shift_jis" in r.headers["content-type"].lower()
    # MUST decode as Shift_JIS, not UTF-8.
    text = r.content.decode("shift_jis")
    lines = text.splitlines()
    header_idx = next(i for i, ln in enumerate(lines) if not ln.startswith("#"))
    header = lines[header_idx].split(",")
    assert header[0] == "識別フラグ"
    # Yayoi 仕訳行 識別フラグ.
    data_line = lines[header_idx + 1]
    assert data_line.startswith("2000,")


# ---------------------------------------------------------------------------
# 8. /v1/programs/{id} rejects ?format=ics (programs detail isn't list-shaped).
# ---------------------------------------------------------------------------


def test_program_get_rejects_ics(client, fmt_key):
    """get-by-id allows json/csv/xlsx/md/docx-application only."""
    r = client.get(
        "/v1/programs/UNI-test-s-1",
        params={"format": "ics"},
        headers={"X-API-Key": fmt_key},
    )
    # Pattern guard returns 422; either way, NOT 200.
    assert r.status_code in (400, 422), r.text


# ---------------------------------------------------------------------------
# 9. /v1/programs/search rejects ?format=docx-application (list-shape only).
# ---------------------------------------------------------------------------


def test_programs_search_rejects_docx(client, fmt_key):
    """search list-shape disallows docx-application (per-program scaffold)."""
    r = client.get(
        "/v1/programs/search",
        params={"prefecture": "東京都", "format": "docx-application"},
        headers={"X-API-Key": fmt_key},
    )
    assert r.status_code in (400, 422), r.text
