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


def test_funnel_event_accepts_text_plain_beacon(client, seeded_db: Path) -> None:
    _clear_funnel_events(seeded_db)

    response = client.post(
        "/v1/funnel/event",
        content=json.dumps(
            {
                "event": "pricing_view",
                "page": "https://www.jpcite.com/pricing.html?utm_source=chatgpt",
                "session_id": "sid-text-plain",
                "properties": {"source": "sendBeacon"},
            }
        ),
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 Safari/605.1.15",
            "Referer": "https://chatgpt.com/",
        },
    )

    assert response.status_code == 202, response.text

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT event_name, page, session_id, properties_json, referer_host "
            "FROM funnel_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["event_name"] == "pricing_view"
    assert row["page"] == "/pricing.html"
    assert row["session_id"] == "sid-text-plain"
    assert json.loads(row["properties_json"]) == {"source": "sendBeacon"}
    assert row["referer_host"] == "chatgpt.com"


def test_funnel_event_drops_foreign_absolute_page(client, seeded_db: Path) -> None:
    _clear_funnel_events(seeded_db)

    response = client.post(
        "/v1/funnel/event",
        json={
            "event": "cta_click",
            "page": "https://evil.example.com/pricing.html?email=a@example.com",
            "properties": {"target": "pricing"},
        },
    )

    assert response.status_code == 202, response.text

    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT page, properties_json FROM funnel_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["page"] is None
    assert json.loads(row["properties_json"]) == {"target": "pricing"}


def test_funnel_event_large_properties_remain_valid_json(
    client, seeded_db: Path
) -> None:
    _clear_funnel_events(seeded_db)

    response = client.post(
        "/v1/funnel/event",
        json={
            "event": "quickstart_copy",
            "page": "/docs/getting-started/",
            "properties": {
                "snippet": "curl-search",
                "long": "あ" * 1000,
                "nested": {"drop": "not top-level scalar"},
            },
        },
    )

    assert response.status_code == 202, response.text

    conn = sqlite3.connect(seeded_db)
    try:
        raw = conn.execute(
            "SELECT properties_json FROM funnel_events ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    decoded = json.loads(raw)
    assert decoded["_truncated"] is True
    assert decoded["snippet"] == "curl-search"
    assert len(raw.encode("utf-8")) <= 512


def test_funnel_event_rejects_oversized_body(client, seeded_db: Path) -> None:
    _clear_funnel_events(seeded_db)

    response = client.post(
        "/v1/funnel/event",
        content=(
            '{"event":"quickstart_copy","page":"/docs/getting-started/",'
            '"properties":{"too_big":"'
            + ("x" * 5000)
            + '"}}'
        ),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )

    assert response.status_code == 413
    conn = sqlite3.connect(seeded_db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM funnel_events").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


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
