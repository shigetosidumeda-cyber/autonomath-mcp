from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent


def _load_script(name: str, rel_path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _REPO / rel_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stripe_usage_backfill_enqueues_usage_event_quantity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "backfill.db"
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                stripe_subscription_id TEXT
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER,
                stripe_synced_at TEXT,
                quantity INTEGER
            );
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO api_keys(key_hash, stripe_subscription_id) VALUES (?, ?)",
            ("kh_batch", "sub_batch"),
        )
        conn.executemany(
            "INSERT INTO usage_events("
            "id, key_hash, endpoint, ts, status, metered, stripe_synced_at, quantity"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (101, "kh_batch", "batch.get", now, 200, 1, None, 7),
                (102, "kh_batch", "legacy.null_quantity", now, 200, 1, None, None),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    enqueued: list[dict[str, Any]] = []

    def fake_enqueue(
        _conn: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
        **_kwargs: Any,
    ) -> int:
        enqueued.append(
            {
                "kind": kind,
                "payload": payload,
                "dedup_key": dedup_key,
            }
        )
        return len(enqueued)

    monkeypatch.setattr(mod, "enqueue", fake_enqueue)
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    assert report["scanned"] == 2
    assert report["enqueued"] == 2
    assert [row["payload"]["quantity"] for row in enqueued] == [7, 1]
    assert [row["payload"]["usage_event_id"] for row in enqueued] == [101, 102]
    assert [row["dedup_key"] for row in enqueued] == [
        "stripe_backfill:101",
        "stripe_backfill:102",
    ]


def test_stripe_usage_backfill_preserves_billing_idempotency_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_billing_idem_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "backfill_billing_idem.db"
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                stripe_subscription_id TEXT
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER,
                stripe_synced_at TEXT,
                quantity INTEGER,
                billing_idempotency_key TEXT
            );
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO api_keys(key_hash, stripe_subscription_id) VALUES (?, ?)",
            ("kh_idem", "sub_idem"),
        )
        conn.execute(
            "INSERT INTO usage_events("
            "id, key_hash, endpoint, ts, status, metered, stripe_synced_at,"
            "quantity, billing_idempotency_key"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                301,
                "kh_idem",
                "programs.get",
                now,
                200,
                1,
                None,
                2,
                "idem_req:u0:abcdef",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    enqueued: list[dict[str, Any]] = []

    def fake_enqueue(
        _conn: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
        **_kwargs: Any,
    ) -> int:
        enqueued.append({"kind": kind, "payload": payload, "dedup_key": dedup_key})
        return len(enqueued)

    monkeypatch.setattr(mod, "enqueue", fake_enqueue)
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    assert report["scanned"] == 1
    assert report["enqueued"] == 1
    assert enqueued[0]["payload"] == {
        "subscription_id": "sub_idem",
        "usage_event_id": 301,
        "quantity": 2,
        "idempotency_key": "idem_req:u0:abcdef",
    }


def test_stripe_usage_backfill_sweeps_older_than_window(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_old_window_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "backfill_old.db"
    old_ts = "2026-01-01T00:00:00+00:00"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                stripe_subscription_id TEXT
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER,
                stripe_synced_at TEXT,
                quantity INTEGER
            );
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO api_keys(key_hash, stripe_subscription_id) VALUES (?, ?)",
            ("kh_old", "sub_old"),
        )
        conn.execute(
            "INSERT INTO usage_events("
            "id, key_hash, endpoint, ts, status, metered, stripe_synced_at, quantity"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (201, "kh_old", "old.unsynced", old_ts, 200, 1, None, 2),
        )
        conn.commit()
    finally:
        conn.close()

    enqueued: list[dict[str, Any]] = []

    def fake_enqueue(
        _conn: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
        dedup_key: str | None = None,
        **_kwargs: Any,
    ) -> int:
        enqueued.append({"kind": kind, "payload": payload, "dedup_key": dedup_key})
        return len(enqueued)

    monkeypatch.setattr(mod, "enqueue", fake_enqueue)
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    assert report["scanned"] == 1
    assert report["enqueued"] == 1
    assert enqueued[0]["payload"] == {
        "subscription_id": "sub_old",
        "usage_event_id": 201,
        "quantity": 2,
    }
    assert enqueued[0]["dedup_key"] == "stripe_backfill:201"


