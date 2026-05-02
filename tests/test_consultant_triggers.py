"""Tests for the 補助金 consultant trigger trio.

Coverage:
    1. POST /v1/me/clients/bulk_evaluate
       - Cost preview (commit=false) returns row_count + estimated_yen.
       - Commit (commit=true) bills ¥3 × N rows AND returns a ZIP.
    2. scripts.cron.post_award_monitor.run
       - One client awarded with a milestone 7 days out → 1 alert fired
         + 1 usage_event row inserted with endpoint='post_award.alert'.
       - Re-running the same window is a no-op (idempotency log).
    3. scripts.cron.same_day_push.run
       - One newly-updated program + one matching client_profile
         → 1 delivery + 1 usage_event row with endpoint='same_day.push'.
       - Re-run inside the same window is a no-op.

Constraints honoured by these tests:
    - NO LLM call. Pure SQL + Python template assembly assertions.
    - NO real Postmark. Postmark module is module-not-found in the test
      env so the cron's `_deliver` returns True silently — fine for
      asserting "the row was processed".
"""
from __future__ import annotations

import contextlib
import io
import sqlite3
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def consultant_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_consultant_test",
        tier="paid",
        stripe_subscription_id="sub_consultant_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture()
def trial_consultant_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id="cus_consultant_trial", tier="trial")
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_trigger_tables(seeded_db: Path):
    """Apply migrations 087/096/098 onto the test DB."""
    repo = Path(__file__).resolve().parent.parent
    profiles = repo / "scripts" / "migrations" / "096_client_profiles.sql"
    post_award = repo / "scripts" / "migrations" / "098_program_post_award_calendar.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(profiles.read_text(encoding="utf-8"))
        c.executescript(post_award.read_text(encoding="utf-8"))
        # 087 is autonomath-target; idempotency cache table is named
        # am_idempotency_cache and we mirror it locally on jpintel.db
        # so bulk_evaluate's idem path works in tests.
        c.execute("""
            CREATE TABLE IF NOT EXISTS am_idempotency_cache (
                api_key_hash    TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                response_json   TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                PRIMARY KEY (api_key_hash, idempotency_key)
            )
        """)
        # Idempotency log tables for the two crons (the crons lazy-create
        # them too; doing it here means the cleanup TRUNCATE below works
        # cleanly between tests).
        c.execute("""
            CREATE TABLE IF NOT EXISTS post_award_alert_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                intention_id    INTEGER NOT NULL,
                milestone_kind  TEXT NOT NULL,
                window_days     INTEGER NOT NULL,
                fired_at        TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                ),
                UNIQUE (intention_id, milestone_kind, window_days)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS same_day_push_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id      TEXT NOT NULL,
                profile_id      INTEGER,
                api_key_hash    TEXT NOT NULL,
                fired_at        TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ','now')
                ),
                UNIQUE (program_id, api_key_hash, profile_id)
            )
        """)
        # Clean slate between cases.
        for table in (
            "client_profiles", "customer_intentions",
            "program_post_award_calendar", "post_award_alert_log",
            "same_day_push_log", "am_idempotency_cache",
        ):
            with contextlib.suppress(sqlite3.OperationalError):
                c.execute(f"DELETE FROM {table}")
        # Also wipe any usage_events from prior test runs so counters are
        # accurate when we COUNT(*) by endpoint below.
        c.execute(
            "DELETE FROM usage_events WHERE endpoint IN "
            "('post_award.alert','same_day.push','clients.bulk_evaluate')"
        )
        c.commit()
    finally:
        c.close()
    yield


# ---------------------------------------------------------------------------
# Sample CSV (5 顧問先) — fixture text shared across bulk_evaluate tests
# ---------------------------------------------------------------------------

SAMPLE_CSV = (
    "name_label,jsic_major,prefecture,employee_count,capital_yen,"
    "target_types\n"
    "株式会社A商事,E,東京都,12,5000000,sole_proprietor\n"
    "株式会社B製作所,E,大阪府,55,30000000,corporation|設備投資\n"
    "株式会社C農園,A,青森県,8,3000000,認定新規就農者\n"
    "株式会社D販売,I,東京都,150,80000000,corporation\n"
    "株式会社E食品,E,愛知県,22,10000000,corporation\n"
)


# ---------------------------------------------------------------------------
# 1. CSV bulk_evaluate
# ---------------------------------------------------------------------------


def test_bulk_evaluate_requires_auth(client):
    r = client.post(
        "/v1/me/clients/bulk_evaluate",
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={"commit": "false"},
    )
    assert r.status_code == 401


