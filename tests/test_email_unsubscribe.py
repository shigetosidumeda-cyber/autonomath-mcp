"""Master-list email unsubscribe tests (P2.6.4 / 特電法 §3, 2026-04-25).

Covers:

  1. POST /v1/email/unsubscribe with a valid HMAC token writes to
     `email_unsubscribes` AND mirrors the opt-out into the legacy
     `subscribers.unsubscribed_at` flag, so all downstream callers
     (legacy newsletter cron, activation sequence) see the suppression.

  2. The scheduler's `_is_unsubscribed()` helper honours the master
     list — once a row lands in `email_unsubscribes`, the activation
     mail dispatch skips that recipient even if the legacy
     `subscribers` flag is still NULL.

Anti-enumeration is implicit in the response shape (always 200 +
{unsubscribed: true, at: <iso>}), so we don't assert on the failure
side here — the success-shape stability is what protects against
"is this email valid" probing.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _make_token(email: str) -> str:
    """Mirror `api.subscribers.make_unsubscribe_token` so the test can
    construct a valid token without importing the full router module."""
    import hashlib
    import hmac

    from jpintel_mcp.config import settings

    return hmac.new(
        settings.api_key_salt.encode("utf-8"),
        email.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _row_exists(db: Path, email: str) -> bool:
    c = sqlite3.connect(db)
    try:
        row = c.execute(
            "SELECT 1 FROM email_unsubscribes WHERE email = ? LIMIT 1",
            (email.strip().lower(),),
        ).fetchone()
    finally:
        c.close()
    return row is not None


def _legacy_row(db: Path, email: str) -> tuple[str | None, str | None] | None:
    c = sqlite3.connect(db)
    try:
        row = c.execute(
            "SELECT source, unsubscribed_at FROM subscribers WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    finally:
        c.close()
    return row


# ---------------------------------------------------------------------------
# Case 1: POST endpoint writes master row + mirrors legacy flag
# ---------------------------------------------------------------------------


def test_post_unsubscribe_writes_master_and_mirrors_legacy(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """A self-serve POST with a valid token must:

      * insert into `email_unsubscribes` (master),
      * flip `subscribers.unsubscribed_at` for the same address (so the
        legacy newsletter cron also stops).

    We seed the legacy `subscribers` row first so the UPDATE has
    something to flip. The master write is unconditional (INSERT OR
    IGNORE) and would fire even if the legacy row were missing.
    """
    email = "email-unsubscribe-alice@example.com"
    token = _make_token(email)

    # Seed an existing newsletter subscription so we can prove the mirror
    # write actually fires.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "INSERT INTO subscribers(email, source, created_at) VALUES (?, ?, datetime('now'))",
            (email, "test-seed"),
        )
        c.commit()
    finally:
        c.close()

    # Sanity: legacy row exists, unsubscribed_at NULL.
    legacy_before = _legacy_row(seeded_db, email)
    assert legacy_before is not None
    assert legacy_before[1] is None, "newsletter row should start un-suppressed"

    # And master list does not yet contain the email.
    assert not _row_exists(seeded_db, email)

    # Hit the endpoint.
    r = client.post(
        "/v1/email/unsubscribe",
        params={"email": email, "token": token, "reason": "user-self-serve"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unsubscribed"] is True
    assert body["at"].startswith(("20", "21"))  # ISO year prefix

    # Master row landed.
    assert _row_exists(seeded_db, email), "master email_unsubscribes row missing"

    # Legacy newsletter row is now flipped to unsubscribed.
    legacy_after = _legacy_row(seeded_db, email)
    assert legacy_after is not None
    assert legacy_after[1] is not None, "legacy subscribers.unsubscribed_at not flipped"

    # Idempotency: a second POST with same token returns the same shape
    # and does NOT raise / does not duplicate the master row.
    r2 = client.post(
        "/v1/email/unsubscribe",
        params={"email": email, "token": token, "reason": "user-self-serve"},
    )
    assert r2.status_code == 200, r2.text
    # Still exactly one row.
    c = sqlite3.connect(seeded_db)
    try:
        n = c.execute(
            "SELECT COUNT(*) FROM email_unsubscribes WHERE email = ?",
            (email,),
        ).fetchone()[0]
    finally:
        c.close()
    assert n == 1, f"expected 1 master row after re-unsubscribe, got {n}"


# ---------------------------------------------------------------------------
# Case 2: scheduler honours master list (skips activation send)
# ---------------------------------------------------------------------------


def test_scheduler_skips_when_email_on_master_list(
    client: TestClient,
    seeded_db: Path,
) -> None:
    """Once `email_unsubscribes` carries a row, the scheduler's pre-send
    suppression check must return True even when the legacy
    `subscribers.unsubscribed_at` is still NULL — the master list is the
    source of truth.

    We exercise the helper directly (not the cron loop) because run_due()
    has cron-internal scaffolding (email_schedule rows, key resolution)
    that is irrelevant to the suppression-check assertion. The helper IS
    the load-bearing decision point.
    """
    from jpintel_mcp.email.scheduler import _is_unsubscribed

    email = "bob@example.com"

    c = sqlite3.connect(seeded_db)
    try:
        # Pristine state — no master row, no legacy row. Helper returns False.
        assert _is_unsubscribed(c, email) is False

        # Add to master list ONLY (no legacy subscribers row).
        c.execute(
            "INSERT INTO email_unsubscribes(email, reason) VALUES (?, ?)",
            (email, "spam-complaint"),
        )
        c.commit()

        # Helper now returns True even though legacy table doesn't have a row.
        assert _is_unsubscribed(c, email) is True, (
            "scheduler did not honour master email_unsubscribes — broadcast "
            "send would still fire to a 特電法-opted-out address"
        )

        # And a different email is still allowed (no master row).
        assert _is_unsubscribed(c, "carol@example.com") is False
    finally:
        c.close()
