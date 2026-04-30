"""Tests for GET /v1/calendar/deadlines.ics — the per-account ICS feed.

Spec: docs/_internal/value_maximization_plan_no_llm_api.md §28.1.

The ICS endpoint surfaces every future `am_application_round` row that
maps back (via autonomath.db `entity_id_map`) to a jpintel.db `programs`
row the calling key is authorised to see. Auth is required (X-API-Key);
output is RFC 5545 (`text/calendar; charset=utf-8`); each call is a
single billable unit (`endpoint=calendar.deadlines.ics`, quantity=1).

These tests build a self-contained autonomath.db fixture (no contention
with the 9.4 GB production file) and rely on the session-level seeded
jpintel.db from `conftest.py`. The conftest seeds 4 program rows
(`UNI-test-s-1`, `UNI-test-a-1`, `UNI-test-b-1`, `UNI-test-x-1`); these
tests add an autonomath-side `entity_id_map` that points the canonical
`program:test:*` IDs at those jpi rows, plus `am_application_round`
rows so the calendar feed has events to render.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixture: build a tiny autonomath.db with entity_id_map + am_application_round
# ---------------------------------------------------------------------------


def _build_autonomath_fixture(
    db_path: Path,
    *,
    rounds: list[dict],
    id_map: list[tuple[str, str]],
    saved_searches: list[dict] | None = None,
) -> None:
    """Create autonomath.db with the minimum schema the ICS endpoint touches.

    `rounds` items: keys = program_entity_id, round_label, application_open_date,
        application_close_date, source_url (optional), status (optional).
    `id_map` items: (jpi_unified_id, am_canonical_id).
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE am_application_round (
            round_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id       TEXT NOT NULL,
            round_label             TEXT NOT NULL,
            round_seq               INTEGER,
            application_open_date   TEXT,
            application_close_date  TEXT,
            announced_date          TEXT,
            disbursement_start_date TEXT,
            budget_yen              INTEGER,
            status                  TEXT,
            source_url              TEXT,
            source_fetched_at       TEXT,
            UNIQUE (program_entity_id, round_label)
        );
        CREATE TABLE entity_id_map (
            jpi_unified_id  TEXT NOT NULL,
            am_canonical_id TEXT NOT NULL,
            match_method    TEXT NOT NULL DEFAULT 'exact_name',
            confidence      REAL NOT NULL DEFAULT 1.0,
            matched_at      TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (jpi_unified_id, am_canonical_id)
        );
        CREATE INDEX ix_eim_am ON entity_id_map(am_canonical_id);
        """
    )
    for r in rounds:
        conn.execute(
            "INSERT INTO am_application_round("
            "  program_entity_id, round_label, application_open_date, "
            "  application_close_date, status, source_url"
            ") VALUES (?,?,?,?,?,?)",
            (
                r["program_entity_id"],
                r["round_label"],
                r.get("application_open_date"),
                r.get("application_close_date"),
                r.get("status", "open"),
                r.get("source_url"),
            ),
        )
    for jpi, am in id_map:
        conn.execute(
            "INSERT OR IGNORE INTO entity_id_map(jpi_unified_id, am_canonical_id) "
            "VALUES (?,?)",
            (jpi, am),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def ics_fixture(seeded_db: Path, monkeypatch: pytest.MonkeyPatch):
    """Build the autonomath.db side of the ICS test bed.

    Seeds 5 rounds: 3 future (within 60d), 1 past (excluded), 1 with no
    matching program (UID it points at exists but has no entity_id_map →
    excluded). The conftest's seeded_db carries the 4 jpi_programs:
    UNI-test-s-1 (S/東京都), UNI-test-a-1 (A/青森県), UNI-test-b-1 (B/null),
    UNI-test-x-1 (X/excluded).

    Yields the autonomath.db Path so tests can introspect counts.
    """
    tmp = Path(tempfile.mkdtemp(prefix="ics-autonomath-"))
    am_path = tmp / "autonomath.db"
    today = date.today()
    rounds = [
        {
            "program_entity_id": "program:test:s1",
            "round_label": "1次",
            "application_open_date": (today - timedelta(days=5)).isoformat(),
            "application_close_date": (today + timedelta(days=10)).isoformat(),
            "source_url": "https://example.go.jp/s1/round1",
        },
        {
            "program_entity_id": "program:test:a1",
            "round_label": "通常型 第1次",
            "application_open_date": (today + timedelta(days=1)).isoformat(),
            "application_close_date": (today + timedelta(days=45)).isoformat(),
            "source_url": "https://example.go.jp/a1/round1",
        },
        {
            "program_entity_id": "program:test:b1",
            "round_label": "上期",
            "application_open_date": (today + timedelta(days=10)).isoformat(),
            "application_close_date": (today + timedelta(days=80)).isoformat(),
            "source_url": "https://example.go.jp/b1/round1",
        },
        {
            "program_entity_id": "program:test:s1",
            "round_label": "0次（過去）",
            "application_open_date": (today - timedelta(days=120)).isoformat(),
            "application_close_date": (today - timedelta(days=30)).isoformat(),
            "source_url": "https://example.go.jp/s1/round0",
            "status": "closed",
        },
    ]
    id_map = [
        ("UNI-test-s-1", "program:test:s1"),
        ("UNI-test-a-1", "program:test:a1"),
        ("UNI-test-b-1", "program:test:b1"),
    ]
    _build_autonomath_fixture(
        am_path, rounds=rounds, id_map=id_map
    )
    # Point the ICS endpoint's connect helper at the fixture. The path is
    # resolved at module-import-time via os.environ so we MUST purge the
    # cached jpintel_mcp.mcp.autonomath_tools.db module before re-import.
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(am_path))
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp.mcp.autonomath_tools.db"):
            del sys.modules[mod]
    yield am_path


@pytest.fixture()
def auth_client(seeded_db: Path, paid_key: str) -> tuple[TestClient, str]:
    """TestClient + a paid (metered) API key. Header pattern is
    `headers={"X-API-Key": key}` for every authenticated call."""
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app()), paid_key


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ics_returns_calendar_content_type(
    ics_fixture: Path, auth_client: tuple[TestClient, str]
) -> None:
    """Test 1: valid API key + Content-Type: text/calendar."""
    c, key = auth_client
    r = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    assert r.status_code == 200, r.text
    ctype = r.headers["content-type"]
    assert ctype.startswith("text/calendar"), ctype
    assert "charset=utf-8" in ctype


def test_ics_body_is_valid_rfc5545(
    ics_fixture: Path, auth_client: tuple[TestClient, str]
) -> None:
    """Test 2: BEGIN:VCALENDAR / END:VCALENDAR present + exactly 3 VEVENTs.

    The fixture has 4 rounds total but only 3 are future-within-horizon AND
    map to a non-X jpi_programs row. The past `0次（過去）` round and any
    unmapped round are filtered out.
    """
    c, key = auth_client
    r = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    assert r.status_code == 200
    body = r.text
    assert "BEGIN:VCALENDAR" in body
    assert "END:VCALENDAR" in body
    # Per-line CRLF — required by RFC. TestClient surfaces the raw body.
    assert "\r\n" in body
    assert body.count("BEGIN:VEVENT") == 3
    assert body.count("END:VEVENT") == 3


def test_ics_each_vevent_has_required_fields(
    ics_fixture: Path, auth_client: tuple[TestClient, str]
) -> None:
    """Test 3: every VEVENT carries UID, SUMMARY, DTSTART, URL."""
    c, key = auth_client
    r = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    assert r.status_code == 200
    body = r.text
    # Split by VEVENT block; skip the calendar header.
    blocks = body.split("BEGIN:VEVENT")[1:]
    assert len(blocks) == 3
    for blk in blocks:
        assert "UID:" in blk
        assert "SUMMARY:" in blk
        assert "DTSTART;VALUE=DATE:" in blk
        assert "DTEND;VALUE=DATE:" in blk
        assert "URL:" in blk


def test_ics_anonymous_returns_401(
    ics_fixture: Path, client: TestClient
) -> None:
    """Test 4: missing X-API-Key → 401."""
    r = client.get("/v1/calendar/deadlines.ics", params={"within_days": 30})
    assert r.status_code == 401, r.text


def test_ics_tier_s_filter_shrinks_count(
    ics_fixture: Path, auth_client: tuple[TestClient, str]
) -> None:
    """Test 5: tier=S returns only the S-tier program (UNI-test-s-1)."""
    c, key = auth_client
    r_all = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    n_all = r_all.text.count("BEGIN:VEVENT")
    r_s = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S", "within_days": 90},
    )
    assert r_s.status_code == 200
    n_s = r_s.text.count("BEGIN:VEVENT")
    assert n_s < n_all
    assert n_s == 1
    # The S-tier program's name should appear in the SUMMARY (escaped).
    assert "テスト S-tier 補助金" in r_s.text


def test_ics_prefecture_filter_shrinks_count(
    ics_fixture: Path, auth_client: tuple[TestClient, str]
) -> None:
    """Test 6: prefecture=東京都 retains only Tokyo + national.

    UNI-test-s-1 is 東京都 (kept), UNI-test-a-1 is 青森県 (dropped),
    UNI-test-b-1 is null prefecture but authority_level=国 (kept by the
    nationwide fallback).
    """
    c, key = auth_client
    r_all = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    n_all = r_all.text.count("BEGIN:VEVENT")
    r_pref = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90, "prefecture": "東京都"},
    )
    assert r_pref.status_code == 200
    n_pref = r_pref.text.count("BEGIN:VEVENT")
    assert n_pref < n_all
    assert n_pref == 2  # 東京都 + national fallback
    assert "青森" not in r_pref.text


def test_ics_within_days_30_excludes_far_future(
    ics_fixture: Path, auth_client: tuple[TestClient, str]
) -> None:
    """Test 7: within_days=30 drops the 45d/80d events.

    Only the close=+10d round (UNI-test-s-1) is inside.
    """
    c, key = auth_client
    r = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 30},
    )
    assert r.status_code == 200
    n = r.text.count("BEGIN:VEVENT")
    assert n == 1
    assert "テスト S-tier 補助金" in r.text


def test_ics_logs_usage_with_quantity_one(
    ics_fixture: Path,
    auth_client: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 8: log_usage called with quantity=1 + endpoint='calendar.deadlines.ics'.

    monkeypatch the calendar module's `log_usage` symbol (the imported
    binding, not the deps module's) so we capture the actual call the
    handler makes.
    """
    captured: list[dict] = []

    def _fake_log_usage(conn, ctx, endpoint, **kwargs):
        captured.append({"endpoint": endpoint, **kwargs})
        return None

    from jpintel_mcp.api import calendar as cal_module

    monkeypatch.setattr(cal_module, "log_usage", _fake_log_usage)

    c, key = auth_client
    r = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    assert r.status_code == 200
    assert len(captured) == 1
    call = captured[0]
    assert call["endpoint"] == "calendar.deadlines.ics"
    assert call["quantity"] == 1


