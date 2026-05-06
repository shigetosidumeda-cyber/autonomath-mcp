from __future__ import annotations

import contextlib
import sqlite3
from importlib import import_module
from typing import TYPE_CHECKING

from jpintel_mcp.api.deps import ApiContext, log_usage

if TYPE_CHECKING:
    from pathlib import Path


def _create_idempotency_cache_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE am_idempotency_cache (
            cache_key TEXT PRIMARY KEY,
            response_blob TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


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
                last_used_at TEXT,
                tier TEXT DEFAULT 'paid',
                monthly_cap_yen INTEGER,
                id INTEGER,
                parent_key_id INTEGER,
                revoked_at TEXT
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
            "SELECT endpoint, params_digest, billing_idempotency_key FROM usage_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
    assert {row[0] for row in rows} == {"am.dd_batch.row"}
    assert {row[1] for row in rows} == {None}
    assert len({row[2] for row in rows}) == 2
    assert all(str(row[2]).startswith("idem_multi:u") for row in rows)


def test_duplicate_billing_idempotency_does_not_advance_cap_cache(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "usage_idempotency_cap.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    noted: list[tuple[str | None, int]] = []
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                last_used_at TEXT,
                tier TEXT DEFAULT 'paid',
                monthly_cap_yen INTEGER,
                id INTEGER,
                parent_key_id INTEGER,
                revoked_at TEXT
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
            "INSERT INTO api_keys(key_hash, last_used_at, tier, id) VALUES (?, NULL, 'paid', 1)",
            ("kh_paid",),
        )
        ctx = ApiContext(
            key_hash="kh_paid",
            tier="paid",
            customer_id="cus_paid",
            stripe_subscription_id=None,
        )

        def fake_note_cap_usage(key_hash: str | None, quantity: int = 1) -> None:
            noted.append((key_hash, quantity))

        monkeypatch.setattr(
            "jpintel_mcp.api.middleware.customer_cap.note_cap_usage",
            fake_note_cap_usage,
        )

        idem = import_module("jpintel_mcp.api.idempotency_context")
        for _ in range(2):
            key_token = idem.billing_idempotency_key.set("idem_once")
            index_token = idem.billing_event_index.set(0)
            try:
                log_usage(
                    conn,
                    ctx,
                    "programs.get",
                    params={"id": "P-1"},
                    quantity=7,
                )
            finally:
                idem.billing_event_index.reset(index_token)
                idem.billing_idempotency_key.reset(key_token)

        row_count = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
    finally:
        conn.close()

    assert row_count == 1
    assert noted == [("kh_paid", 7)]


def test_duplicate_billing_idempotency_skips_final_cap_check(tmp_path) -> None:
    db_path = tmp_path / "usage_idempotency_cap_retry.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                last_used_at TEXT,
                tier TEXT DEFAULT 'paid',
                monthly_cap_yen INTEGER,
                id INTEGER,
                parent_key_id INTEGER,
                revoked_at TEXT
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
            "INSERT INTO api_keys(key_hash, last_used_at, tier, monthly_cap_yen, id) "
            "VALUES (?, NULL, 'paid', 3, 1)",
            ("kh_paid_cap",),
        )
        ctx = ApiContext(
            key_hash="kh_paid_cap",
            tier="paid",
            customer_id="cus_paid_cap",
            stripe_subscription_id=None,
        )

        idem = import_module("jpintel_mcp.api.idempotency_context")
        for _ in range(2):
            key_token = idem.billing_idempotency_key.set("idem_cap_once")
            index_token = idem.billing_event_index.set(0)
            try:
                log_usage(
                    conn,
                    ctx,
                    "programs.get",
                    params={"id": "P-1"},
                    quantity=1,
                    strict_metering=True,
                )
            finally:
                idem.billing_event_index.reset(index_token)
                idem.billing_idempotency_key.reset(key_token)

        row_count = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
    finally:
        conn.close()

    assert row_count == 1


