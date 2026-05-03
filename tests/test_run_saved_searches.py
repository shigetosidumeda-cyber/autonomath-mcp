"""Tests for `scripts/cron/run_saved_searches.py` profile_ids fan-out.

Coverage focus is the gap-fix surface added by migration 097
(navit cancel trigger #1 — `saved_searches.profile_ids_json`):
    * profile_ids_json non-empty → 1 metered ¥3 delivery per 顧問先 with
      `usage_events.client_tag = profile_id`
    * profile_ids_json NULL / empty → legacy single delivery (no client_tag)
    * Both branches survive without autonomath.db (changed_ids = ∅) by
      pre-seeding `am_amendment_diff` so the cron has matches to deliver.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.billing.keys import issue_key
from scripts.cron import run_saved_searches as rss


@pytest.fixture()
def consultant_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_run_saved_test",
        tier="paid",
        stripe_subscription_id="sub_run_saved_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _ensure_saved_searches_with_fanout(seeded_db: Path):
    """Apply 079 (base) + 097 (profile_ids_json) onto the test DB."""
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations" / "079_saved_searches.sql"

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(base.read_text(encoding="utf-8"))
        cols = {r[1] for r in c.execute("PRAGMA table_info(saved_searches)")}
        if "profile_ids_json" not in cols:
            c.execute("ALTER TABLE saved_searches ADD COLUMN profile_ids_json TEXT")
        c.execute("DELETE FROM saved_searches")
        c.execute(
            "DELETE FROM usage_events WHERE endpoint = 'saved_searches.digest'"
        )
        c.commit()
    finally:
        c.close()
    yield


def _seed_saved_search(
    db_path: Path,
    *,
    api_key_hash: str,
    profile_ids: list[int] | None,
) -> int:
    c = sqlite3.connect(db_path)
    try:
        cur = c.execute(
            "INSERT INTO saved_searches("
            "  api_key_hash, name, query_json, frequency, "
            "  notify_email, profile_ids_json"
            ") VALUES (?,?,?,?,?,?)",
            (
                api_key_hash,
                "東京都の補助金",
                json.dumps({"prefecture": "東京都"}),
                "daily",
                "test@example.com",
                json.dumps(profile_ids) if profile_ids is not None else None,
            ),
        )
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def _seed_autonomath_with_diff(tmp_path: Path, unified_ids: list[str]) -> Path:
    """Build a minimal autonomath.db carrying am_amendment_diff so the cron
    surfaces the seeded matches without needing the full 9.4 GB fixture."""
    am_path = tmp_path / "autonomath.db"
    c = sqlite3.connect(am_path)
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS am_amendment_diff ("
            "  entity_id TEXT NOT NULL, detected_at TEXT NOT NULL"
            ")"
        )
        for uid in unified_ids:
            c.execute(
                "INSERT INTO am_amendment_diff(entity_id, detected_at) "
                "VALUES (?, '2099-01-01T00:00:00Z')",
                (uid,),
            )
        c.commit()
    finally:
        c.close()
    return am_path


def _patch_email_ok(monkeypatch) -> None:
    """Stub the email path so `sent` is True without invoking Postmark."""
    monkeypatch.setattr(
        rss, "_send_digest_email", lambda **_kw: {"ok": True}
    )


def _usage_rows(db_path: Path) -> list[tuple[str | None, int]]:
    c = sqlite3.connect(db_path)
    try:
        return c.execute(
            "SELECT client_tag, metered FROM usage_events "
            "WHERE endpoint = 'saved_searches.digest' "
            "ORDER BY id ASC"
        ).fetchall()
    finally:
        c.close()


def test_profile_ids_fanout_meters_one_row_per_profile(
    seeded_db: Path, consultant_key: str, monkeypatch, tmp_path: Path,
):
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(consultant_key)
    saved_id = _seed_saved_search(
        seeded_db, api_key_hash=key_hash, profile_ids=[101, 202, 303],
    )

    am_path = _seed_autonomath_with_diff(tmp_path, ["UNI-test-s-1"])
    _patch_email_ok(monkeypatch)

    summary = rss.run(
        dry_run=False,
        autonomath_db=am_path,
        jpintel_db=seeded_db,
    )

    # 1 saved_search × 3 profiles → 3 ¥3 deliveries metered.
    assert summary["emails_sent"] == 1
    assert summary["billed"] == 3
    rows = _usage_rows(seeded_db)
    assert len(rows) == 3, rows
    tags = sorted(str(r[0]) for r in rows)
    assert tags == ["101", "202", "303"]
    assert all(int(r[1]) == 1 for r in rows)
    assert saved_id  # keep used


def test_profile_ids_null_keeps_legacy_single_delivery(
    seeded_db: Path, consultant_key: str, monkeypatch, tmp_path: Path,
):
    from jpintel_mcp.api.deps import hash_api_key

    key_hash = hash_api_key(consultant_key)
    _seed_saved_search(seeded_db, api_key_hash=key_hash, profile_ids=None)

    am_path = _seed_autonomath_with_diff(tmp_path, ["UNI-test-s-1"])
    _patch_email_ok(monkeypatch)

    summary = rss.run(
        dry_run=False,
        autonomath_db=am_path,
        jpintel_db=seeded_db,
    )

    assert summary["emails_sent"] == 1
    assert summary["billed"] == 1
    rows = _usage_rows(seeded_db)
    assert len(rows) == 1
    assert rows[0][0] is None  # no client_tag in legacy path
