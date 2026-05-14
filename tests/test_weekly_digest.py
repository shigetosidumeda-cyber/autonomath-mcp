"""Tests for `scripts/cron/weekly_digest.py` (60-day Advisor Loop core).

Coverage focus matches the brief:
    * run_one() on a weekly-active row produces a digest
    * re-run within 7d is a no-op (idempotency gate)
    * daily-frequency rows are NOT picked up
    * is_active=0 rows are skipped
    * delta detection: NEW/REMOVED across runs
    * analytics_events row inserted on success with event_name='digest_delivered'

Schema posture: tests apply 079_saved_searches.sql + 099 channel columns +
113_weekly_digest_state.sql onto a tmp jpintel.db, then exercise
`weekly_digest.run_one` and `weekly_digest.run` directly.
"""

from __future__ import annotations

import importlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Fixture: minimal jpintel.db with saved_searches + analytics_events tables
# ---------------------------------------------------------------------------


def _apply_migration(conn: sqlite3.Connection, path: Path) -> None:
    """Execute the migration SQL idempotently.

    SQLite's executescript() handles multi-statement SQL correctly, but
    halts on the first error. Migration 113 contains ALTER TABLE ADD
    COLUMN which is non-idempotent — re-applying it raises "duplicate
    column name". To tolerate that on second-run, we pre-skip ALTER
    statements whose target column already exists by parsing the SQL.
    """
    sql = path.read_text(encoding="utf-8")
    # Strip line comments to make the regex below safe.
    cleaned_lines: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # Pre-skip ALTER TABLE ADD COLUMN whose column already exists.
    import re

    pattern = re.compile(
        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
        re.IGNORECASE,
    )
    statements_to_remove: list[str] = []
    for m in pattern.finditer(cleaned):
        table, col = m.group(1), m.group(2)
        try:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.OperationalError:
            existing = set()
        if col in existing:
            # Find the full statement (up to next semicolon) and mark it.
            start = m.start()
            end = cleaned.find(";", start)
            if end > start:
                statements_to_remove.append(cleaned[start : end + 1])

    for stmt in statements_to_remove:
        cleaned = cleaned.replace(stmt, "")

    try:
        conn.executescript(cleaned)
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "duplicate column" in msg or "already exists" in msg:
            return
        raise