def test_ics_caps_at_500_events(
    seeded_db: Path,
    auth_client: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 9: 600 future rounds → 500 VEVENTs + X-LIMIT-HIT comment.

    Builds a parallel autonomath.db carrying 600 future rounds, all
    pointing at UNI-test-s-1 (the conftest-seeded S-tier program). The
    UNIQUE(program_entity_id, round_label) constraint forces unique
    labels so all 600 land.
    """
    tmp = Path(tempfile.mkdtemp(prefix="ics-cap-"))
    am_path = tmp / "autonomath.db"
    today = date.today()
    rounds = [
        {
            "program_entity_id": "program:test:s1",
            "round_label": f"R{i:04d}",
            "application_open_date": today.isoformat(),
            "application_close_date": (today + timedelta(days=15 + (i % 60))).isoformat(),
            "source_url": f"https://example.go.jp/s1/{i}",
        }
        for i in range(600)
    ]
    id_map = [("UNI-test-s-1", "program:test:s1")]
    _build_autonomath_fixture(am_path, rounds=rounds, id_map=id_map)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(am_path))
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp.mcp.autonomath_tools.db"):
            del sys.modules[mod]

    c, key = auth_client
    r = c.get(
        "/v1/calendar/deadlines.ics",
        headers={"X-API-Key": key},
        params={"tier": "S,A,B,C", "within_days": 90},
    )
    assert r.status_code == 200
    body = r.text
    assert body.count("BEGIN:VEVENT") == 500
    assert body.count("END:VEVENT") == 500
    assert "X-LIMIT-HIT:500" in body
