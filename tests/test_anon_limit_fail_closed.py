"""Anon rate-limit fail-CLOSED behaviour (regression for the 2026-05-04 flip).

Pre-2026-05-04 the dep failed OPEN: a `sqlite3.Error` on the bucket
write was logged and the request was let through. That over-served
anon quota indefinitely (any caller who could lock `anon_rate_limit`
got unlimited free 3/日 calls) and put the ¥3/req metered path at
risk of leaking through the same self-DoS path.

These tests pin the new fail-CLOSED contract:

  1. When `_try_increment` raises `sqlite3.Error` (simulating a DB lock /
     I/O failure), the dep raises `AnonRateLimitExceeded` and the
     response is HTTP 429 — NOT 200, NOT 500.
  2. The 429 envelope carries `reason="rate_limit_unavailable"` so
     operators / dashboards / clients can distinguish a backend outage
     from a real over-quota event.
  3. The "real" rate-exceeded path (DB healthy, count > limit) carries
     `reason="rate_limit_exceeded"` so the two are unambiguously split.
  4. The fail-closed envelope still carries the same upgrade / Retry-After
     contract as a normal 429 — bilingual `detail`/`detail_en`, `limit`,
     `resets_at`, `Retry-After` header — so existing client retry logic
     keeps working.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest
    from fastapi.testclient import TestClient


def _import_anon():
    """Re-import the dep module each call so the monkeypatch in one test
    does not leak into the next."""
    import importlib
    import sys

    mod = sys.modules.get("jpintel_mcp.api.anon_limit")
    if mod is None:
        mod = importlib.import_module("jpintel_mcp.api.anon_limit")
    return mod


# ---------------------------------------------------------------------------
# Fail-closed: DB lock -> 429 with reason="rate_limit_unavailable"
# ---------------------------------------------------------------------------


def test_db_lock_returns_429_not_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-fix: this asserted 200 (fail-open). Post-fix: must be 429."""
    anon = _import_anon()

    def _raise_locked(*_args, **_kwargs):
        # OperationalError("database is locked") is the canonical
        # sqlite3.Error subclass our production lock-loop produces.
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(anon, "_try_increment", _raise_locked)

    r = client.get("/meta", headers={"x-forwarded-for": "203.0.113.77"})
    assert r.status_code == 429, (
        f"expected fail-CLOSED 429 on DB lock, got {r.status_code}: {r.text[:200]}"
    )


def test_db_lock_envelope_has_unavailable_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fail-closed envelope distinguishes itself from a real over-quota
    via reason='rate_limit_unavailable'."""
    anon = _import_anon()

    def _raise_io(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(anon, "_try_increment", _raise_io)

    r = client.get("/meta", headers={"x-forwarded-for": "203.0.113.78"})
    assert r.status_code == 429
    body = r.json()
    assert body.get("code") == "rate_limit_unavailable", (
        f"missing or wrong code in fail-closed envelope: {body}"
    )
    assert body.get("reason") == "rate_limit_unavailable", (
        f"missing or wrong reason in fail-closed envelope: {body}"
    )
    # Contract: bilingual copy, limit + resets_at + Retry-After header
    # all present so existing client retry logic still works.
    assert "limit" in body
    assert "resets_at" in body
    assert "detail" in body and "detail_en" in body
    assert r.headers.get("Retry-After") is not None
    assert int(r.headers["Retry-After"]) >= 60  # floor enforced


def test_real_quota_exceed_carries_distinct_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The healthy-DB over-quota path carries reason='rate_limit_exceeded'
    so it is unambiguously split from the fail-closed envelope above."""
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "anon_rate_limit_per_day", 2)

    ip = "203.0.113.79"
    # Burn the quota legitimately (DB healthy).
    for _ in range(2):
        assert client.get("/meta", headers={"x-forwarded-for": ip}).status_code == 200

    # 3rd call -> real over-quota (NOT fail-closed).
    r = client.get("/meta", headers={"x-forwarded-for": ip})
    assert r.status_code == 429
    body = r.json()
    assert body.get("code") == "rate_limit_exceeded", (
        f"real over-quota envelope must carry code=rate_limit_exceeded, got {body}"
    )
    assert body.get("reason") == "rate_limit_exceeded", (
        f"real over-quota envelope must carry reason=rate_limit_exceeded, got {body}"
    )
    # Sanity: NOT the unavailable reason.
    assert body["reason"] != "rate_limit_unavailable"


def test_db_generic_sqlite_error_also_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sqlite3.Error (not just OperationalError) must also trigger fail-closed.
    The except clause is `except sqlite3.Error` which is the parent of every
    sqlite3-defined exception — pinning it here so a future narrowing edit
    breaks the test."""
    anon = _import_anon()

    def _raise_generic(*_args, **_kwargs):
        raise sqlite3.DatabaseError("malformed write")

    monkeypatch.setattr(anon, "_try_increment", _raise_generic)

    r = client.get("/meta", headers={"x-forwarded-for": "203.0.113.80"})
    assert r.status_code == 429
    assert r.json().get("reason") == "rate_limit_unavailable"


def test_db_lock_envelope_carries_upgrade_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even on backend outage the conversion path must surface — a degraded
    rate limiter is no excuse to drop the upgrade hint that turns a friction
    moment into a paid signup."""
    anon = _import_anon()

    monkeypatch.setattr(
        anon,
        "_try_increment",
        lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
    )

    r = client.get("/meta", headers={"x-forwarded-for": "203.0.113.81"})
    assert r.status_code == 429
    body = r.json()
    assert body["upgrade_url"].startswith("https://jpcite.com/upgrade.html")
    assert r.headers.get("X-Anon-Upgrade-Url", "").startswith("https://jpcite.com/upgrade.html")
