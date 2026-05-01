from __future__ import annotations

import sqlite3
from importlib import import_module

from jpintel_mcp.api.deps import ApiContext, log_usage


def test_request_idempotency_key_distinguishes_multiple_usage_events(
    tmp_path,
) -> None:
    db_path = tmp_path / "usage_idempotency.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                last_used_at TEXT
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER DEFAULT 0,
                params_digest TEXT,
                latency_ms INTEGER,
                result_count INTEGER,
                client_tag TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                billing_idempotency_key TEXT
            );
            CREATE UNIQUE INDEX idx_usage_events_billing_idempotency
                ON usage_events(key_hash, billing_idempotency_key)
                WHERE billing_idempotency_key IS NOT NULL;
            """
        )
        conn.execute(
            "INSERT INTO api_keys(key_hash, last_used_at) VALUES (?, NULL)",
            ("kh_multi",),
        )
        ctx = ApiContext(key_hash="kh_multi", tier="free", customer_id=None)

        def record_request_once() -> None:
            idem = import_module("jpintel_mcp.api.idempotency_context")
            key_token = idem.billing_idempotency_key.set("idem_multi")
            index_token = idem.billing_event_index.set(0)
            try:
                log_usage(
                    conn,
                    ctx,
                    "am.dd_batch.row",
                    params={"houjin_bangou": "1234567890123", "depth": "basic"},
                )
                log_usage(
                    conn,
                    ctx,
                    "am.dd_batch.row",
                    params={"houjin_bangou": "9876543210987", "depth": "basic"},
                    )
            finally:
                idem.billing_event_index.reset(index_token)
                idem.billing_idempotency_key.reset(key_token)

        record_request_once()
        record_request_once()

        rows = conn.execute(
            "SELECT endpoint, params_digest, billing_idempotency_key "
            "FROM usage_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
    assert {row[0] for row in rows} == {"am.dd_batch.row"}
    assert {row[1] for row in rows} == {None}
    assert len({row[2] for row in rows}) == 2
    assert all(str(row[2]).startswith("idem_multi:u") for row in rows)