def test_bulk_evaluate_preview_returns_cost(client, consultant_key):
    r = client.post(
        "/v1/me/clients/bulk_evaluate",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={"commit": "false"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["preview"] is True
    assert body["row_count"] == 5
    assert body["estimated_yen"] == 15  # 5 × ¥3
    assert body["program_filter"] == "all"


def test_bulk_evaluate_commit_requires_paid_key(client, trial_consultant_key):
    r = client.post(
        "/v1/me/clients/bulk_evaluate",
        headers={"X-API-Key": trial_consultant_key},
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={
            "commit": "true",
            "idempotency_key": "trial-commit-blocked",
        },
    )
    assert r.status_code == 402
    body = r.json()
    assert body["detail"]["required_tier"] == "paid"
    assert body["detail"]["current_tier"] == "trial"


def test_bulk_evaluate_commit_bills_and_returns_zip(
    client, consultant_key, seeded_db,
):
    r = client.post(
        "/v1/me/clients/bulk_evaluate",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={
            "commit": "true",
            "idempotency_key": "test-idem-1",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/zip")
    assert r.headers.get("X-Row-Count") == "5"
    assert r.headers.get("X-Billed-Yen") == "15"

    # ZIP integrity + manifest.
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "manifest.json" in names
    # 5 client CSV files + 1 manifest => 6 total entries (or more if
    # name disambiguation kicked in — at least 5 CSV files).
    csv_names = [n for n in names if n.endswith(".csv")]
    assert len(csv_names) == 5

    # Bill assertion: bulk_evaluate now logs ONE usage_events row with
    # quantity=5 (single batch request → single audit row), not 5 separate
    # rows. This matches `bulk_evaluate.py` line 513-530 and avoids
    # fragmenting reconciliation. Stripe still charges quantity=5 = ¥15.
    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT quantity FROM usage_events "
            "WHERE endpoint = 'clients.bulk_evaluate'"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1, rows
    assert int(rows[0][0]) == 5, rows


def test_bulk_evaluate_commit_requires_idempotency_key(
    client, consultant_key,
):
    r = client.post(
        "/v1/me/clients/bulk_evaluate",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={"commit": "true"},  # missing idempotency_key
    )
    assert r.status_code == 400
    assert "idempotency_key" in r.text


def test_bulk_evaluate_idempotent_replay(
    client, consultant_key, seeded_db,
):
    # First call — should bill 5.
    r1 = client.post(
        "/v1/me/clients/bulk_evaluate",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={"commit": "true", "idempotency_key": "replay-key"},
    )
    assert r1.status_code == 200

    # Second call same idem key — should NOT bill again.
    r2 = client.post(
        "/v1/me/clients/bulk_evaluate",
        headers={"X-API-Key": consultant_key},
        files={"file": ("clients.csv", SAMPLE_CSV.encode("utf-8"))},
        data={"commit": "true", "idempotency_key": "replay-key"},
    )
    assert r2.status_code == 200
    assert r2.headers.get("X-Idempotent-Replay") == "1"

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT quantity FROM usage_events "
            "WHERE endpoint = 'clients.bulk_evaluate'"
        ).fetchall()
    finally:
        c.close()
    # Still 1 audit row with quantity=5 (only first call billed; the replay
    # short-circuits before log_usage). Single-row + quantity=N is the
    # post-Wave-21 contract — see test_bulk_evaluate_commit_bills_and_returns_zip.
    assert len(rows) == 1, rows
    assert int(rows[0][0]) == 5, rows


# ---------------------------------------------------------------------------
# 2. post_award_monitor cron
# ---------------------------------------------------------------------------


def _seed_intention_with_milestone(
    db_path: Path, key_hash: str, days_out: int,
) -> tuple[int, str]:
    """Insert one customer_intention + one program_post_award_calendar row
    so today + days_out maps to the milestone deadline.

    Returns (intention_id, program_id).
    """
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        program_id = "UNI-test-s-1"  # exists in seeded_db
        # awarded_at = today - 30. days_after_award = 30 + days_out.
        # → deadline = today + days_out.
        today = date.today()
        awarded = (today - timedelta(days=30)).isoformat()
        c.execute(
            "INSERT INTO program_post_award_calendar("
            "  program_id, milestone_kind, days_after_award, "
            "  kind_label, source_url"
            ") VALUES (?,?,?,?,?)",
            (
                program_id, "report_due_T+6m", 30 + days_out,
                "中間報告書 (試験)", "https://example.invalid/post-award",
            ),
        )
        cur = c.execute(
            "INSERT INTO customer_intentions("
            "  api_key_hash, profile_id, program_id, awarded_at, "
            "  status, notify_email"
            ") VALUES (?,?,?,?,?,?)",
            (
                key_hash, None, program_id, awarded,
                "awarded", "consultant@example.invalid",
            ),
        )
        intention_id = cur.lastrowid
        c.commit()
        return intention_id, program_id
    finally:
        c.close()


def test_post_award_monitor_fires_alert_at_7_days(
    seeded_db, consultant_key,
):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import post_award_monitor as pam

    key_hash = hash_api_key(consultant_key)
    intention_id, _ = _seed_intention_with_milestone(
        seeded_db, key_hash, days_out=7,
    )

    counters = pam.run(db_path=seeded_db)
    assert counters["alerts_fired"] == 1
    assert counters["alerts_skipped"] == 0

    # usage_event row recorded for the delivery.
    c = sqlite3.connect(seeded_db)
    try:
        (count,) = c.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE endpoint = 'post_award.alert'"
        ).fetchone()
        # Idempotency row in place.
        log_row = c.execute(
            "SELECT intention_id, milestone_kind, window_days "
            "FROM post_award_alert_log "
            "WHERE intention_id = ?",
            (intention_id,),
        ).fetchone()
    finally:
        c.close()
    assert count == 1
    assert log_row is not None
    assert log_row[2] == 7  # window_days


def test_post_award_monitor_idempotent(seeded_db, consultant_key):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import post_award_monitor as pam

    key_hash = hash_api_key(consultant_key)
    _seed_intention_with_milestone(seeded_db, key_hash, days_out=7)

    pam.run(db_path=seeded_db)
    second = pam.run(db_path=seeded_db)
    # Second run should skip (already in log).
    assert second["alerts_fired"] == 0
    assert second["alerts_skipped"] == 1


# ---------------------------------------------------------------------------
# 3. same_day_push cron
# ---------------------------------------------------------------------------


def _seed_matching_profile(db_path: Path, key_hash: str) -> int:
    """Insert one client_profile that matches UNI-test-s-1 (Tokyo/national).
    Returns profile_id."""
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(
            "INSERT INTO client_profiles("
            "  api_key_hash, name_label, jsic_major, prefecture, "
            "  employee_count, capital_yen, target_types_json, "
            "  last_active_program_ids_json"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                key_hash, "テスト顧問先A", "E", "東京都",
                12, 5000000,
                '["sole_proprietor","corporation"]',
                "[]",
            ),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _bump_program_updated_at(db_path: Path, program_id: str) -> None:
    """Set programs.updated_at to now so the cron's lookback window picks
    it up."""
    c = sqlite3.connect(db_path)
    try:
        c.execute(
            "UPDATE programs SET updated_at = ? WHERE unified_id = ?",
            (datetime.now(UTC).isoformat(), program_id),
        )
        c.commit()
    finally:
        c.close()


def test_same_day_push_fires_for_matching_profile(
    seeded_db, consultant_key,
):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import same_day_push as sdp

    key_hash = hash_api_key(consultant_key)
    profile_id = _seed_matching_profile(seeded_db, key_hash)
    _bump_program_updated_at(seeded_db, "UNI-test-s-1")

    # Use a non-existent autonomath path so the autonomath branch is a no-op.
    counters = sdp.run(
        db_path=seeded_db,
        autonomath_path=Path("/nonexistent/autonomath.db"),
        window_minutes=60,
    )
    assert counters["new_programs_seen"] >= 1
    assert counters["deliveries_fired"] >= 1

    c = sqlite3.connect(seeded_db)
    try:
        (count,) = c.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE endpoint = 'same_day.push'"
        ).fetchone()
        log = c.execute(
            "SELECT program_id, profile_id FROM same_day_push_log "
            "WHERE api_key_hash = ?",
            (key_hash,),
        ).fetchall()
    finally:
        c.close()
    assert count >= 1
    assert ("UNI-test-s-1", profile_id) in [(r[0], r[1]) for r in log]


def test_same_day_push_idempotent_within_window(
    seeded_db, consultant_key,
):
    from jpintel_mcp.api.deps import hash_api_key
    from scripts.cron import same_day_push as sdp

    key_hash = hash_api_key(consultant_key)
    _seed_matching_profile(seeded_db, key_hash)
    _bump_program_updated_at(seeded_db, "UNI-test-s-1")

    sdp.run(
        db_path=seeded_db,
        autonomath_path=Path("/nonexistent/autonomath.db"),
        window_minutes=60,
    )
    second = sdp.run(
        db_path=seeded_db,
        autonomath_path=Path("/nonexistent/autonomath.db"),
        window_minutes=60,
    )
    # Second run sees the same program but skips via the push log.
    assert second["deliveries_fired"] == 0