def _seed_programs(conn: sqlite3.Connection, programs: list[dict]) -> None:
    for p in programs:
        conn.execute(
            """INSERT OR REPLACE INTO programs(
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["unified_id"],
                p["primary_name"],
                None,
                p.get("authority_level", "国"),
                None,
                p.get("prefecture", "東京都"),
                None,
                p.get("program_kind", "補助金"),
                None,
                p.get("amount_max_man_yen"),
                None,
                None,
                None,
                p.get("tier", "A"),
                None,
                None,
                None,
                p.get("excluded", 0),
                None,
                None,
                None,
                json.dumps(p.get("target_types", []), ensure_ascii=False),
                json.dumps(p.get("funding_purpose", []), ensure_ascii=False),
                None,
                None,
                None,
                None,
                p.get("updated_at", datetime.now(UTC).isoformat()),
            ),
        )


@pytest.fixture()
def weekly_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fresh jpintel.db with all required tables for weekly_digest."""
    db_path = tmp_path / "jpintel.db"

    # Re-import the session module against this DB path. We need to set the
    # env BEFORE importing weekly_digest below so settings.db_path resolves
    # correctly. The module under test imports lazily inside run().
    monkeypatch.setenv("JPINTEL_DB_PATH", str(db_path))
    monkeypatch.setenv("API_KEY_SALT", "test-salt")

    # Build the minimal jpintel.db schema that weekly_digest needs.
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # programs table — needed by the search replay. We use the same
        # column shape the project schema uses (mirrors conftest.py).
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                aliases_json TEXT,
                authority_level TEXT,
                authority_name TEXT,
                prefecture TEXT,
                municipality TEXT,
                program_kind TEXT,
                official_url TEXT,
                amount_max_man_yen REAL,
                amount_min_man_yen REAL,
                subsidy_rate TEXT,
                trust_level TEXT,
                tier TEXT,
                coverage_score REAL,
                gap_to_tier_s_json TEXT,
                a_to_j_coverage_json TEXT,
                excluded INTEGER NOT NULL DEFAULT 0,
                exclusion_reason TEXT,
                crop_categories_json TEXT,
                equipment_category TEXT,
                target_types_json TEXT,
                funding_purpose_json TEXT,
                amount_band TEXT,
                application_window_json TEXT,
                enriched_json TEXT,
                source_mentions_json TEXT,
                updated_at TEXT
            );
            -- analytics_events (mig 111) — base shape; mig 113 adds columns.
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status INTEGER NOT NULL,
                latency_ms INTEGER,
                key_hash TEXT,
                anon_ip_hash TEXT,
                client_tag TEXT,
                is_anonymous INTEGER NOT NULL DEFAULT 0
            );
            """
        )

        # Apply migration 079 (saved_searches base) + 099 channel columns + 113.
        _apply_migration(conn, REPO / "scripts" / "migrations" / "079_saved_searches.sql")
        # 099 — only the saved_searches column-add half (course_subscriptions
        # is unrelated to weekly_digest, but the migration is idempotent so
        # applying the whole thing is fine here).
        _apply_migration(conn, REPO / "scripts" / "migrations" / "099_recurring_engagement.sql")
        _apply_migration(conn, REPO / "scripts" / "migrations" / "113_weekly_digest_state.sql")

        # Seed 5 programs all matching the saved query (prefecture='東京都').
        base_now = datetime.now(UTC)
        _seed_programs(
            conn,
            [
                {
                    "unified_id": "wd-test-1",
                    "primary_name": "東京都 サンプル補助金 1",
                    "prefecture": "東京都",
                    "tier": "A",
                    "amount_max_man_yen": 500.0,
                    "updated_at": (base_now - timedelta(days=1)).isoformat(),
                },
                {
                    "unified_id": "wd-test-2",
                    "primary_name": "東京都 サンプル補助金 2",
                    "prefecture": "東京都",
                    "tier": "A",
                    "amount_max_man_yen": 1000.0,
                    "updated_at": (base_now - timedelta(days=2)).isoformat(),
                },
                {
                    "unified_id": "wd-test-3",
                    "primary_name": "東京都 サンプル補助金 3",
                    "prefecture": "東京都",
                    "tier": "B",
                    "amount_max_man_yen": 200.0,
                    "updated_at": (base_now - timedelta(days=3)).isoformat(),
                },
                {
                    "unified_id": "wd-test-4",
                    "primary_name": "東京都 サンプル補助金 4",
                    "prefecture": "東京都",
                    "tier": "B",
                    "amount_max_man_yen": 100.0,
                    "updated_at": (base_now - timedelta(days=4)).isoformat(),
                },
                {
                    "unified_id": "wd-test-5",
                    "primary_name": "東京都 サンプル補助金 5",
                    "prefecture": "東京都",
                    "tier": "A",
                    "amount_max_man_yen": 800.0,
                    "updated_at": (base_now - timedelta(days=5)).isoformat(),
                },
            ],
        )

        # Seed 3 saved_searches:
        # 1) weekly + active — should be picked up
        # 2) daily + active  — must NOT be picked up
        # 3) weekly + inactive — must NOT be picked up
        common_query = json.dumps(
            {"prefecture": "東京都"}, ensure_ascii=False, separators=(",", ":")
        )
        conn.execute(
            "INSERT INTO saved_searches("
            "  api_key_hash, name, query_json, frequency, notify_email,"
            "  channel_format, channel_url, last_run_at, created_at,"
            "  is_active"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "key_hash_weekly",
                "東京都の補助金 (週次)",
                common_query,
                "weekly",
                "test_weekly@example.com",
                "email",
                None,
                None,
                base_now.isoformat(),
                1,
            ),
        )
        conn.execute(
            "INSERT INTO saved_searches("
            "  api_key_hash, name, query_json, frequency, notify_email,"
            "  channel_format, channel_url, last_run_at, created_at,"
            "  is_active"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "key_hash_daily",
                "東京都の補助金 (日次)",
                common_query,
                "daily",
                "test_daily@example.com",
                "email",
                None,
                None,
                base_now.isoformat(),
                1,
            ),
        )
        conn.execute(
            "INSERT INTO saved_searches("
            "  api_key_hash, name, query_json, frequency, notify_email,"
            "  channel_format, channel_url, last_run_at, created_at,"
            "  is_active"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "key_hash_paused",
                "東京都の補助金 (休止中)",
                common_query,
                "weekly",
                "test_paused@example.com",
                "email",
                None,
                None,
                base_now.isoformat(),
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Force re-import of weekly_digest so settings is bound fresh.
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp.config") or mod.startswith("jpintel_mcp.db"):
            del sys.modules[mod]
    if "weekly_digest" in sys.modules:
        del sys.modules["weekly_digest"]
    return db_path


def _import_module():
    """Import the cron module via importlib so the test re-imports cleanly
    against the freshly-mocked env."""
    spec = importlib.util.spec_from_file_location(
        "weekly_digest_under_test",
        REPO / "scripts" / "cron" / "weekly_digest.py",
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fetch_one_row(conn: sqlite3.Connection, freq: str, active: int = 1):
    return conn.execute(
        "SELECT id, api_key_hash, name, query_json, frequency, notify_email, "
        "       last_run_at, created_at, last_result_signature "
        "  FROM saved_searches "
        " WHERE frequency = ? AND is_active = ?",
        (freq, active),
    ).fetchone()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_one_weekly_active_produces_digest(weekly_db: Path):
    """Test 1: run_one() on weekly-active produces digest."""
    mod = _import_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        row = _fetch_one_row(conn, "weekly", active=1)
        assert row is not None, "weekly active row must exist"
        outcome = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        assert outcome["status"] == "sent"
        assert outcome["delta_count"] >= 0
        # First run treats all 5 matches as NEW.
        assert outcome["new_count"] == 5
        assert outcome["all_count"] == 5

        # last_run_at must be bumped.
        bumped = conn.execute(
            "SELECT last_run_at, last_result_signature, last_delta_count "
            "FROM saved_searches WHERE id = ?",
            (row["id"],),
        ).fetchone()
        assert bumped["last_run_at"] is not None
        assert bumped["last_result_signature"] is not None
        assert bumped["last_delta_count"] == 5
    finally:
        conn.close()


def test_run_one_within_7d_window_skipped(weekly_db: Path):
    """Test 2: re-run within 7d window is a no-op."""
    mod = _import_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        row = _fetch_one_row(conn, "weekly", active=1)
        first = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        assert first["status"] == "sent"

        # Second pass within the window — fetch the now-bumped row and
        # call run_one again.
        row2 = _fetch_one_row(conn, "weekly", active=1)
        first_last_run_at = row2["last_run_at"]
        outcome2 = mod.run_one(
            jp_conn=conn,
            row=row2,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        assert outcome2["status"] == "skipped"
        assert outcome2["reason"] == "window"

        # last_run_at must NOT have advanced.
        post = conn.execute(
            "SELECT last_run_at FROM saved_searches WHERE id = ?",
            (row2["id"],),
        ).fetchone()
        assert post["last_run_at"] == first_last_run_at
    finally:
        conn.close()


def test_daily_frequency_not_picked_up(weekly_db: Path):
    """Test 3: daily-frequency rows are NOT picked up by the weekly cron."""
    mod = _import_module()
    summary = mod.run(dry_run=False, jpintel_db=weekly_db)
    # The sweep filters on frequency='weekly' AND is_active=1, so only the
    # ONE weekly+active row should be processed.
    assert summary["searches_run"] == 1
    assert summary["digests_sent"] == 1

    # Verify the daily row's last_run_at is still NULL — the cron never
    # touched it.
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        daily_row = conn.execute(
            "SELECT last_run_at FROM saved_searches WHERE frequency = 'daily'"
        ).fetchone()
        assert daily_row["last_run_at"] is None
    finally:
        conn.close()


def test_inactive_row_skipped(weekly_db: Path):
    """Test 4: is_active=0 rows are skipped."""
    mod = _import_module()
    summary = mod.run(dry_run=False, jpintel_db=weekly_db)
    assert summary["digests_sent"] == 1  # only the weekly+active one

    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        paused_row = conn.execute(
            "SELECT last_run_at, is_active FROM saved_searches "
            "WHERE api_key_hash = 'key_hash_paused'"
        ).fetchone()
        assert paused_row["is_active"] == 0
        assert paused_row["last_run_at"] is None
    finally:
        conn.close()


def test_delta_detection_new_then_modified_then_removed(weekly_db: Path):
    """Test 5: delta detection — first NEW=5, second after add NEW=1, removal
    surfaces REMOVED=1."""
    mod = _import_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        # First run: all 5 NEW.
        row = _fetch_one_row(conn, "weekly", active=1)
        first = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        assert first["new_count"] == 5

        # Add a 6th program AND remove one to verify both diff sides.
        future_now = datetime.now(UTC) + timedelta(days=8)
        conn.execute(
            "INSERT INTO programs("
            "  unified_id, primary_name, prefecture, tier, "
            "  amount_max_man_yen, target_types_json, funding_purpose_json, "
            "  excluded, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "wd-test-6",
                "東京都 サンプル補助金 6 (NEW row)",
                "東京都",
                "A",
                300.0,
                "[]",
                "[]",
                0,
                future_now.isoformat(),
            ),
        )
        conn.execute("DELETE FROM programs WHERE unified_id = ?", ("wd-test-1",))
        conn.commit()

        # Re-fetch the saved_searches row (signature column was updated).
        row2 = _fetch_one_row(conn, "weekly", active=1)
        # Pass a future "now" to bypass the 7d window gate.
        second = mod.run_one(
            jp_conn=conn,
            row=row2,
            now_utc=future_now,
            dry_run=False,
        )
        assert second["status"] == "sent", second
        # Net change: +1 NEW (wd-test-6), -1 REMOVED (wd-test-1).
        assert second["new_count"] == 1, second
        assert second["removed_count"] == 1, second
        assert second["all_count"] == 5
    finally:
        conn.close()


def test_analytics_events_row_inserted_on_success(weekly_db: Path):
    """Test 6: analytics_events row inserted with event_name='digest_delivered'."""
    mod = _import_module()
    conn = sqlite3.connect(str(weekly_db))
    conn.row_factory = sqlite3.Row
    try:
        row = _fetch_one_row(conn, "weekly", active=1)
        outcome = mod.run_one(
            jp_conn=conn,
            row=row,
            now_utc=datetime.now(UTC),
            dry_run=False,
        )
        assert outcome["status"] == "sent"

        ev = conn.execute(
            "SELECT event_name, saved_search_id, delta_count, key_hash, path "
            "  FROM analytics_events "
            " WHERE event_name = 'digest_delivered'"
        ).fetchall()
        assert len(ev) == 1
        assert ev[0]["event_name"] == "digest_delivered"
        assert ev[0]["saved_search_id"] == row["id"]
        assert ev[0]["delta_count"] == 5
        assert ev[0]["key_hash"] == "key_hash_weekly"
        assert ev[0]["path"] == "/cron/weekly_digest"
    finally:
        conn.close()


def test_rendered_digest_program_links_use_static_slug_urls():
    mod = _import_module()
    diff = {
        "hits": [
            {
                "unified_id": "UNI-static-link-1",
                "primary_name": "東京都 テスト補助金",
                "prefecture": "東京都",
                "amount_max_man_yen": 100,
                "updated_at": "2026-05-01T00:00:00Z",
                "_delta": "NEW",
            }
        ],
        "new": ["UNI-static-link-1"],
        "modified": [],
        "removed": [],
        "all_count": 1,
    }
    args = {
        "saved_name": "static link guard",
        "diff": diff,
        "manage_url": "https://jpcite.com/dashboard.html#saved-searches",
        "now_iso": "2026-05-14T00:00:00Z",
    }

    plaintext = mod._render_plaintext(**args)
    html = mod._render_html(**args)
    payload = mod._render_json(saved_id=1, **args)
    combined = "\n".join(
        [
            plaintext,
            html,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )

    assert "/programs/UNI-" not in combined
    assert re.search(r"https://jpcite\.com/programs/.+\.html", combined)


def test_digest_program_link_falls_back_without_required_static_fields():
    mod = _import_module()
    assert (
        mod._program_public_url({"unified_id": "UNI-static-link-2", "primary_name": ""})
        == "https://jpcite.com/dashboard.html#saved-searches"
    )
    assert (
        mod._program_public_url({"unified_id": "", "primary_name": "東京都 テスト補助金"})
        == "https://jpcite.com/dashboard.html#saved-searches"
    )


def test_cron_scripts_do_not_synthesize_program_links_from_unified_ids():
    unsafe_pattern = re.compile(r"/programs/\{[^}\n]*(?:unified_id|\['unified_id'\])")
    for rel in (
        Path("scripts/cron/weekly_digest.py"),
        Path("scripts/cron/morning_briefing.py"),
    ):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert not unsafe_pattern.search(src), f"{rel} synthesizes an unsafe program link"
