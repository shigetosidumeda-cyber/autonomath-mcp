from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _clear_funnel_events(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM funnel_events")
        conn.commit()
    finally:
        conn.close()


def test_funnel_event_accepts_browser_beacon(client, seeded_db: Path) -> None:
    _clear_funnel_events(seeded_db)

    response = client.post(
        "/v1/funnel/event",
        json={
            "event": "playground_success",
            "page": "/playground.html?flow=evidence3&email=a@example.com",
            "session_id": "abc123",
            "properties": {"endpoint": "intelligence.precomputed.query"},
        },
        headers={"User-Agent": "Mozilla/5.0 Chrome/120.0", "Referer": "https://jpcite.com/pricing.html"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body == {
        "accepted": True,
        "is_bot": False,
        "user_agent_class": "browser:chrome",
    }

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT event_name, page, session_id, properties_json, "
            "user_agent_class, is_bot, is_anonymous, referer_host "
            "FROM funnel_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["event_name"] == "playground_success"
    assert row["page"] == "/playground.html"
    assert row["session_id"] == "abc123"
    assert json.loads(row["properties_json"]) == {
        "endpoint": "intelligence.precomputed.query"
    }
    assert row["user_agent_class"] == "browser:chrome"
    assert row["is_bot"] == 0
    assert row["is_anonymous"] == 1
    assert row["referer_host"] == "jpcite.com"


def test_funnel_event_rejects_unknown_event(client, seeded_db: Path) -> None:
    _clear_funnel_events(seeded_db)

    response = client.post(
        "/v1/funnel/event",
        json={"event": "made_up_event", "page": "/playground.html"},
    )

    assert response.status_code == 400
    conn = sqlite3.connect(seeded_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM funnel_events").fetchone()[0]
    finally:
        conn.close()
    assert count == 0