def test_stripe_usage_backfill_requeues_failed_dedup_row(tmp_path: Path) -> None:
    mod = _load_script(
        "stripe_usage_backfill_requeue_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "backfill_requeue.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            INSERT INTO bg_task_queue(
                kind, payload_json, status, attempts, last_error, dedup_key
            ) VALUES (
                'stripe_usage_sync',
                '{"subscription_id":"old","usage_event_id":101,"quantity":1}',
                'failed',
                5,
                'stripe unavailable',
                'stripe_backfill:101'
            );
            """
        )

        was_new, task_id = mod._enqueue_one(
            conn,
            usage_event_id=101,
            subscription_id="sub_recovered",
            quantity=7,
        )
        row = conn.execute(
            "SELECT status, attempts, last_error, payload_json FROM bg_task_queue WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()

    assert was_new is True
    assert task_id == 1
    assert row[0] == "pending"
    assert row[1] == 0
    assert row[2] is None
    payload = json.loads(row[3])
    assert payload == {
        "subscription_id": "sub_recovered",
        "usage_event_id": 101,
        "quantity": 7,
    }


def test_stripe_usage_backfill_requeues_stale_processing_dedup_row(
    tmp_path: Path,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_stale_processing_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "backfill_stale_processing.db"
    stale = "2026-01-01T00:00:00.000Z"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            f"""
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            INSERT INTO bg_task_queue(
                kind, payload_json, status, attempts, last_error,
                dedup_key, updated_at, next_attempt_at
            ) VALUES (
                'stripe_usage_sync',
                '{{"subscription_id":"old","usage_event_id":202,"quantity":1}}',
                'processing',
                1,
                NULL,
                'stripe_backfill:202',
                '{stale}',
                '{stale}'
            );
            """
        )

        was_new, task_id = mod._enqueue_one(
            conn,
            usage_event_id=202,
            subscription_id="sub_recovered",
            quantity=3,
        )
        row = conn.execute(
            "SELECT status, attempts, last_error, payload_json FROM bg_task_queue WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()

    assert was_new is True
    assert task_id == 1
    assert row[0] == "pending"
    assert row[1] == 0
    assert row[2] is None
    assert json.loads(row[3]) == {
        "subscription_id": "sub_recovered",
        "usage_event_id": 202,
        "quantity": 3,
    }


def test_stripe_usage_backfill_requeues_done_dedup_row_when_event_unsynced(
    tmp_path: Path,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_done_requeue_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "backfill_done_requeue.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            INSERT INTO bg_task_queue(
                kind, payload_json, status, attempts, last_error, dedup_key
            ) VALUES (
                'stripe_usage_sync',
                '{"subscription_id":"old","usage_event_id":303,"quantity":1}',
                'done',
                1,
                NULL,
                'stripe_backfill:303'
            );
            """
        )

        was_new, task_id = mod._enqueue_one(
            conn,
            usage_event_id=303,
            subscription_id="sub_recovered",
            quantity=9,
        )
        row = conn.execute(
            "SELECT status, attempts, last_error, payload_json FROM bg_task_queue WHERE id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()

    assert was_new is True
    assert task_id == 1
    assert row[0] == "pending"
    assert row[1] == 0
    assert row[2] is None
    assert json.loads(row[3]) == {
        "subscription_id": "sub_recovered",
        "usage_event_id": 303,
        "quantity": 9,
    }


def _create_backfill_queue_db(db_path: Path, *, task_status: str, updated_at: str) -> None:
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                stripe_subscription_id TEXT
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER,
                stripe_synced_at TEXT,
                quantity INTEGER
            );
            CREATE TABLE bg_task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                dedup_key TEXT UNIQUE,
                updated_at TEXT,
                next_attempt_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO bg_task_queue("
            "kind, payload_json, status, attempts, last_error, "
            "dedup_key, updated_at, next_attempt_at"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                "stripe_usage_sync",
                json.dumps(
                    {
                        "subscription_id": "sub_widget",
                        "quantity": 1,
                        "idempotency_key": "widget_key_42",
                    }
                ),
                task_status,
                5,
                "stripe unavailable",
                "widget_overage:widget_key_42",
                updated_at,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_widget_overage_failed_queue_row_is_requeued(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_widget_failed_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "widget_failed_requeue.db"
    _create_backfill_queue_db(
        db_path,
        task_status="failed",
        updated_at="2026-05-01T00:00:00.000Z",
    )
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, attempts, last_error FROM bg_task_queue WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    assert report["widget_overage_requeued"] == 1
    assert row == ("pending", 0, None)


def test_widget_overage_requeue_hydrates_missing_idempotency_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_widget_idem_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "widget_missing_idem_requeue.db"
    _create_backfill_queue_db(
        db_path,
        task_status="failed",
        updated_at="2026-05-01T00:00:00.000Z",
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE bg_task_queue SET payload_json = ? WHERE id = 1",
            (json.dumps({"subscription_id": "sub_widget", "quantity": 1}),),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, payload_json FROM bg_task_queue WHERE id = 1").fetchone()
    finally:
        conn.close()

    assert report["widget_overage_requeued"] == 1
    assert row[0] == "pending"
    assert json.loads(row[1]) == {
        "subscription_id": "sub_widget",
        "quantity": 1,
        "idempotency_key": "widget_key_42",
    }


def test_widget_overage_requeue_enforces_dedup_idempotency_and_quantity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_widget_stale_payload_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "widget_stale_payload_requeue.db"
    _create_backfill_queue_db(
        db_path,
        task_status="failed",
        updated_at="2026-05-01T00:00:00.000Z",
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE bg_task_queue SET payload_json = ? WHERE id = 1",
            (
                json.dumps(
                    {
                        "subscription_id": "sub_widget",
                        "quantity": 99,
                        "idempotency_key": "wrong_retry_key",
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, payload_json FROM bg_task_queue WHERE id = 1").fetchone()
    finally:
        conn.close()

    assert report["widget_overage_requeued"] == 1
    assert row[0] == "pending"
    assert json.loads(row[1]) == {
        "subscription_id": "sub_widget",
        "quantity": 1,
        "idempotency_key": "widget_key_42",
    }


def test_widget_overage_stale_processing_row_is_recovered(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_usage_backfill_widget_stale_unit",
        "scripts/cron/stripe_usage_backfill.py",
    )
    db_path = tmp_path / "widget_stale_requeue.db"
    _create_backfill_queue_db(
        db_path,
        task_status="processing",
        updated_at="2026-01-01T00:00:00.000Z",
    )
    monkeypatch.setattr(mod, "safe_capture_message", lambda *args, **kwargs: None)

    report = mod.backfill(
        window_hours=24,
        max_events=10,
        dry_run=False,
        db_path=db_path,
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, attempts, last_error FROM bg_task_queue WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    assert report["widget_overage_requeued"] == 1
    assert row == ("pending", 0, None)


def test_stripe_reconcile_sums_usage_event_quantity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_script(
        "stripe_reconcile_unit",
        "scripts/cron/stripe_reconcile.py",
    )
    db_path = tmp_path / "reconcile.db"
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE api_keys (
                key_hash TEXT PRIMARY KEY,
                stripe_subscription_id TEXT
            );
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                ts TEXT NOT NULL,
                status INTEGER,
                metered INTEGER,
                quantity INTEGER
            );
            """
        )
        conn.executemany(
            "INSERT INTO api_keys(key_hash, stripe_subscription_id) VALUES (?, ?)",
            [("kh_a", "sub_a"), ("kh_b", "sub_b")],
        )
        conn.executemany(
            "INSERT INTO usage_events("
            "key_hash, endpoint, ts, status, metered, quantity"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("kh_a", "batch.get", now, 200, 1, 3),
                ("kh_a", "legacy.null_quantity", now, 200, 1, None),
                ("kh_b", "bulk.evaluate", now, None, 1, 5),
                ("kh_a", "client.error", now, 400, 1, 11),
                ("kh_b", "unmetered", now, 200, 0, 13),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    reported_by_sub = {"sub_a": 4, "sub_b": 5}

    def fake_stripe_usage_for_sub(
        subscription_id: str,
        *,
        since_ts: int,
        until_ts: int,
    ) -> int:
        assert since_ts < until_ts
        return reported_by_sub[subscription_id]

    monkeypatch.setattr(mod, "_stripe_usage_for_sub", fake_stripe_usage_for_sub)

    report = mod.reconcile(
        window_hours=24,
        threshold=0.001,
        dry_run=True,
        db_path=db_path,
        output_dir=tmp_path / "reports",
    )

    assert report["expected_usage"] == 9
    assert report["reported_usage"] == 9
    assert report["diff_abs"] == 0
    per_sub = {row["sub_id"]: row for row in report["per_subscription"]}
    assert per_sub["sub_a"]["expected"] == 4
    assert per_sub["sub_b"]["expected"] == 5
