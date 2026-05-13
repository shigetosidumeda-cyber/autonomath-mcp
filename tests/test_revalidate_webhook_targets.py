"""Tests for scripts/cron/revalidate_webhook_targets.

R2 P1-4 follow-on: register-time validation cannot catch DNS drift on its
own. The daily cron walks every active customer_webhooks row, re-resolves
the URL, and flips ``status='disabled' + disabled_reason='dns_drift_unsafe'``
on any row whose hostname now points at RFC1918 / loopback / link-local
space.

Coverage:
  * Hostname drifts → public IP : row stays active.
  * Hostname drifts → RFC1918   : row flips disabled with reason prefix.
  * Already-inactive rows       : skipped (disabled_reason preserved).
  * IP literal → loopback      : row flips disabled (no DNS call needed).
  * Dry-run                    : same summary, no DB mutation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def revalidate_db(seeded_db: Path) -> Path:
    """Apply migration 080 and clear customer_webhooks for each test."""
    repo = Path(__file__).resolve().parent.parent
    sql_path = repo / "scripts" / "migrations" / "080_customer_webhooks.sql"
    sql = sql_path.read_text(encoding="utf-8")

    c = sqlite3.connect(seeded_db)
    try:
        c.executescript(sql)
        c.execute("DELETE FROM webhook_deliveries")
        c.execute("DELETE FROM customer_webhooks")
        c.commit()
    finally:
        c.close()
    return seeded_db


def _insert_webhook(
    db_path: Path,
    *,
    url: str,
    status: str = "active",
    disabled_reason: str | None = None,
    api_key_hash: str = "key_hash_revalidate_test",
) -> int:
    c = sqlite3.connect(db_path)
    try:
        cur = c.execute(
            "INSERT INTO customer_webhooks(api_key_hash, url, event_types_json, "
            "secret_hmac, status, failure_count, created_at, updated_at, "
            "disabled_reason) "
            "VALUES (?, ?, ?, ?, ?, 0, datetime('now'), datetime('now'), ?)",
            (
                api_key_hash,
                url,
                json.dumps(["program.created"]),
                "whsec_revalidate_test",
                status,
                disabled_reason,
            ),
        )
        wid = cur.lastrowid
        c.commit()
    finally:
        c.close()
    assert wid is not None
    return wid


def _read_row(db_path: Path, wid: int) -> dict:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT status, disabled_reason FROM customer_webhooks WHERE id = ?",
            (wid,),
        ).fetchone()
    finally:
        c.close()
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_revalidate_keeps_public_resolving_active(
    revalidate_db: Path,
    monkeypatch,
):
    """Hostname resolves to a public IP → row stays active."""
    from scripts.cron import revalidate_webhook_targets as rev

    wid = _insert_webhook(revalidate_db, url="https://good.example.com/hook")

    def _fake_getaddrinfo(host, *_args, **_kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(
        "jpintel_mcp.utils.webhook_safety.socket.getaddrinfo",
        _fake_getaddrinfo,
    )

    summary = rev.run(jpintel_db=revalidate_db)
    assert summary["active_examined"] == 1
    assert summary["kept_active"] == 1
    assert summary["flagged_unsafe"] == 0
    assert summary["dns_failed"] == 0

    row = _read_row(revalidate_db, wid)
    assert row["status"] == "active"
    assert row["disabled_reason"] is None


def test_revalidate_flags_dns_rebind_to_private_ip(
    revalidate_db: Path,
    monkeypatch,
):
    """Hostname now resolves to RFC1918 → row flips disabled."""
    from scripts.cron import revalidate_webhook_targets as rev

    wid = _insert_webhook(revalidate_db, url="https://rebind.example.com/hook")

    def _fake_getaddrinfo(host, *_args, **_kwargs):
        return [(2, 1, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(
        "jpintel_mcp.utils.webhook_safety.socket.getaddrinfo",
        _fake_getaddrinfo,
    )

    summary = rev.run(jpintel_db=revalidate_db)
    assert summary["active_examined"] == 1
    assert summary["flagged_unsafe"] == 1
    assert summary["kept_active"] == 0

    row = _read_row(revalidate_db, wid)
    assert row["status"] == "disabled"
    assert row["disabled_reason"] is not None
    assert row["disabled_reason"].startswith("dns_drift_unsafe:")
    assert "internal_ip_resolved" in row["disabled_reason"]


def test_revalidate_skips_already_inactive(
    revalidate_db: Path,
    monkeypatch,
):
    """status='disabled' rows are NOT re-examined and reason is preserved.

    Re-examining disabled rows would (a) waste DNS look-ups and (b) clobber
    the original disabled_reason ("5 consecutive failures" overwritten by
    "dns_drift_unsafe" on the next pass). The cron must skip them entirely.
    """
    from scripts.cron import revalidate_webhook_targets as rev

    wid_active = _insert_webhook(
        revalidate_db,
        url="https://still-active.example.com/hook",
    )
    wid_inactive = _insert_webhook(
        revalidate_db,
        url="https://inactive.example.com/hook",
        status="disabled",
        disabled_reason="5 consecutive failures: timeout",
    )

    call_log: list[str] = []

    def _fake_getaddrinfo(host, *_args, **_kwargs):
        call_log.append(host)
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(
        "jpintel_mcp.utils.webhook_safety.socket.getaddrinfo",
        _fake_getaddrinfo,
    )

    summary = rev.run(jpintel_db=revalidate_db)
    assert summary["active_examined"] == 1
    assert summary["kept_active"] == 1

    # Only the active row's host was resolved.
    assert call_log == ["still-active.example.com"]

    # Disabled row's original reason is preserved verbatim.
    inactive = _read_row(revalidate_db, wid_inactive)
    assert inactive["status"] == "disabled"
    assert inactive["disabled_reason"] == "5 consecutive failures: timeout"

    # Active row still active.
    active = _read_row(revalidate_db, wid_active)
    assert active["status"] == "active"


def test_revalidate_flags_ip_literal_to_loopback(revalidate_db: Path):
    """IP literal → loopback → row flips disabled (no DNS lookup needed)."""
    from scripts.cron import revalidate_webhook_targets as rev

    wid = _insert_webhook(revalidate_db, url="https://127.0.0.1/hook")

    summary = rev.run(jpintel_db=revalidate_db)
    assert summary["active_examined"] == 1
    assert summary["flagged_unsafe"] == 1

    row = _read_row(revalidate_db, wid)
    assert row["status"] == "disabled"
    assert "internal_ip_literal" in (row["disabled_reason"] or "")


def test_revalidate_dry_run_does_not_mutate(
    revalidate_db: Path,
    monkeypatch,
):
    """--dry-run reports flags but never writes."""
    from scripts.cron import revalidate_webhook_targets as rev

    wid = _insert_webhook(revalidate_db, url="https://rebind.example.com/hook")

    def _fake_getaddrinfo(host, *_args, **_kwargs):
        return [(2, 1, 6, "", ("172.16.0.5", 0))]

    monkeypatch.setattr(
        "jpintel_mcp.utils.webhook_safety.socket.getaddrinfo",
        _fake_getaddrinfo,
    )

    summary = rev.run(jpintel_db=revalidate_db, dry_run=True)
    assert summary["flagged_unsafe"] == 1
    assert summary["dry_run"] is True

    row = _read_row(revalidate_db, wid)
    assert row["status"] == "active"
    assert row["disabled_reason"] is None
