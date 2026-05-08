from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def _make_conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_first_billable_funnel_event_records_once(monkeypatch, tmp_path) -> None:
    from jpintel_mcp.api import deps as deps_mod

    db_path = tmp_path / "first_billable.sqlite"
    conn = _make_conn(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE usage_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT,
                endpoint TEXT,
                ts TEXT,
                status INTEGER,
                metered INTEGER,
                quantity INTEGER
            );
            CREATE TABLE funnel_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                event_name TEXT,
                page TEXT,
                properties_json TEXT,
                anon_ip_hash TEXT,
                session_id TEXT,
                key_hash TEXT,
                user_agent_class TEXT,
                is_bot INTEGER,
                is_anonymous INTEGER,
                referer_host TEXT,
                src TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO usage_events(key_hash, endpoint, ts, status, metered, quantity) "
            "VALUES (?,?,?,?,?,?)",
            ("kh1", "batch.endpoint", datetime.now(UTC).isoformat(), 200, 1, 7),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(deps_mod, "connect", lambda: _make_conn(db_path))

    deps_mod._record_first_billable_event_once(
        key_hash="kh1",
        endpoint="batch.endpoint",
        quantity=7,
        usage_event_id=1,
    )
    deps_mod._record_first_billable_event_once(
        key_hash="kh1",
        endpoint="batch.endpoint",
        quantity=7,
        usage_event_id=1,
    )

    conn = _make_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT event_name, key_hash, properties_json FROM funnel_events"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["event_name"] == "first_billable"
    assert rows[0]["key_hash"] == "kh1"
    assert '"quantity":7' in rows[0]["properties_json"]