def test_duplicate_billing_idempotency_retries_stripe_report_without_cap_cache(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "usage_idempotency_stripe_retry.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    reported: list[tuple[str, dict]] = []
    noted: list[tuple[str | None, int]] = []
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                last_used_at TEXT,
                tier TEXT DEFAULT 'paid',
                monthly_cap_yen INTEGER,
                id INTEGER,
                parent_key_id INTEGER,
                revoked_at TEXT
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
            "INSERT INTO api_keys(key_hash, last_used_at, tier, id) VALUES (?, NULL, 'paid', 1)",
            ("kh_paid_stripe",),
        )
        ctx = ApiContext(
            key_hash="kh_paid_stripe",
            tier="paid",
            customer_id="cus_paid_stripe",
            stripe_subscription_id="sub_paid_stripe",
        )

        def fake_report_usage_async(subscription_id: str, **kwargs) -> None:
            reported.append((subscription_id, kwargs))

        def fake_note_cap_usage(key_hash: str | None, quantity: int = 1) -> None:
            noted.append((key_hash, quantity))

        monkeypatch.setattr(
            "jpintel_mcp.billing.stripe_usage.report_usage_async",
            fake_report_usage_async,
        )
        monkeypatch.setattr(
            "jpintel_mcp.api.middleware.customer_cap.note_cap_usage",
            fake_note_cap_usage,
        )

        idem = import_module("jpintel_mcp.api.idempotency_context")
        for _ in range(2):
            key_token = idem.billing_idempotency_key.set("idem_stripe_retry")
            index_token = idem.billing_event_index.set(0)
            try:
                log_usage(
                    conn,
                    ctx,
                    "programs.get",
                    params={"id": "P-1"},
                    quantity=4,
                )
            finally:
                idem.billing_event_index.reset(index_token)
                idem.billing_idempotency_key.reset(key_token)

        rows = conn.execute(
            "SELECT id, quantity, billing_idempotency_key FROM usage_events"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert int(rows[0]["quantity"]) == 4
    assert noted == [("kh_paid_stripe", 4)]
    assert len(reported) == 2
    assert {call[0] for call in reported} == {"sub_paid_stripe"}
    assert [call[1]["usage_event_id"] for call in reported] == [rows[0]["id"], rows[0]["id"]]
    assert {call[1]["idempotency_key"] for call in reported} == {rows[0]["billing_idempotency_key"]}


def test_body_fingerprint_collision_guard_rejects_different_payload(tmp_path) -> None:
    from jpintel_mcp.api.middleware.idempotency import (
        _check_or_record_body_fingerprint,
    )

    db_path = tmp_path / "idempotency_body_collision.db"
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        _create_idempotency_cache_table(conn)
        assert _check_or_record_body_fingerprint(conn, "collision:test", "body-a") == ("ok", None)
        assert _check_or_record_body_fingerprint(conn, "collision:test", "body-a") == ("ok", None)
        assert _check_or_record_body_fingerprint(conn, "collision:test", "body-b") == (
            "mismatch",
            "body-a",
        )
    finally:
        conn.close()


def test_body_fingerprint_collision_guard_db_lock_fails_closed(tmp_path) -> None:
    from jpintel_mcp.api.middleware.idempotency import (
        _check_or_record_body_fingerprint,
    )

    db_path = tmp_path / "idempotency_body_collision_lock.db"
    setup = sqlite3.connect(db_path, isolation_level=None)
    try:
        _create_idempotency_cache_table(setup)
    finally:
        setup.close()

    locker = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    contender = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        assert _check_or_record_body_fingerprint(contender, "collision:locked", "body-a") == (
            "busy",
            None,
        )
    finally:
        with contextlib.suppress(Exception):
            locker.execute("ROLLBACK")
        locker.close()
        contender.close()


def test_same_idempotency_key_different_body_is_unmetered_409(
    client,
    paid_key: str,
    seeded_db: Path,
) -> None:
    from jpintel_mcp.api.deps import hash_api_key

    headers = {
        "X-API-Key": paid_key,
        "Idempotency-Key": "idem-different-body-usage-billing",
        "X-Cost-Cap-JPY": "6",
    }
    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = 'programs.get'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    r1 = client.post(
        "/v1/programs/batch",
        headers=headers,
        json={"unified_ids": ["UNI-test-s-1"]},
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/v1/programs/batch",
        headers=headers,
        json={"unified_ids": ["UNI-test-a-1"]},
    )
    assert r2.status_code == 409, r2.text
    assert r2.headers.get("X-Metered") == "false"
    assert r2.headers.get("X-Cost-Yen") == "0"
    assert r2.json()["error"] == "idempotency_key_in_use"

    conn = sqlite3.connect(seeded_db)
    try:
        after = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = 'programs.get'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert after == before + 1


def test_corrupt_idempotency_replay_fails_closed_without_second_usage(
    client,
    paid_key: str,
    seeded_db: Path,
) -> None:
    from jpintel_mcp.api.deps import hash_api_key

    headers = {
        "X-API-Key": paid_key,
        "Idempotency-Key": "idem-corrupt-replay-usage-billing",
        "X-Cost-Cap-JPY": "6",
    }
    key_hash = hash_api_key(paid_key)
    conn = sqlite3.connect(seeded_db)
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = 'programs.get'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    r1 = client.post(
        "/v1/programs/batch",
        headers=headers,
        json={"unified_ids": ["UNI-test-s-1"]},
    )
    assert r1.status_code == 200, r1.text

    conn = sqlite3.connect(seeded_db)
    try:
        updated = conn.execute(
            "UPDATE am_idempotency_cache SET response_blob = ? "
            "WHERE cache_key = ("
            "  SELECT cache_key FROM am_idempotency_cache "
            "  WHERE response_blob NOT LIKE '__bodyfp__:%' "
            "    AND response_blob NOT LIKE '__pending__:%' "
            "  ORDER BY created_at DESC LIMIT 1"
            ")",
            ("not-json",),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    assert updated == 1

    r2 = client.post(
        "/v1/programs/batch",
        headers=headers,
        json={"unified_ids": ["UNI-test-s-1"]},
    )
    assert r2.status_code == 503, r2.text
    assert r2.headers.get("X-Metered") == "false"
    assert r2.headers.get("X-Cost-Yen") == "0"
    assert r2.json()["error"] == "idempotency_cache_unavailable"

    conn = sqlite3.connect(seeded_db)
    try:
        after = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = 'programs.get'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert after == before + 1
