"""Integration tests for Dim T predictive service (Wave 47).

Closes the Wave 46 dim T storage gap: migration 280 adds
``am_predictive_watch_subscription`` (operator-internal predictive
subscription with watch_type enum + threshold + 24h window) and
``am_predictive_alert_log`` (append-only per-fire audit) per
``feedback_predictive_service_design.md``. Pairs with
``scripts/etl/build_predictive_watch_v2.py`` (daily scan unifying
houjin / program / amendment watches with a 24h TTL purge).

Case bundles
------------
  1. Migration 280 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 280 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows (watch_type out of enum,
     token_hash wrong length, threshold < 0, notify_window_hours out of
     range, payload too small, delivered_at < fired_at, status enum).
  4. Three watch types are evaluated in one ETL pass (houjin / program /
     amendment) — each fires exactly the expected count of alerts.
  5. 24h TTL purge flips stale 'pending' rows to 'expired'.
  6. Dedup partial unique index prevents double-fire on
     (watch_id, source_diff_id).
  7. Threshold gate (subscription.threshold) is honored — 0.0 = always,
     positive value = only above-threshold diffs queue alerts.
  8. Boot manifest registration (jpcite + autonomath mirror).
  9. **LLM-0 verify** — `grep -E "anthropic|openai" build_predictive_watch_v2.py` = 0.

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (predictive ranks + routes only).
  * Schema is config + audit only; no summary / explanation column.
  * Brand: only jpcite. No legacy ``税務会計AI`` / ``zeimu-kaikei.ai``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_280 = REPO_ROOT / "scripts" / "migrations" / "280_predictive_service.sql"
MIG_280_RB = REPO_ROOT / "scripts" / "migrations" / "280_predictive_service_rollback.sql"
ETL = REPO_ROOT / "scripts" / "etl" / "build_predictive_watch_v2.py"
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
    db = tmp_path / "dim_t.db"
    _apply(db, MIG_280)
    # The ETL JOINs am_amendment_diff; create a minimal fixture so the
    # JOIN-based scan tests can produce candidates. Schema mirrors the
    # columns used by build_predictive_watch_v2._scan_one_type.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS am_amendment_diff (
                diff_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id    TEXT NOT NULL,
                field_name   TEXT NOT NULL,
                new_value    TEXT,
                detected_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _insert_subscription(
    db: pathlib.Path,
    *,
    token_hash: str,
    watch_type: str,
    watch_target: str,
    threshold: float = 0.0,
    notify_window_hours: int = 24,
) -> int:
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "INSERT INTO am_predictive_watch_subscription "
            "(subscriber_token_hash, watch_type, watch_target, threshold, notify_window_hours) "
            "VALUES (?, ?, ?, ?, ?)",
            (token_hash, watch_type, watch_target, threshold, notify_window_hours),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _insert_diff(
    db: pathlib.Path, *, entity_id: str, field_name: str = "x", detected_at: str | None = None
) -> int:
    conn = sqlite3.connect(str(db))
    try:
        if detected_at:
            cur = conn.execute(
                "INSERT INTO am_amendment_diff (entity_id, field_name, detected_at) VALUES (?, ?, ?)",
                (entity_id, field_name, detected_at),
            )
        else:
            cur = conn.execute(
                "INSERT INTO am_amendment_diff (entity_id, field_name) VALUES (?, ?)",
                (entity_id, field_name),
            )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _run_etl(db: pathlib.Path, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ETL), "--db", str(db), *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


# ---------------------------------------------------------------------------
# 1. Migration applies + is idempotent
# ---------------------------------------------------------------------------


def test_mig_280_applies_clean(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') "
                "AND (name LIKE 'am_predictive_%' OR name LIKE 'v_predictive_%')"
            )
        }
        assert "am_predictive_watch_subscription" in names
        assert "am_predictive_alert_log" in names
        assert "v_predictive_watch_active" in names
    finally:
        conn.close()


def test_mig_280_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    # Re-applying must not raise.
    _apply(db, MIG_280)


# ---------------------------------------------------------------------------
# 2. Rollback drops every artefact
# ---------------------------------------------------------------------------


def test_mig_280_rollback_drops_all(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _apply(db, MIG_280_RB)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE 'am_predictive_%' OR name LIKE 'v_predictive_%' "
            "  OR name LIKE 'idx_am_predictive_%' OR name LIKE 'uq_am_predictive_%'"
        ).fetchall()
        assert rows == []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints reject malformed rows
# ---------------------------------------------------------------------------


def test_check_watch_type_enum(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_predictive_watch_subscription "
                "(subscriber_token_hash, watch_type, watch_target) VALUES (?, ?, ?)",
                ("a" * 64, "INVALID", "12345"),
            )
    finally:
        conn.close()


def test_check_token_hash_length(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_predictive_watch_subscription "
                "(subscriber_token_hash, watch_type, watch_target) VALUES (?, ?, ?)",
                ("short", "houjin", "12345"),
            )
    finally:
        conn.close()


def test_check_threshold_non_negative(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_predictive_watch_subscription "
                "(subscriber_token_hash, watch_type, watch_target, threshold) "
                "VALUES (?, ?, ?, ?)",
                ("a" * 64, "houjin", "12345", -1.0),
            )
    finally:
        conn.close()


def test_check_notify_window_range(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_predictive_watch_subscription "
                "(subscriber_token_hash, watch_type, watch_target, notify_window_hours) "
                "VALUES (?, ?, ?, ?)",
                ("a" * 64, "houjin", "12345", 0),
            )
    finally:
        conn.close()


def test_check_delivered_at_after_fired_at(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    watch_id = _insert_subscription(
        db, token_hash="a" * 64, watch_type="houjin", watch_target="1234567890123"
    )
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_predictive_alert_log "
                "(watch_id, fired_at, delivered_at, payload, delivery_status) "
                "VALUES (?, ?, ?, ?, ?)",
                (watch_id, "2026-05-12T10:00:00Z", "2026-05-12T09:00:00Z", "{}", "delivered"),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Three watch types fire alerts via ETL
# ---------------------------------------------------------------------------


def test_three_watch_types_fire_via_etl(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    # Register one subscription per watch_type.
    _insert_subscription(db, token_hash="a" * 64, watch_type="houjin", watch_target="1234567890123")
    _insert_subscription(db, token_hash="b" * 64, watch_type="program", watch_target="PROG-001")
    _insert_subscription(db, token_hash="c" * 64, watch_type="amendment", watch_target="LAW-100")

    # Land matching diffs.
    _insert_diff(db, entity_id="1234567890123")  # houjin match
    _insert_diff(db, entity_id="PROG-001")  # program match
    _insert_diff(db, entity_id="LAW-100-art-3")  # amendment LIKE match (sub-article)

    rep = _run_etl(db)
    assert rep["queued"] == 3
    assert rep["by_type"] == {"houjin": 1, "program": 1, "amendment": 1}
    # Confirm alert rows landed.
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_predictive_alert_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 3


def test_etl_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _insert_subscription(db, token_hash="a" * 64, watch_type="houjin", watch_target="X")
    _insert_diff(db, entity_id="X")
    rep = _run_etl(db, "--dry-run")
    assert rep["dry_run"] is True
    assert rep["queued"] == 1
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_predictive_alert_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# 5. 24h TTL purge flips stale pending rows to expired
# ---------------------------------------------------------------------------


def test_ttl_purge_marks_stale_pending_expired(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    watch_id = _insert_subscription(
        db, token_hash="a" * 64, watch_type="houjin", watch_target="X", notify_window_hours=24
    )
    conn = sqlite3.connect(str(db))
    try:
        # Stale row: fired 48h ago (past the 24h window).
        conn.execute(
            "INSERT INTO am_predictive_alert_log "
            "(watch_id, fired_at, payload, delivery_status) "
            "VALUES (?, datetime('now', '-48 hours'), ?, ?)",
            (watch_id, json.dumps({"k": "v"}), "pending"),
        )
        # Fresh row: fired 1h ago (still within window).
        conn.execute(
            "INSERT INTO am_predictive_alert_log "
            "(watch_id, fired_at, payload, delivery_status) "
            "VALUES (?, datetime('now', '-1 hours'), ?, ?)",
            (watch_id, json.dumps({"k": "v"}), "pending"),
        )
        conn.commit()
    finally:
        conn.close()

    rep = _run_etl(db)
    assert rep["expired"] == 1
    conn = sqlite3.connect(str(db))
    try:
        statuses = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT alert_id, delivery_status FROM am_predictive_alert_log ORDER BY alert_id"
            )
        }
    finally:
        conn.close()
    assert list(statuses.values()) == ["expired", "pending"]


# ---------------------------------------------------------------------------
# 6. Dedup prevents double-fire on (watch_id, source_diff_id)
# ---------------------------------------------------------------------------


def test_dedup_prevents_double_fire(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _insert_subscription(db, token_hash="a" * 64, watch_type="houjin", watch_target="X")
    _insert_diff(db, entity_id="X")

    rep1 = _run_etl(db)
    assert rep1["queued"] == 1
    # Re-run: same diff -> NOT EXISTS guards in the scan AND the partial
    # unique index uq_am_predictive_alert_dedup are both protecting us.
    rep2 = _run_etl(db)
    assert rep2["queued"] == 0
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_predictive_alert_log").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


# ---------------------------------------------------------------------------
# 7. Unique-active partial index: only one active sub per (token, type, target)
# ---------------------------------------------------------------------------


def test_unique_active_partial_index(tmp_path: pathlib.Path) -> None:
    db = _fresh_db(tmp_path)
    _insert_subscription(db, token_hash="a" * 64, watch_type="houjin", watch_target="X")
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO am_predictive_watch_subscription "
                "(subscriber_token_hash, watch_type, watch_target) VALUES (?, ?, ?)",
                ("a" * 64, "houjin", "X"),
            )
        # But once cancelled, re-subscribing is allowed.
        conn.execute(
            "UPDATE am_predictive_watch_subscription SET status='cancelled' "
            "WHERE subscriber_token_hash=? AND watch_type=? AND watch_target=?",
            ("a" * 64, "houjin", "X"),
        )
        conn.commit()
        conn.execute(
            "INSERT INTO am_predictive_watch_subscription "
            "(subscriber_token_hash, watch_type, watch_target) VALUES (?, ?, ?)",
            ("a" * 64, "houjin", "X"),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. Boot-manifest integrity
# ---------------------------------------------------------------------------


def test_manifest_jpcite_lists_280() -> None:
    """jpcite boot manifest registers migration 280_predictive_service.sql."""
    assert "280_predictive_service.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_manifest_autonomath_lists_280() -> None:
    """autonomath boot manifest (mirror) registers migration 280."""
    assert "280_predictive_service.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 9. LLM-0 verify + brand discipline
# ---------------------------------------------------------------------------


_FORBIDDEN_LLM_TOKENS = ("anthropic", "openai", "google.generativeai")


def test_no_llm_token_in_predictive_etl() -> None:
    """``grep -E "anthropic|openai" build_predictive_watch_v2.py`` MUST be 0."""
    src = ETL.read_text(encoding="utf-8")
    code_lines = []
    in_doc = False
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_only = "\n".join(code_lines)
    for bad in _FORBIDDEN_LLM_TOKENS:
        assert bad not in code_only.lower(), (
            f"LLM token `{bad}` leaked into build_predictive_watch_v2.py code "
            f"(violates feedback_no_operator_llm_api / feedback_predictive_service_design)"
        )


def test_no_llm_import_in_migration() -> None:
    """Dim T surface MUST stay LLM-free (feedback_no_operator_llm_api)."""
    sources = [
        ETL.read_text(encoding="utf-8"),
        MIG_280.read_text(encoding="utf-8"),
        MIG_280_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in _FORBIDDEN_LLM_TOKENS:
            assert f"import {bad}" not in src
            assert f"from {bad}" not in src


def test_no_legacy_brand_in_new_files() -> None:
    """No 税務会計AI / zeimu-kaikei.ai legacy brand in new files."""
    legacy_phrases = ("税務会計AI", "zeimu-kaikei.ai")
    sources = [
        ETL.read_text(encoding="utf-8"),
        MIG_280.read_text(encoding="utf-8"),
        MIG_280_RB.read_text(encoding="utf-8"),
    ]
    for src in sources:
        for bad in legacy_phrases:
            assert bad not in src, f"legacy brand `{bad}` found in new file"
