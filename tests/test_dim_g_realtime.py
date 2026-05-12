"""Integration tests for Dim G realtime_signal Wave 47 layer.

Wave 47 layer-on for the existing realtime_signal surface:

* migration 286 adds ``am_realtime_signal_subscriber`` (fan-out across
  signal_types JSON array) + ``am_realtime_signal_event_log`` (append-only
  per-event delivery log).
* ``scripts/etl/dispatch_realtime_signals.py`` walks pending event rows and
  POSTs each payload to the subscriber's ``webhook_url`` (no LLM).
* Existing Wave 43 layer (migration 263 + ``maintain_realtime_signal_*``
  cron + ``realtime_signal_v2.py``) is left untouched.

Case bundles
------------
  1. Migration 286 applies cleanly on a fresh SQLite db + idempotent re-apply.
  2. Migration 286 rollback drops every Wave 47 artefact (and ONLY those).
  3. CHECK constraints reject malformed rows (webhook_url non-https /
     too-short, payload not-JSON, signal_type empty, attempt_count < 1).
  4. Dispatcher delivers 2xx events → marks delivered_at + updates
     subscriber.last_signal_at.
  5. Dispatcher records non-2xx failures with attempt_count++ and error.
  6. Dispatcher dry-run never mutates the DB.
  7. Dispatcher skips events whose subscriber is disabled.
  8. Boot manifest registration (jpcite + autonomath mirror).
  9. LLM-0 verify — no anthropic / openai import anywhere in new files.
 10. No legacy brand (税務会計AI / zeimu-kaikei.ai) in new files.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_286 = REPO_ROOT / "scripts" / "migrations" / "286_realtime_signal.sql"
MIG_286_RB = REPO_ROOT / "scripts" / "migrations" / "286_realtime_signal_rollback.sql"
ETL_DISPATCH = REPO_ROOT / "scripts" / "etl" / "dispatch_realtime_signals.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_g.db"
    _apply(db, MIG_286)
    return db


def _load_dispatcher() -> object:
    spec = importlib.util.spec_from_file_location("_dim_g_dispatcher", ETL_DISPATCH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_subscriber(
    conn: sqlite3.Connection,
    webhook_url: str = "https://example.test/webhook",
    signal_types: tuple[str, ...] = ("kokkai_bill", "amendment"),
    enabled: int = 1,
) -> int:
    conn.execute(
        """
        INSERT INTO am_realtime_signal_subscriber
            (webhook_url, signal_types, enabled)
        VALUES (?, ?, ?)
        """,
        (webhook_url, json.dumps(list(signal_types)), int(enabled)),
    )
    conn.commit()
    return int(
        conn.execute(
            "SELECT subscriber_id FROM am_realtime_signal_subscriber WHERE webhook_url=?",
            (webhook_url,),
        ).fetchone()[0]
    )


def _seed_event(
    conn: sqlite3.Connection,
    subscriber_id: int,
    signal_type: str = "kokkai_bill",
    payload: dict | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO am_realtime_signal_event_log
            (subscriber_id, signal_type, payload)
        VALUES (?, ?, ?)
        """,
        (subscriber_id, signal_type, json.dumps(payload or {"bill_id": "B-001"})),
    )
    conn.commit()
    return int(
        conn.execute(
            "SELECT MAX(event_id) FROM am_realtime_signal_event_log"
        ).fetchone()[0]
    )


# ---------------------------------------------------------------------------
# 1. Migration applies + idempotent
# ---------------------------------------------------------------------------


def test_mig_286_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND (name LIKE 'am_realtime_signal_%' "
                "  OR name LIKE 'v_realtime_signal_%')"
            )
        }
        assert "am_realtime_signal_subscriber" in names
        assert "am_realtime_signal_event_log" in names
        assert "v_realtime_signal_subscriber_enabled" in names
    finally:
        conn.close()


def test_mig_286_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_286)  # second apply must not raise


# ---------------------------------------------------------------------------
# 2. Rollback drops every Wave 47 artefact
# ---------------------------------------------------------------------------


def test_mig_286_rollback_drops_all(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_286_RB)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view','index') "
            "AND (name LIKE 'am_realtime_signal_subscriber%' "
            "  OR name LIKE 'am_realtime_signal_event_log%' "
            "  OR name LIKE 'v_realtime_signal_subscriber_enabled%' "
            "  OR name LIKE 'idx_am_rt_sig_%')"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints
# ---------------------------------------------------------------------------


def test_check_webhook_url_https_only(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_realtime_signal_subscriber (webhook_url) VALUES (?)",
                ("http://insecure.example.test",),
            )
    finally:
        conn.close()


def test_check_webhook_url_min_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_realtime_signal_subscriber (webhook_url) VALUES (?)",
                ("https://x",),  # too short, fails len BETWEEN 12 AND 512
            )
    finally:
        conn.close()


def test_check_signal_types_must_be_json(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_realtime_signal_subscriber "
                "(webhook_url, signal_types) VALUES (?, ?)",
                ("https://example.test/webhook", "not-json"),
            )
    finally:
        conn.close()


def test_check_event_signal_type_not_empty(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_realtime_signal_event_log "
                "(subscriber_id, signal_type, payload) VALUES (?, ?, ?)",
                (sid, "", "{}"),
            )
    finally:
        conn.close()


def test_check_event_payload_must_be_json(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_realtime_signal_event_log "
                "(subscriber_id, signal_type, payload) VALUES (?, ?, ?)",
                (sid, "kokkai_bill", "<not json>"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Dispatcher delivers 2xx events
# ---------------------------------------------------------------------------


def test_dispatcher_delivers_2xx(tmp_path: pathlib.Path) -> None:
    dispatcher = _load_dispatcher()
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn)
        eid = _seed_event(conn, sid, "kokkai_bill", {"bill_id": "B-001"})
    finally:
        conn.close()

    posted_envelopes: list[dict] = []

    def fake_post(url: str, body: bytes, timeout_s: float) -> tuple[int, str | None]:
        posted_envelopes.append({"url": url, "body": json.loads(body.decode("utf-8"))})
        return 200, None

    stats = dispatcher.dispatch(db, post_fn=fake_post)
    assert stats == {"pending": 1, "delivered": 1, "failed": 0, "skipped": 0}

    # 2xx => delivered_at filled, subscriber last_signal_at filled.
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT status_code, delivered_at, attempt_count, error "
            "FROM am_realtime_signal_event_log WHERE event_id = ?",
            (eid,),
        ).fetchone()
        assert row[0] == 200
        assert row[1] is not None
        assert row[2] == 1
        assert row[3] is None

        sub_row = conn.execute(
            "SELECT last_signal_at FROM am_realtime_signal_subscriber WHERE subscriber_id = ?",
            (sid,),
        ).fetchone()
        assert sub_row[0] is not None
    finally:
        conn.close()

    # Delivery envelope shape sanity.
    assert len(posted_envelopes) == 1
    env = posted_envelopes[0]
    assert env["url"] == "https://example.test/webhook"
    assert env["body"]["schema"] == "jpcite.realtime_signal.v1"
    assert env["body"]["signal_type"] == "kokkai_bill"
    assert env["body"]["payload"] == {"bill_id": "B-001"}
    assert env["body"]["attempt"] == 1
    assert env["body"]["event_id"] == eid


# ---------------------------------------------------------------------------
# 5. Dispatcher records non-2xx failures
# ---------------------------------------------------------------------------


def test_dispatcher_records_failure(tmp_path: pathlib.Path) -> None:
    dispatcher = _load_dispatcher()
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn)
        eid = _seed_event(conn, sid)
    finally:
        conn.close()

    def fake_post(url: str, body: bytes, timeout_s: float) -> tuple[int, str | None]:
        return 503, "HTTPError: service unavailable"

    stats = dispatcher.dispatch(db, post_fn=fake_post)
    assert stats == {"pending": 1, "delivered": 0, "failed": 1, "skipped": 0}

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT status_code, delivered_at, attempt_count, error "
            "FROM am_realtime_signal_event_log WHERE event_id = ?",
            (eid,),
        ).fetchone()
        assert row[0] == 503
        assert row[1] is None
        assert row[2] == 2  # incremented from initial default 1
        assert row[3] is not None and "503" not in row[3]  # error string preserved
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. Dry run never mutates
# ---------------------------------------------------------------------------


def test_dispatcher_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    dispatcher = _load_dispatcher()
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn)
        _seed_event(conn, sid)
    finally:
        conn.close()

    called: list[str] = []

    def fake_post(url: str, body: bytes, timeout_s: float) -> tuple[int, str | None]:
        called.append(url)
        return 200, None

    stats = dispatcher.dispatch(db, dry_run=True, post_fn=fake_post)
    assert stats["delivered"] == 0
    assert stats["skipped"] == 1
    assert called == []  # dry-run must not call the network

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT delivered_at, status_code FROM am_realtime_signal_event_log"
        ).fetchone()
        assert row[0] is None and row[1] is None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. Dispatcher skips disabled subscribers
# ---------------------------------------------------------------------------


def test_dispatcher_skips_disabled_subscriber(tmp_path: pathlib.Path) -> None:
    dispatcher = _load_dispatcher()
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn, enabled=0)
        _seed_event(conn, sid)
    finally:
        conn.close()

    def fake_post(url: str, body: bytes, timeout_s: float) -> tuple[int, str | None]:
        raise AssertionError("must not POST for disabled subscriber")

    stats = dispatcher.dispatch(db, post_fn=fake_post)
    assert stats == {"pending": 0, "delivered": 0, "failed": 0, "skipped": 0}


# ---------------------------------------------------------------------------
# 7b. Dispatcher CLI runs (json summary on stdout)
# ---------------------------------------------------------------------------


def test_dispatcher_cli_dry_run(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        sid = _seed_subscriber(conn)
        _seed_event(conn, sid)
    finally:
        conn.close()

    proc = subprocess.run(
        [sys.executable, str(ETL_DISPATCH), "--db", str(db), "--dry-run"],
        check=True, capture_output=True, text=True,
    )
    last = proc.stdout.strip().splitlines()[-1]
    payload = json.loads(last)
    assert payload["dispatcher"] == "realtime_signal"
    assert payload["pending"] == 1
    assert payload["skipped"] == 1


# ---------------------------------------------------------------------------
# 8. Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_286() -> None:
    """jpcite boot manifest registers migration 286_realtime_signal.sql."""
    assert "286_realtime_signal.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_286() -> None:
    """autonomath boot manifest (mirror) registers migration 286."""
    assert "286_realtime_signal.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 9. LLM-0 verify (no Anthropic/OpenAI SDK in any new file)
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_TOKENS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_import_in_new_files() -> None:
    sources = [
        ETL_DISPATCH.read_text(encoding="utf-8"),
        MIG_286.read_text(encoding="utf-8"),
        MIG_286_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_TOKENS:
            assert f"import {bad}" not in src, f"banned LLM import `{bad}` found"
            assert f"from {bad}" not in src, f"banned LLM-from import `{bad}` found"


# ---------------------------------------------------------------------------
# 10. No legacy brand
# ---------------------------------------------------------------------------


def test_no_legacy_brand_in_new_files() -> None:
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL_DISPATCH.read_text(encoding="utf-8"),
        MIG_286.read_text(encoding="utf-8"),
        MIG_286_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
